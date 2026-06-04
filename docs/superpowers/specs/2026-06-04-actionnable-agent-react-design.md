# Actionnable Agent ReAct Redesign

## Problem Statement

Actionnable agents in TAIC use a two-stage pipeline where Stage 1 (RAG/LLM) has no knowledge of available actions, causing the LLM to tell users "I can't do that" even when the plugin system supports the requested capability. Stage 2 (Gemini action detection) runs separately and may produce an action proposal that contradicts the text answer. The streaming path (`/ask-stream`) has no action detection at all. The result is a broken, inconsistent user experience.

## Solution

Replace the disconnected two-stage pipeline with a ReAct (Reasoning + Acting) agent loop. The agent reasons about the user's request, decides which tools to use, executes them (with user confirmation for side-effect actions), observes results, and continues reasoning until it can provide a final answer.

No framework dependency (no LangChain, no LlamaIndex). The ReAct loop is ~200 lines of Python using prompt engineering that works with any text-generating LLM (OpenAI, Gemini, Mistral).

## Architecture

### Data Flow

```
User question
    |
    v
[Agent type check]
    |
    +-- type != "actionnable" --> existing get_answer() / get_answer_stream() (unchanged)
    |
    +-- type == "actionnable" -->
        |
        v
    [AgentExecutor.run()]
        |
        v
    1. Load agent personality (contexte, biographie)
    2. Load enabled plugins --> convert to ToolDefinitions (read/write)
    3. Retrieve RAG context via rag_engine (document search only)
    4. Build ReAct system prompt (personality + tools + RAG context)
    5. Enter ReAct loop:
        |
        +-- LLM generates Thought + Action --> parse
        |       |
        |       +-- Tool is "read" (no side effect) --> auto-execute, add Observation, continue loop
        |       |
        |       +-- Tool is "write" (side effect) --> create ActionExecution(pending_confirmation)
        |               |                             yield action_proposal to frontend
        |               |                             SUSPEND loop (serialize state to DB)
        |               |
        |               +-- User confirms --> execute action, RESUME loop with Observation
        |               +-- User cancels  --> RESUME loop with "Action cancelled" Observation
        |
        +-- LLM generates Final Answer --> return to user
        |
        +-- Max iterations (6) reached --> force Final Answer from LLM
```

### ReAct Prompt Template

```
Tu es {agent.name}, un assistant IA actionnable.
{agent.contexte}
{agent.biographie}

Tu as acces aux outils suivants :

{for each tool}
- {tool.name}: {tool.description}
  Parametres: {JSON schema}
  Type: {"lecture seule" if read else "action (necessite confirmation)"}
{end for}

REGLES :
1. Utilise EXACTEMENT le format ci-dessous pour raisonner et agir.
2. Tu peux enchainer plusieurs actions avant de donner ta reponse finale.
3. Ne fabrique JAMAIS le resultat d'une action. Attends toujours l'Observation.
4. Si tu n'as pas besoin d'outil, reponds directement avec "Final Answer:".
5. Reponds toujours dans la langue de l'utilisateur.

FORMAT OBLIGATOIRE :

Thought: [ton raisonnement]
Action: [nom exact de l'outil]
Action Input: [JSON valide des parametres]

... tu recevras une Observation avec le resultat ...

Thought: [raisonnement sur le resultat]
Final Answer: [reponse finale a l'utilisateur]

{if rag_context}
--- Contexte documentaire ---
{rag_context}
{end if}
```

### AgentExecutor Loop

```python
class AgentExecutor:
    MAX_ITERATIONS = 6
    TOOL_TIMEOUT_SECONDS = 30

    def run(self, question, agent, history, db, user_id, credentials):
        """
        Synchronous execution. Returns dict with:
        - answer: str (final answer text)
        - steps: list[AgentStep] (full reasoning trace)
        - action_proposal: dict | None (if paused on write tool)
        - loop_state: str | None (serialized state if paused)
        - sources: list (RAG sources)
        """

    def run_stream(self, question, agent, history, db, user_id, credentials):
        """
        Generator yielding SSE events:
        - ("thought", {"content": "..."})
        - ("action", {"tool": "...", "args": {...}, "type": "read|write"})
        - ("observation", {"tool": "...", "result": {...}})
        - ("action_proposal", {"execution_id": ..., "plugin": ..., ...})
        - ("token", {"t": "..."})  -- streaming Final Answer
        - ("done", {"full_text": ..., "steps": [...], "sources": [...]})
        """

    def resume(self, loop_state, observation, db, credentials):
        """
        Resume a suspended loop after user confirmation/cancellation.
        Takes the serialized loop state and the observation from the executed
        (or cancelled) action. Continues the ReAct loop from where it paused.

        Returns same structure as run():
        - answer: str | None (final answer if loop finished, None if paused again)
        - steps: list[AgentStep] (new steps since resume)
        - action_proposal: dict | None (if paused on another write tool)
        - loop_state: str | None (new serialized state if paused again)

        This enables multi-step chains: search -> confirm send -> confirm reply
        where each confirmation triggers a resume that may pause again.
        """
```

### AgentLoopState (Serializable)

```python
@dataclass
class AgentLoopState:
    messages: list[dict]        # Accumulated LLM messages (system + history + steps)
    iteration: int              # Current iteration count
    steps: list[dict]           # Steps taken so far (for audit trail)
    agent_id: int
    user_id: int
    question: str               # Original question
    model_id: str
    sources: list               # RAG sources collected
```

Serialized to JSON and stored in `ActionExecution.loop_state` when the loop suspends on a write tool. This allows stateless resume after confirmation.

### LLM Output Parser

```python
def parse_llm_output(text: str, available_tools: list[str]) -> AgentStep:
    """
    Parse LLM text output into structured step.

    Returns one of:
    - ActionStep(thought, tool_name, tool_args)   -- when Action: detected
    - FinishStep(answer)                          -- when Final Answer: detected
    - FallbackStep(text)                          -- when format not followed (treat as final answer)

    Parsing rules:
    1. Look for "Final Answer:" prefix --> FinishStep
    2. Look for "Action:" and "Action Input:" --> extract tool name and JSON args
    3. Validate tool_name exists in available_tools
    4. If JSON parsing fails, attempt repair (strip markdown fences, trailing commas)
    5. If nothing matches, treat entire text as FallbackStep (graceful degradation)
    """
```

### Tool Categorization

Side-effect classification is declared by each plugin in its ActionDefinition:

```python
# plugins/base.py
@dataclass
class ActionDefinition:
    name: str
    description: str
    parameters_schema: dict
    display_name: str
    icon: str
    side_effect: bool = True    # True = "write" (needs confirmation), False = "read"
```

Plugin annotations:

| Plugin | Action | side_effect | Reason |
|--------|--------|-------------|--------|
| gmail | search_emails | False | Read-only |
| gmail | send_email | True | Sends real email |
| gmail | reply_email | True | Sends real reply |
| google_docs | create_doc | True | Creates document |
| google_sheets | create_sheet | True | Creates spreadsheet |
| google_calendar | list_events | False | Read-only |
| google_calendar | create_event | True | Creates event |
| google_drive | list_files | False | Read-only |
| google_drive | upload_file | True | Uploads file |
| google_slides | create_presentation | True | Creates presentation |

## Files Changed

### New Files

| File | Purpose | ~Size |
|------|---------|-------|
| `backend/agent_executor.py` | ReAct loop, parser, prompt builder, state management | ~300 lines |
| `backend/agent_tools.py` | ToolDefinition, ToolRegistry (plugins-to-tools converter) | ~80 lines |

### Modified Files

| File | Change | Impact |
|------|--------|--------|
| `backend/routers/ask.py` | Route actionnable agents to AgentExecutor instead of get_answer + detect_action_with_gemini. Delete `detect_action_with_gemini()`. Delete `_ACTIONNABLE_REMOVED` block (~300 lines). Add streaming support for actionnable agents via `AgentExecutor.run_stream()`. | Major (simplification) |
| `backend/routers/action_executions.py` | On confirm: execute action, then call `AgentExecutor.resume()` with observation. On cancel: call resume with cancellation observation. Return continuation (next steps or final answer). | Moderate |
| `backend/database.py` | Add `loop_state = Column(Text, nullable=True)` to ActionExecution model. | Minimal |
| `backend/plugins/base.py` | Add `side_effect: bool = True` field to ActionDefinition dataclass. | Minimal |
| `backend/plugins/gmail/__init__.py` | Annotate each action with `side_effect=True/False`. | Minimal |
| `backend/plugins/google_docs/__init__.py` | Annotate each action with `side_effect=True/False`. | Minimal |
| `backend/plugins/google_sheets/__init__.py` | Annotate each action with `side_effect=True/False`. | Minimal |
| `backend/plugins/google_calendar/__init__.py` | Annotate each action with `side_effect=True/False`. | Minimal |
| `backend/plugins/google_drive/__init__.py` | Annotate each action with `side_effect=True/False`. | Minimal |
| `backend/plugins/google_slides/__init__.py` | Annotate each action with `side_effect=True/False`. | Minimal |
| `frontend/components/ActionProposal.js` | Display agent's thought alongside the action summary. After confirm/cancel, display the agent's continuation response. Show human-readable summary instead of raw code. | Moderate |
| `frontend/pages/chat/[agentId].js` | Handle new SSE event types: thought, action, observation, action_proposal. Render reasoning steps in chat UI. | Moderate |

### Deleted Code

| Location | What | Lines |
|----------|------|-------|
| `backend/routers/ask.py` | `detect_action_with_gemini()` function | ~35 lines |
| `backend/routers/ask.py` | Stage 2 action detection block in POST /ask | ~50 lines |
| `backend/routers/ask.py` | `_ACTIONNABLE_REMOVED` legacy block | ~300 lines |

### Unchanged Files

| File | Reason |
|------|--------|
| `backend/rag_engine.py` | Stays as pure RAG retrieval service. AgentExecutor calls it for context. |
| `backend/plugins/*/actions.py` | Plugin execution logic unchanged. |
| `backend/google_credentials.py` | OAuth token management unchanged. |
| `backend/routers/google_auth.py` | OAuth flow unchanged. |
| `frontend/components/PluginSelector.js` | Plugin selection UI unchanged. |
| All non-actionnable agent paths | Completely untouched. |

## Robustness

### Scope Validation

In `action_executions.py`, before executing any action:

```python
plugin = plugin_manager.get_plugin(ae.plugin_name)
required_scopes = plugin.required_scopes
granted_scopes = json.loads(token.granted_scopes)
if not check_scopes_covered(granted_scopes, required_scopes):
    raise HTTPException(400, "Required Google scopes not granted. Please reconnect your Google account.")
```

### Tool Execution Timeout

Every tool execution is wrapped with a timeout:

```python
import asyncio
try:
    result = await asyncio.wait_for(
        asyncio.to_thread(plugin.execute, action_name, args, credentials),
        timeout=TOOL_TIMEOUT_SECONDS
    )
except asyncio.TimeoutError:
    result = ActionResult(success=False, ..., error_message="Tool execution timed out")
```

### Max Iterations Guard

The loop hard-stops after MAX_ITERATIONS (6). On reaching the limit:

1. Append a forced user message: "You have reached the maximum number of steps. Provide your Final Answer now based on what you have so far."
2. Call LLM one final time.
3. If still no Final Answer, treat raw text as the answer (FallbackStep).

### Parser Fallback

If the LLM ignores the ReAct format entirely (possible with weaker models), the parser treats the full text output as a Final Answer. The user always gets a response. The agent just won't be able to use tools in that case, which degrades gracefully to the current conversationnel behavior.

### Loop State Integrity

AgentLoopState is serialized to JSON and stored atomically in the DB. If the server crashes between suspend and resume, the state persists. On resume, the state is loaded, validated (check iteration count, verify agent_id matches), and the loop continues.

## Frontend UX

### Reasoning Steps Display

When the agent is thinking and acting, the chat shows intermediate steps:

```
[Agent thinking icon] "Je dois d'abord chercher les mails de Pierre..."

[Search icon] Recherche emails: "from:pierre"
  > 3 emails trouves. Le plus recent: "Reunion demain ?"

[Agent thinking icon] "J'ai trouve le mail. Je vais repondre..."

[Action card - needs confirmation]
  Repondre au mail "Reunion demain ?"
  Contenu: "D'accord pour demain !"
  [Confirmer] [Annuler]

--- after user confirms ---

[Success badge] Reponse envoyee

[Agent response]
  J'ai trouve le dernier mail de Pierre "Reunion demain ?"
  et j'y ai repondu "D'accord pour demain !".
```

### Action Proposal Display

The ActionProposal component shows:
- The agent's reasoning (thought) that led to the action
- A human-readable summary: "Envoyer un email a alice@example.com" instead of `send_email(to='alice@...', subject='...', body='...')`
- Expandable details showing the full parameters
- Confirm/Cancel buttons
- After execution: success/failure status with the agent's continuation

## Migration

### Database Migration

Single column addition to ActionExecution:

```sql
ALTER TABLE action_executions ADD COLUMN loop_state TEXT;
```

### Backward Compatibility

- Existing ActionExecution records (without loop_state) continue to work. The confirm/cancel endpoints check if loop_state is present; if not, they execute the action without resuming a loop (legacy behavior).
- The `/ask` endpoint routes based on `agent.type`. Non-actionnable agents are completely unaffected.
- Existing actionnable agents will immediately benefit from the new behavior since their `enabled_plugins` field is already populated.

## Testing Strategy

1. Unit tests for `parse_llm_output()` with various LLM response formats (clean, messy, no format, markdown-wrapped JSON)
2. Unit tests for `ToolRegistry.from_plugins()` with mock plugins
3. Integration test: full ReAct loop with mocked LLM responses (scripted multi-step scenario)
4. Integration test: suspend on write tool, resume after confirm, resume after cancel
5. Integration test: max iterations guard triggers correctly
6. Integration test: streaming events emitted in correct order
7. E2E test: "envoie un mail" flow with real Gmail plugin (staging environment)
