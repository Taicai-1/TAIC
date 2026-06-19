# Actionnable Agent ReAct Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken two-stage actionnable agent pipeline with a ReAct agent loop that reasons, acts (with user confirmation for side-effect tools), and responds coherently.

**Architecture:** A lightweight ReAct loop (`agent_executor.py`) orchestrates LLM calls, parses Thought/Action/Final Answer, executes read-only tools automatically, suspends on write tools for user confirmation, and resumes after. No framework dependency — prompt engineering over any text LLM.

**Tech Stack:** Python 3.11, FastAPI, existing plugin system, existing `openai_client.get_chat_response`, existing `rag_engine` for document retrieval, existing SSE streaming infrastructure.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/agent_tools.py` | CREATE | ToolDefinition dataclass, `build_tools_from_plugins()` converter |
| `backend/agent_executor.py` | CREATE | ReAct loop, LLM output parser, prompt builder, state serialization, `run()`/`run_stream()`/`resume()` |
| `backend/tests/test_agent_tools.py` | CREATE | Unit tests for tool building |
| `backend/tests/test_agent_executor.py` | CREATE | Unit tests for parser + integration tests for the ReAct loop |
| `backend/plugins/base.py` | MODIFY | Add `side_effect: bool = True` to ActionDefinition |
| `backend/plugins/gmail/__init__.py` | MODIFY | Annotate `side_effect` per action |
| `backend/plugins/google_docs/__init__.py` | MODIFY | Annotate `side_effect` per action |
| `backend/plugins/google_sheets/__init__.py` | MODIFY | Annotate `side_effect` per action |
| `backend/plugins/google_calendar/__init__.py` | MODIFY | Annotate `side_effect` per action |
| `backend/plugins/google_drive/__init__.py` | MODIFY | Annotate `side_effect` per action |
| `backend/plugins/google_slides/__init__.py` | MODIFY | Annotate `side_effect` per action |
| `backend/database.py` | MODIFY | Add `loop_state` column to ActionExecution |
| `backend/routers/ask.py` | MODIFY | Route actionnable agents to AgentExecutor, delete old Stage 2 + legacy code |
| `backend/routers/action_executions.py` | MODIFY | Add scope validation, resume loop after confirm/cancel |
| `frontend/lib/streamingFetch.js` | MODIFY | Handle new SSE event types |
| `frontend/components/ActionProposal.js` | MODIFY | Show thought, human-readable summary, agent continuation |
| `frontend/pages/chat/[agentId].js` | MODIFY | Render reasoning steps (thought, action, observation) |

---

## Task 1: Add `side_effect` field to ActionDefinition

**Files:**
- Modify: `backend/plugins/base.py:9-17`

- [ ] **Step 1: Add `side_effect` field to the dataclass**

In `backend/plugins/base.py`, replace the `ActionDefinition` dataclass:

```python
@dataclass
class ActionDefinition:
    """Describes a single action a plugin can perform."""

    name: str
    description: str
    parameters_schema: dict
    display_name: str
    icon: str
    side_effect: bool = True  # True = write (needs confirmation), False = read-only
```

- [ ] **Step 2: Verify existing plugins still import cleanly**

Run: `cd backend && python -c "from plugins.gmail import GmailPlugin; p = GmailPlugin(); print(p.get_actions())"`

Expected: prints the 3 gmail actions without error (they'll have `side_effect=True` by default).

- [ ] **Step 3: Commit**

```bash
git add backend/plugins/base.py
git commit -m "feat(plugins): add side_effect field to ActionDefinition"
```

---

## Task 2: Annotate all plugins with `side_effect`

**Files:**
- Modify: `backend/plugins/gmail/__init__.py`
- Modify: `backend/plugins/google_docs/__init__.py`
- Modify: `backend/plugins/google_sheets/__init__.py`
- Modify: `backend/plugins/google_calendar/__init__.py`
- Modify: `backend/plugins/google_drive/__init__.py`
- Modify: `backend/plugins/google_slides/__init__.py`

- [ ] **Step 1: Gmail plugin — mark `search_emails` as read-only**

In `backend/plugins/gmail/__init__.py`, update `get_actions()`:

```python
    def get_actions(self):
        return {
            "send_email": ActionDefinition(name="send_email", description="Send an email from the user's Gmail account",
                                          parameters_schema=schemas.SEND_EMAIL, display_name="Send Email", icon="send", side_effect=True),
            "reply_email": ActionDefinition(name="reply_email", description="Reply to an existing email thread",
                                           parameters_schema=schemas.REPLY_EMAIL, display_name="Reply to Email", icon="reply", side_effect=True),
            "search_emails": ActionDefinition(name="search_emails", description="Search for emails in Gmail",
                                             parameters_schema=schemas.SEARCH_EMAILS, display_name="Search Emails", icon="search", side_effect=False),
        }
```

- [ ] **Step 2: Google Docs — all actions are write**

In `backend/plugins/google_docs/__init__.py`, add `side_effect=True` explicitly to all 3 actions (`create_doc`, `update_doc`, `share_doc`):

```python
    def get_actions(self):
        return {
            "create_doc": ActionDefinition(
                name="create_doc",
                description="Create a new Google Docs document with an optional title and content",
                parameters_schema=schemas.CREATE_DOC,
                display_name="Create Document",
                icon="file-plus",
                side_effect=True,
            ),
            "update_doc": ActionDefinition(
                name="update_doc",
                description="Append content to an existing Google Docs document",
                parameters_schema=schemas.UPDATE_DOC,
                display_name="Update Document",
                icon="file-edit",
                side_effect=True,
            ),
            "share_doc": ActionDefinition(
                name="share_doc",
                description="Share a Google Docs document with another user by email",
                parameters_schema=schemas.SHARE_DOC,
                display_name="Share Document",
                icon="share",
                side_effect=True,
            ),
        }
```

- [ ] **Step 3: Google Sheets — `read_sheet` is read-only**

In `backend/plugins/google_sheets/__init__.py`:

```python
    def get_actions(self):
        return {
            "create_sheet": ActionDefinition(name="create_sheet", description="Create a new spreadsheet with optional sheets, headers and data",
                                            parameters_schema=schemas.CREATE_SHEET, display_name="Create Spreadsheet", icon="table", side_effect=True),
            "update_sheet": ActionDefinition(name="update_sheet", description="Update cell values in an existing spreadsheet",
                                           parameters_schema=schemas.UPDATE_SHEET, display_name="Update Spreadsheet", icon="edit", side_effect=True),
            "read_sheet": ActionDefinition(name="read_sheet", description="Read cell values from a spreadsheet",
                                          parameters_schema=schemas.READ_SHEET, display_name="Read Spreadsheet", icon="eye", side_effect=False),
        }
```

- [ ] **Step 4: Google Calendar — `list_events` is read-only**

In `backend/plugins/google_calendar/__init__.py`:

```python
    def get_actions(self):
        return {
            "create_event": ActionDefinition(name="create_event", description="Create a new calendar event with title, time and optional attendees",
                                            parameters_schema=schemas.CREATE_EVENT, display_name="Create Event", icon="calendar-plus", side_effect=True),
            "list_events": ActionDefinition(name="list_events", description="List calendar events in a time range",
                                           parameters_schema=schemas.LIST_EVENTS, display_name="List Events", icon="calendar", side_effect=False),
            "update_event": ActionDefinition(name="update_event", description="Update an existing calendar event",
                                           parameters_schema=schemas.UPDATE_EVENT, display_name="Update Event", icon="calendar-edit", side_effect=True),
        }
```

- [ ] **Step 5: Google Drive — `search_files` is read-only**

In `backend/plugins/google_drive/__init__.py`:

```python
    def get_actions(self):
        return {
            "create_folder": ActionDefinition(name="create_folder", description="Create a new folder in Google Drive",
                                             parameters_schema=schemas.CREATE_FOLDER, display_name="Create Folder", icon="folder-plus", side_effect=True),
            "move_file": ActionDefinition(name="move_file", description="Move a file to a different folder",
                                        parameters_schema=schemas.MOVE_FILE, display_name="Move File", icon="folder-input", side_effect=True),
            "share_file": ActionDefinition(name="share_file", description="Share a file or folder with another user by email",
                                          parameters_schema=schemas.SHARE_FILE, display_name="Share File", icon="share", side_effect=True),
            "search_files": ActionDefinition(name="search_files", description="Search for files and folders in Google Drive",
                                           parameters_schema=schemas.SEARCH_FILES, display_name="Search Files", icon="search", side_effect=False),
        }
```

- [ ] **Step 6: Google Slides — all write**

In `backend/plugins/google_slides/__init__.py`:

```python
    def get_actions(self):
        return {
            "create_presentation": ActionDefinition(name="create_presentation", description="Create a new Google Slides presentation with optional slides",
                                                   parameters_schema=schemas.CREATE_PRESENTATION, display_name="Create Presentation", icon="plus-square", side_effect=True),
            "add_slide": ActionDefinition(name="add_slide", description="Add a new slide to an existing presentation",
                                        parameters_schema=schemas.ADD_SLIDE, display_name="Add Slide", icon="layers", side_effect=True),
        }
```

- [ ] **Step 7: Verify all plugins load correctly**

Run: `cd backend && python -c "from plugins import discover_plugins, plugin_manager; discover_plugins(); [print(f'{p.name}: {[(a, d.side_effect) for a,d in p.get_actions().items()]}') for p in plugin_manager.list_plugins()]"`

Expected: all plugins list their actions with correct `side_effect` values.

- [ ] **Step 8: Commit**

```bash
git add backend/plugins/gmail/__init__.py backend/plugins/google_docs/__init__.py backend/plugins/google_sheets/__init__.py backend/plugins/google_calendar/__init__.py backend/plugins/google_drive/__init__.py backend/plugins/google_slides/__init__.py
git commit -m "feat(plugins): annotate all actions with side_effect read/write"
```

---

## Task 3: Create `agent_tools.py` — Plugin-to-Tool converter

**Files:**
- Create: `backend/agent_tools.py`
- Create: `backend/tests/test_agent_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_tools.py`:

```python
"""Tests for agent_tools module."""
from unittest.mock import MagicMock
from plugins.base import ActionDefinition


class TestBuildToolsFromPlugins:
    def test_converts_plugin_actions_to_tool_definitions(self):
        from agent_tools import ToolDefinition, build_tools_from_plugins

        mock_manager = MagicMock()
        mock_plugin = MagicMock()
        mock_plugin.name = "gmail"
        mock_plugin.get_actions.return_value = {
            "send_email": ActionDefinition(
                name="send_email", description="Send an email",
                parameters_schema={"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
                display_name="Send Email", icon="send", side_effect=True,
            ),
            "search_emails": ActionDefinition(
                name="search_emails", description="Search emails",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                display_name="Search Emails", icon="search", side_effect=False,
            ),
        }
        mock_manager.get_plugin.return_value = mock_plugin
        tools = build_tools_from_plugins(["gmail"], mock_manager)

        assert len(tools) == 2
        by_name = {t.name: t for t in tools}
        assert by_name["send_email"].side_effect is True
        assert by_name["send_email"].plugin_name == "gmail"
        assert by_name["search_emails"].side_effect is False

    def test_skips_unknown_plugin(self):
        from agent_tools import build_tools_from_plugins

        mock_manager = MagicMock()
        mock_manager.get_plugin.return_value = None
        tools = build_tools_from_plugins(["nonexistent"], mock_manager)
        assert tools == []

    def test_tool_definition_prompt_format(self):
        from agent_tools import ToolDefinition

        tool = ToolDefinition(
            name="send_email", description="Send an email",
            parameters_schema={"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
            plugin_name="gmail", side_effect=True,
        )
        text = tool.to_prompt_str()
        assert "send_email" in text
        assert "Send an email" in text
        assert "to" in text
        assert "confirmation" in text.lower()

    def test_read_tool_prompt_says_lecture(self):
        from agent_tools import ToolDefinition

        tool = ToolDefinition(
            name="search_emails", description="Search emails",
            parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            plugin_name="gmail", side_effect=False,
        )
        text = tool.to_prompt_str()
        assert "lecture seule" in text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_agent_tools.py -v`

Expected: ModuleNotFoundError — `agent_tools` doesn't exist yet.

- [ ] **Step 3: Implement `agent_tools.py`**

Create `backend/agent_tools.py`:

```python
"""Convert plugin actions into tool definitions for the ReAct agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plugins import PluginManager


@dataclass
class ToolDefinition:
    """A tool available to the ReAct agent."""

    name: str
    description: str
    parameters_schema: dict
    plugin_name: str
    side_effect: bool  # True = write (needs confirmation), False = read-only

    def to_prompt_str(self) -> str:
        """Format this tool for inclusion in the ReAct system prompt."""
        params_desc = []
        props = self.parameters_schema.get("properties", {})
        required = set(self.parameters_schema.get("required", []))
        for pname, pinfo in props.items():
            req_mark = " (obligatoire)" if pname in required else " (optionnel)"
            desc = pinfo.get("description", "")
            params_desc.append(f"    - {pname}: {desc}{req_mark}")
        params_text = "\n".join(params_desc) if params_desc else "    (aucun parametre)"
        side_label = "action (necessite confirmation)" if self.side_effect else "lecture seule"
        return (
            f"- {self.name}: {self.description}\n"
            f"  Type: {side_label}\n"
            f"  Parametres:\n{params_text}"
        )


def build_tools_from_plugins(
    plugin_names: list[str], manager: "PluginManager"
) -> list[ToolDefinition]:
    """Build ToolDefinition list from enabled plugin names."""
    tools: list[ToolDefinition] = []
    for pname in plugin_names:
        plugin = manager.get_plugin(pname)
        if plugin is None:
            continue
        for action_name, action_def in plugin.get_actions().items():
            tools.append(
                ToolDefinition(
                    name=action_def.name,
                    description=action_def.description,
                    parameters_schema=action_def.parameters_schema,
                    plugin_name=pname,
                    side_effect=action_def.side_effect,
                )
            )
    return tools
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_agent_tools.py -v`

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/agent_tools.py backend/tests/test_agent_tools.py
git commit -m "feat: add agent_tools module — plugin-to-tool converter"
```

---

## Task 4: Create `agent_executor.py` — ReAct loop core

**Files:**
- Create: `backend/agent_executor.py`
- Create: `backend/tests/test_agent_executor.py`

This is the largest task. Split into sub-steps: parser first, then prompt builder, then the loop.

### Part A: LLM Output Parser

- [ ] **Step 1: Write parser tests**

Create `backend/tests/test_agent_executor.py`:

```python
"""Tests for agent_executor module."""
import json
import pytest


class TestParseLlmOutput:
    """Test the ReAct output parser."""

    def test_parses_final_answer(self):
        from agent_executor import parse_llm_output, FinishStep
        text = "Thought: The email has been sent.\nFinal Answer: J'ai envoyé l'email à alice@example.com."
        step = parse_llm_output(text, ["send_email"])
        assert isinstance(step, FinishStep)
        assert "envoyé" in step.answer

    def test_parses_action_step(self):
        from agent_executor import parse_llm_output, ActionStep
        text = (
            'Thought: I need to search for emails from Pierre.\n'
            'Action: search_emails\n'
            'Action Input: {"query": "from:pierre"}'
        )
        step = parse_llm_output(text, ["search_emails", "send_email"])
        assert isinstance(step, ActionStep)
        assert step.tool_name == "search_emails"
        assert step.tool_args == {"query": "from:pierre"}
        assert "Pierre" in step.thought

    def test_parses_action_with_markdown_fenced_json(self):
        from agent_executor import parse_llm_output, ActionStep
        text = (
            'Thought: Sending the email.\n'
            'Action: send_email\n'
            'Action Input: ```json\n{"to": "alice@test.com", "subject": "Hi", "body": "Hello"}\n```'
        )
        step = parse_llm_output(text, ["send_email"])
        assert isinstance(step, ActionStep)
        assert step.tool_args["to"] == "alice@test.com"

    def test_fallback_on_unformatted_text(self):
        from agent_executor import parse_llm_output, FallbackStep
        text = "Bonjour, je suis votre assistant."
        step = parse_llm_output(text, ["send_email"])
        assert isinstance(step, FallbackStep)
        assert step.text == text

    def test_rejects_unknown_tool_name(self):
        from agent_executor import parse_llm_output, FallbackStep
        text = (
            'Thought: Doing something.\n'
            'Action: nonexistent_tool\n'
            'Action Input: {"foo": "bar"}'
        )
        step = parse_llm_output(text, ["send_email"])
        assert isinstance(step, FallbackStep)

    def test_handles_invalid_json_gracefully(self):
        from agent_executor import parse_llm_output, FallbackStep
        text = (
            'Thought: Sending email.\n'
            'Action: send_email\n'
            'Action Input: {to: alice, subject: test}'
        )
        step = parse_llm_output(text, ["send_email"])
        # Should fallback because JSON is invalid
        assert isinstance(step, FallbackStep)

    def test_final_answer_without_thought(self):
        from agent_executor import parse_llm_output, FinishStep
        text = "Final Answer: Voici la réponse."
        step = parse_llm_output(text, [])
        assert isinstance(step, FinishStep)
        assert step.answer == "Voici la réponse."

    def test_multiline_final_answer(self):
        from agent_executor import parse_llm_output, FinishStep
        text = "Thought: Done.\nFinal Answer: Ligne 1\nLigne 2\nLigne 3"
        step = parse_llm_output(text, [])
        assert isinstance(step, FinishStep)
        assert "Ligne 1" in step.answer
        assert "Ligne 3" in step.answer
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_agent_executor.py::TestParseLlmOutput -v`

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the parser and data types**

Create `backend/agent_executor.py` (first part — types + parser):

```python
"""ReAct agent executor for actionnable agents.

Implements a lightweight Reasoning + Acting loop that:
- Builds a system prompt with agent personality, tools, and RAG context
- Iteratively calls the LLM and parses Thought/Action/Final Answer
- Auto-executes read-only tools, suspends on write tools for user confirmation
- Resumes after confirmation with the action result as Observation
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step types returned by the parser
# ---------------------------------------------------------------------------

@dataclass
class ActionStep:
    """LLM wants to call a tool."""
    thought: str
    tool_name: str
    tool_args: dict

@dataclass
class FinishStep:
    """LLM has a final answer."""
    answer: str

@dataclass
class FallbackStep:
    """LLM didn't follow ReAct format — treat text as final answer."""
    text: str


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_ACTION_RE = re.compile(r"Action\s*:\s*(.+)", re.IGNORECASE)
_ACTION_INPUT_RE = re.compile(r"Action\s+Input\s*:\s*(.*)", re.IGNORECASE | re.DOTALL)
_FINAL_ANSWER_RE = re.compile(r"Final\s+Answer\s*:\s*(.*)", re.IGNORECASE | re.DOTALL)
_THOUGHT_RE = re.compile(r"Thought\s*:\s*(.*?)(?=\n(?:Action|Final Answer)\s*:|\Z)", re.IGNORECASE | re.DOTALL)


def _clean_json(text: str) -> str:
    """Strip markdown fences and whitespace from a JSON string."""
    text = text.strip()
    if text.startswith("```"):
        # Remove ```json ... ``` wrapping
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_llm_output(text: str, available_tools: list[str]) -> ActionStep | FinishStep | FallbackStep:
    """Parse LLM text output into a structured step.

    Rules:
    1. If "Final Answer:" is found, return FinishStep with everything after it.
    2. If "Action:" and "Action Input:" are found, extract tool name + JSON args.
       Validate tool name exists in available_tools.
    3. Otherwise, treat as FallbackStep (graceful degradation).
    """
    text = text.strip()

    # Check for Final Answer first
    fa_match = _FINAL_ANSWER_RE.search(text)
    if fa_match:
        answer = fa_match.group(1).strip()
        return FinishStep(answer=answer)

    # Check for Action
    action_match = _ACTION_RE.search(text)
    ai_match = _ACTION_INPUT_RE.search(text)

    if action_match and ai_match:
        tool_name = action_match.group(1).strip()
        raw_input = ai_match.group(1).strip()

        # Validate tool name
        if tool_name not in available_tools:
            logger.warning(f"ReAct parser: unknown tool '{tool_name}', available: {available_tools}")
            return FallbackStep(text=text)

        # Parse JSON
        cleaned = _clean_json(raw_input)
        try:
            tool_args = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(f"ReAct parser: invalid JSON for tool '{tool_name}': {cleaned[:200]}")
            return FallbackStep(text=text)

        # Extract thought
        thought_match = _THOUGHT_RE.search(text)
        thought = thought_match.group(1).strip() if thought_match else ""

        return ActionStep(thought=thought, tool_name=tool_name, tool_args=tool_args)

    # Nothing matched — fallback
    return FallbackStep(text=text)
```

- [ ] **Step 4: Run parser tests**

Run: `cd backend && python -m pytest tests/test_agent_executor.py::TestParseLlmOutput -v`

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/agent_executor.py backend/tests/test_agent_executor.py
git commit -m "feat(agent): add ReAct LLM output parser with step types"
```

### Part B: Prompt Builder + Loop State

- [ ] **Step 6: Write prompt builder tests**

Append to `backend/tests/test_agent_executor.py`:

```python
class TestBuildReactPrompt:
    def test_includes_agent_personality(self):
        from agent_executor import build_react_prompt
        from agent_tools import ToolDefinition
        prompt = build_react_prompt(
            agent_name="TestBot",
            agent_contexte="Tu es un assistant RH.",
            agent_biographie="Expert en recrutement.",
            tools=[],
            rag_context="",
        )
        assert "TestBot" in prompt
        assert "assistant RH" in prompt
        assert "recrutement" in prompt

    def test_includes_tool_descriptions(self):
        from agent_executor import build_react_prompt
        from agent_tools import ToolDefinition
        tools = [
            ToolDefinition(name="send_email", description="Send an email",
                          parameters_schema={"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
                          plugin_name="gmail", side_effect=True),
        ]
        prompt = build_react_prompt("Bot", "", "", tools, "")
        assert "send_email" in prompt
        assert "Send an email" in prompt
        assert "confirmation" in prompt.lower()

    def test_includes_rag_context_when_provided(self):
        from agent_executor import build_react_prompt
        prompt = build_react_prompt("Bot", "", "", [], "Document X says: blah blah")
        assert "Document X says" in prompt

    def test_omits_rag_context_when_empty(self):
        from agent_executor import build_react_prompt
        prompt = build_react_prompt("Bot", "", "", [], "")
        assert "Contexte documentaire" not in prompt

    def test_includes_react_format_instructions(self):
        from agent_executor import build_react_prompt
        prompt = build_react_prompt("Bot", "", "", [], "")
        assert "Thought:" in prompt
        assert "Action:" in prompt
        assert "Action Input:" in prompt
        assert "Final Answer:" in prompt


class TestAgentLoopState:
    def test_serialization_roundtrip(self):
        from agent_executor import AgentLoopState
        state = AgentLoopState(
            messages=[{"role": "system", "content": "test"}],
            iteration=2,
            steps=[{"type": "thought", "content": "thinking"}],
            agent_id=5,
            user_id=42,
            question="send a mail",
            model_id="gemini:gemini-2.0-flash",
            sources=[],
        )
        serialized = state.to_json()
        restored = AgentLoopState.from_json(serialized)
        assert restored.iteration == 2
        assert restored.agent_id == 5
        assert restored.messages == state.messages
        assert restored.question == "send a mail"
```

- [ ] **Step 7: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_agent_executor.py::TestBuildReactPrompt tests/test_agent_executor.py::TestAgentLoopState -v`

Expected: ImportError for `build_react_prompt` and `AgentLoopState`.

- [ ] **Step 8: Implement prompt builder + AgentLoopState**

Append to `backend/agent_executor.py`:

```python
# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_REACT_SYSTEM_TEMPLATE = """Tu es {agent_name}, un assistant IA actionnable.
{agent_contexte}
{agent_biographie}

Tu as acces aux outils suivants :

{tools_block}

REGLES :
1. Utilise EXACTEMENT le format ci-dessous pour raisonner et agir.
2. Tu peux enchainer plusieurs actions avant de donner ta reponse finale.
3. Ne fabrique JAMAIS le resultat d'une action. Attends toujours l'Observation.
4. Si tu n'as pas besoin d'outil, reponds directement avec "Final Answer:".
5. Reponds toujours dans la langue de l'utilisateur.

FORMAT OBLIGATOIRE :

Thought: [ton raisonnement sur ce qu'il faut faire]
Action: [nom exact de l'outil]
Action Input: [objet JSON valide avec les parametres]

... tu recevras ensuite une Observation avec le resultat ...

Thought: [raisonnement sur le resultat]
Final Answer: [reponse finale a l'utilisateur]
{rag_block}"""


def build_react_prompt(
    agent_name: str,
    agent_contexte: str,
    agent_biographie: str,
    tools: list,
    rag_context: str,
) -> str:
    """Build the ReAct system prompt."""
    from agent_tools import ToolDefinition

    if tools:
        tools_block = "\n".join(t.to_prompt_str() for t in tools)
    else:
        tools_block = "(aucun outil disponible)"

    rag_block = ""
    if rag_context:
        rag_block = f"\n\n--- Contexte documentaire ---\n{rag_context}"

    return _REACT_SYSTEM_TEMPLATE.format(
        agent_name=agent_name,
        agent_contexte=agent_contexte.strip() if agent_contexte else "",
        agent_biographie=agent_biographie.strip() if agent_biographie else "",
        tools_block=tools_block,
        rag_block=rag_block,
    )


# ---------------------------------------------------------------------------
# Loop state (serializable for suspend/resume)
# ---------------------------------------------------------------------------

@dataclass
class AgentLoopState:
    """Serializable state of a suspended ReAct loop."""
    messages: list[dict]
    iteration: int
    steps: list[dict]
    agent_id: int
    user_id: int
    question: str
    model_id: str
    sources: list

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "AgentLoopState":
        data = json.loads(raw)
        return cls(**data)
```

- [ ] **Step 9: Run tests**

Run: `cd backend && python -m pytest tests/test_agent_executor.py -v`

Expected: all tests PASS (parser + prompt builder + state).

- [ ] **Step 10: Commit**

```bash
git add backend/agent_executor.py backend/tests/test_agent_executor.py
git commit -m "feat(agent): add ReAct prompt builder and serializable loop state"
```

### Part C: The ReAct Loop

- [ ] **Step 11: Write loop integration tests**

Append to `backend/tests/test_agent_executor.py`:

```python
from unittest.mock import patch, MagicMock, call


class TestAgentExecutorRun:
    """Integration tests for the ReAct loop with mocked LLM."""

    def _make_agent(self, name="TestBot", contexte="", biographie="", enabled_plugins='["gmail"]', agent_type="actionnable"):
        agent = MagicMock()
        agent.id = 1
        agent.name = name
        agent.contexte = contexte
        agent.biographie = biographie
        agent.type = agent_type
        agent.enabled_plugins = enabled_plugins
        agent.company_id = 10
        agent.finetuned_model_id = None
        agent.llm_provider = "gemini"
        return agent

    @patch("agent_executor.get_chat_response")
    @patch("agent_executor.get_rag_context")
    def test_simple_final_answer_no_tools(self, mock_rag, mock_llm):
        from agent_executor import AgentExecutor
        mock_rag.return_value = ("", [])
        mock_llm.return_value = "Final Answer: Bonjour, comment puis-je vous aider ?"

        executor = AgentExecutor()
        result = executor.run(
            question="Bonjour",
            agent=self._make_agent(),
            history=[],
            db=MagicMock(),
            user_id=42,
            credentials=MagicMock(),
        )
        assert result["answer"] == "Bonjour, comment puis-je vous aider ?"
        assert result["action_proposal"] is None
        assert result["loop_state"] is None

    @patch("agent_executor.get_chat_response")
    @patch("agent_executor.get_rag_context")
    @patch("agent_executor._execute_read_tool")
    def test_read_tool_auto_executed(self, mock_exec, mock_rag, mock_llm):
        from agent_executor import AgentExecutor
        from plugins.base import ActionResult
        mock_rag.return_value = ("", [])
        mock_llm.side_effect = [
            'Thought: I need to search emails.\nAction: search_emails\nAction Input: {"query": "from:pierre"}',
            'Thought: Found emails.\nFinal Answer: J\'ai trouve 2 emails de Pierre.',
        ]
        mock_exec.return_value = ActionResult(
            success=True, data={"emails": [{"subject": "Test"}], "total": 1},
            display_message="Found 1 email", resource_url=None, error_message=None,
        )

        executor = AgentExecutor()
        result = executor.run(
            question="Cherche les mails de Pierre",
            agent=self._make_agent(),
            history=[],
            db=MagicMock(),
            user_id=42,
            credentials=MagicMock(),
        )
        assert "Pierre" in result["answer"]
        assert result["action_proposal"] is None
        mock_exec.assert_called_once()

    @patch("agent_executor.get_chat_response")
    @patch("agent_executor.get_rag_context")
    def test_write_tool_suspends_loop(self, mock_rag, mock_llm):
        from agent_executor import AgentExecutor
        mock_rag.return_value = ("", [])
        mock_llm.return_value = (
            'Thought: I need to send an email.\n'
            'Action: send_email\n'
            'Action Input: {"to": "alice@test.com", "subject": "Hi", "body": "Hello"}'
        )

        mock_db = MagicMock()
        executor = AgentExecutor()
        result = executor.run(
            question="Envoie un mail a alice",
            agent=self._make_agent(),
            history=[],
            db=mock_db,
            user_id=42,
            credentials=MagicMock(),
        )
        # Loop should suspend: no final answer yet, but action_proposal present
        assert result["answer"] is None
        assert result["action_proposal"] is not None
        assert result["action_proposal"]["action"] == "send_email"
        assert result["loop_state"] is not None

    @patch("agent_executor.get_chat_response")
    def test_resume_after_confirm(self, mock_llm):
        from agent_executor import AgentExecutor, AgentLoopState
        mock_llm.return_value = "Thought: Email sent.\nFinal Answer: J'ai envoye l'email a alice."

        state = AgentLoopState(
            messages=[{"role": "system", "content": "prompt"}, {"role": "user", "content": "Envoie un mail"}],
            iteration=1, steps=[], agent_id=1, user_id=42,
            question="Envoie un mail a alice", model_id="gemini:gemini-2.0-flash", sources=[],
        )

        executor = AgentExecutor()
        result = executor.resume(
            loop_state=state.to_json(),
            observation="Email envoye avec succes (message_id: abc123)",
            db=MagicMock(),
            credentials=MagicMock(),
        )
        assert result["answer"] is not None
        assert "alice" in result["answer"]

    @patch("agent_executor.get_chat_response")
    @patch("agent_executor.get_rag_context")
    def test_max_iterations_forces_answer(self, mock_rag, mock_llm):
        from agent_executor import AgentExecutor
        mock_rag.return_value = ("", [])
        # LLM always returns an action, never a final answer
        mock_llm.side_effect = [
            'Thought: Searching.\nAction: search_emails\nAction Input: {"query": "test"}',
        ] * 7 + [
            "I'm stuck but here is what I know."  # Forced fallback
        ]

        executor = AgentExecutor()
        # Mock read tool execution
        with patch("agent_executor._execute_read_tool") as mock_exec:
            from plugins.base import ActionResult
            mock_exec.return_value = ActionResult(
                success=True, data={"emails": []}, display_message="", resource_url=None, error_message=None,
            )
            result = executor.run(
                question="infinite loop test",
                agent=self._make_agent(),
                history=[], db=MagicMock(), user_id=42, credentials=MagicMock(),
            )
        # Should have stopped and returned something
        assert result["answer"] is not None
```

- [ ] **Step 12: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_agent_executor.py::TestAgentExecutorRun -v`

Expected: ImportError for `AgentExecutor`.

- [ ] **Step 13: Implement the ReAct loop**

Append to `backend/agent_executor.py`:

```python
from openai_client import get_chat_response
from helpers.agent_helpers import resolve_model_id


# ---------------------------------------------------------------------------
# RAG context retrieval (delegates to rag_engine)
# ---------------------------------------------------------------------------

def get_rag_context(agent, user_id: int, db, question: str, selected_doc_ids=None, use_rag=True, use_graph=True, company_id=None) -> tuple[str, list]:
    """Retrieve RAG document context for the agent.

    Returns (context_text, sources). Delegates to rag_engine internals
    but only retrieves chunks — does NOT call the LLM.
    """
    if not use_rag:
        return "", []

    from rag_engine import search_similar_texts_for_user, get_embedding
    from database import Document

    try:
        # Get documents scoped to this agent
        q = db.query(Document).filter(Document.agent_id == agent.id)
        if company_id:
            q = q.filter(Document.company_id == company_id)
        q = q.filter(Document.document_type != "traceability")
        if selected_doc_ids:
            q = q.filter(Document.id.in_(selected_doc_ids))
        user_docs = q.all()

        if not user_docs:
            return "", []

        query_embedding = get_embedding(question)
        results = search_similar_texts_for_user(
            query_embedding, user_id, db, top_k=8,
            selected_doc_ids=selected_doc_ids, agent_id=agent.id, company_id=company_id,
        )

        sources = [
            {"text": r["text"], "document_name": r["document_name"],
             "score": round(r["similarity"] * 100, 1), "document_id": r["document_id"]}
            for r in results
        ]

        # Build context string
        by_doc: dict[str, list[str]] = {}
        for r in results:
            by_doc.setdefault(r["document_name"], []).append(r["text"])

        parts = []
        for doc_name, texts in by_doc.items():
            section = f"\n--- Extraits du document '{doc_name}' ---\n"
            for i, t in enumerate(texts, 1):
                section += f"Extrait {i}: {t}\n"
            parts.append(section)

        return "".join(parts), sources
    except Exception as e:
        logger.warning(f"RAG context retrieval failed: {e}")
        return "", []


# ---------------------------------------------------------------------------
# Tool execution helpers
# ---------------------------------------------------------------------------

def _execute_read_tool(plugin_name: str, action_name: str, args: dict, credentials) -> "ActionResult":
    """Execute a read-only tool immediately."""
    from plugins import plugin_manager
    from plugins.base import ActionResult

    plugin = plugin_manager.get_plugin(plugin_name)
    if not plugin:
        return ActionResult(success=False, data={}, display_message="", resource_url=None,
                           error_message=f"Plugin '{plugin_name}' not found")
    return plugin.execute(action_name, args, credentials)


def _observation_from_result(result: "ActionResult") -> str:
    """Format an ActionResult as an Observation string for the LLM."""
    if result.success:
        data_str = json.dumps(result.data, ensure_ascii=False, default=str)
        # Truncate very large observations
        if len(data_str) > 3000:
            data_str = data_str[:3000] + "... (tronque)"
        return f"Succes. {result.display_message}\nDonnees: {data_str}"
    else:
        return f"Echec: {result.error_message}"


# ---------------------------------------------------------------------------
# AgentExecutor — the ReAct loop
# ---------------------------------------------------------------------------

class AgentExecutor:
    MAX_ITERATIONS = 6
    TOOL_TIMEOUT_SECONDS = 30

    def run(
        self,
        question: str,
        agent,
        history: list[dict],
        db,
        user_id: int,
        credentials,
        selected_doc_ids: list[int] | None = None,
        use_rag: bool = True,
        use_graph: bool = True,
    ) -> dict:
        """Run the ReAct loop synchronously.

        Returns:
            {
                "answer": str | None,          # Final answer (None if suspended)
                "steps": list[dict],           # Reasoning trace
                "action_proposal": dict | None, # If suspended on write tool
                "loop_state": str | None,       # Serialized state if suspended
                "sources": list,                # RAG sources
            }
        """
        from agent_tools import build_tools_from_plugins
        from plugins import plugin_manager

        # Load tools
        enabled_plugins = []
        if agent.enabled_plugins:
            try:
                enabled_plugins = json.loads(agent.enabled_plugins)
            except Exception:
                enabled_plugins = []
        tools = build_tools_from_plugins(enabled_plugins, plugin_manager)
        tool_names = [t.name for t in tools]
        tool_map = {t.name: t for t in tools}

        # Retrieve RAG context
        rag_context, sources = get_rag_context(
            agent, user_id, db, question,
            selected_doc_ids=selected_doc_ids,
            use_rag=use_rag, use_graph=use_graph,
            company_id=agent.company_id,
        )

        # Build system prompt
        system_prompt = build_react_prompt(
            agent_name=agent.name,
            agent_contexte=getattr(agent, "contexte", "") or "",
            agent_biographie=getattr(agent, "biographie", "") or "",
            tools=tools,
            rag_context=rag_context,
        )

        # Build messages
        model_id = agent.finetuned_model_id or resolve_model_id(agent)
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for msg in history[-10:]:
                role = msg.get("role", "user")
                if role == "agent":
                    role = "assistant"
                elif role == "system":
                    continue
                messages.append({"role": role, "content": msg.get("content", "")})
        messages.append({"role": "user", "content": question})

        # ReAct loop
        steps = []
        return self._loop(messages, steps, tool_names, tool_map, model_id, sources,
                         agent, user_id, question, db, credentials, iteration=0)

    def resume(self, loop_state: str, observation: str, db, credentials) -> dict:
        """Resume a suspended loop after user confirmation/cancellation."""
        state = AgentLoopState.from_json(loop_state)

        # Reload tools
        from agent_tools import build_tools_from_plugins
        from plugins import plugin_manager
        from database import Agent

        agent = db.query(Agent).filter(Agent.id == state.agent_id).first()
        enabled_plugins = []
        if agent and agent.enabled_plugins:
            try:
                enabled_plugins = json.loads(agent.enabled_plugins)
            except Exception:
                enabled_plugins = []
        tools = build_tools_from_plugins(enabled_plugins, plugin_manager)
        tool_names = [t.name for t in tools]
        tool_map = {t.name: t for t in tools}

        # Add the observation to messages
        messages = state.messages
        messages.append({"role": "user", "content": f"Observation: {observation}"})

        return self._loop(messages, state.steps, tool_names, tool_map,
                         state.model_id, state.sources, agent, state.user_id,
                         state.question, db, credentials, iteration=state.iteration)

    def _loop(self, messages, steps, tool_names, tool_map, model_id, sources,
              agent, user_id, question, db, credentials, iteration):
        """Core ReAct loop shared by run() and resume()."""
        from database import ActionExecution
        from helpers.tenant import _get_caller_company_id

        for i in range(iteration, self.MAX_ITERATIONS):
            # Call LLM
            llm_response = get_chat_response(messages, model_id=model_id)
            logger.info(f"[ReAct iter {i}] LLM response: {llm_response[:300]}")

            step = parse_llm_output(llm_response, tool_names)

            if isinstance(step, FinishStep):
                steps.append({"type": "finish", "answer": step.answer})
                return {
                    "answer": step.answer,
                    "steps": steps,
                    "action_proposal": None,
                    "loop_state": None,
                    "sources": sources,
                }

            if isinstance(step, FallbackStep):
                steps.append({"type": "fallback", "text": step.text})
                return {
                    "answer": step.text,
                    "steps": steps,
                    "action_proposal": None,
                    "loop_state": None,
                    "sources": sources,
                }

            if isinstance(step, ActionStep):
                tool_def = tool_map.get(step.tool_name)
                steps.append({
                    "type": "action",
                    "thought": step.thought,
                    "tool": step.tool_name,
                    "args": step.tool_args,
                    "side_effect": tool_def.side_effect if tool_def else True,
                })

                if tool_def and not tool_def.side_effect:
                    # Read-only tool: execute immediately
                    result = _execute_read_tool(tool_def.plugin_name, step.tool_name, step.tool_args, credentials)
                    obs = _observation_from_result(result)
                    steps.append({"type": "observation", "tool": step.tool_name, "result": obs})
                    # Add to messages so LLM sees the observation
                    messages.append({"role": "assistant", "content": llm_response})
                    messages.append({"role": "user", "content": f"Observation: {obs}"})
                    continue

                else:
                    # Write tool: suspend loop, create ActionExecution
                    company_id = getattr(agent, "company_id", None) or _get_caller_company_id(str(user_id), db)

                    # Find plugin name for this action
                    plugin_name = tool_def.plugin_name if tool_def else "unknown"

                    ae = ActionExecution(
                        agent_id=agent.id,
                        user_id=user_id,
                        company_id=company_id,
                        plugin_name=plugin_name,
                        action_name=step.tool_name,
                        action_params=json.dumps(step.tool_args, ensure_ascii=False),
                        status="pending_confirmation",
                    )
                    db.add(ae)

                    # Serialize loop state for resume
                    messages.append({"role": "assistant", "content": llm_response})
                    state = AgentLoopState(
                        messages=messages,
                        iteration=i + 1,
                        steps=steps,
                        agent_id=agent.id,
                        user_id=user_id,
                        question=question,
                        model_id=model_id,
                        sources=sources,
                    )
                    ae.loop_state = state.to_json()
                    db.commit()
                    db.refresh(ae)

                    # Build human-readable display summary
                    display_parts = []
                    for k, v in list(step.tool_args.items())[:3]:
                        display_parts.append(f"{k}: {v}")
                    display_summary = f"{tool_def.display_name if tool_def else step.tool_name} — {', '.join(display_parts)}"

                    return {
                        "answer": None,
                        "steps": steps,
                        "action_proposal": {
                            "execution_id": ae.id,
                            "plugin": plugin_name,
                            "action": step.tool_name,
                            "params": step.tool_args,
                            "display_summary": display_summary,
                            "thought": step.thought,
                        },
                        "loop_state": state.to_json(),
                        "sources": sources,
                    }

        # Max iterations reached — force a final answer
        messages.append({"role": "user", "content": "Tu as atteint le nombre maximum d'etapes. Donne ta reponse finale maintenant avec ce que tu sais."})
        forced = get_chat_response(messages, model_id=model_id)
        forced_step = parse_llm_output(forced, tool_names)
        if isinstance(forced_step, FinishStep):
            answer = forced_step.answer
        else:
            answer = forced if isinstance(forced, str) else str(forced)
        steps.append({"type": "forced_finish", "answer": answer})
        return {
            "answer": answer,
            "steps": steps,
            "action_proposal": None,
            "loop_state": None,
            "sources": sources,
        }
```

- [ ] **Step 14: Run all agent_executor tests**

Run: `cd backend && python -m pytest tests/test_agent_executor.py -v`

Expected: all tests PASS.

- [ ] **Step 15: Commit**

```bash
git add backend/agent_executor.py backend/tests/test_agent_executor.py
git commit -m "feat(agent): implement ReAct loop with run/resume/max-iterations"
```

---

## Task 5: Add `loop_state` column to ActionExecution

**Files:**
- Modify: `backend/database.py:369-390`

- [ ] **Step 1: Add the column**

In `backend/database.py`, in the `ActionExecution` class, after line 386 (`created_at`), add:

```python
    loop_state = Column(Text, nullable=True)  # JSON: serialized AgentLoopState for ReAct resume
```

- [ ] **Step 2: Generate/apply migration**

Run: `cd backend && python -c "from database import engine, Base; Base.metadata.create_all(engine); print('Schema updated')"` or via Alembic if configured.

For production, the SQL is:
```sql
ALTER TABLE action_executions ADD COLUMN IF NOT EXISTS loop_state TEXT;
```

- [ ] **Step 3: Commit**

```bash
git add backend/database.py
git commit -m "feat(db): add loop_state column to ActionExecution for ReAct resume"
```

---

## Task 6: Modify `ask.py` — Route actionnable agents to AgentExecutor

**Files:**
- Modify: `backend/routers/ask.py`

- [ ] **Step 1: Delete `detect_action_with_gemini` function (lines 31-65)**

Remove the entire function from `ask.py`.

- [ ] **Step 2: Delete `_ACTIONNABLE_REMOVED` block (lines 438-743)**

Remove the entire multi-line string from `ask.py`.

- [ ] **Step 3: Add AgentExecutor import at top of file**

Add to imports (after existing imports):

```python
from agent_executor import AgentExecutor
from google_credentials import get_google_credentials
```

- [ ] **Step 4: Replace the Stage 1 + Stage 2 flow for actionnable agents**

In the `POST /ask` handler, replace the block at lines 102-126 (the `if request.agent_id:` block) and lines 178-226 (Stage 2 action detection) with:

```python
        if request.agent_id:
            from database import Agent

            agent = _user_can_access_agent(int(user_id), request.agent_id, db)
            model_id = agent.finetuned_model_id or resolve_model_id(agent)
            logger.info(
                f"[LLM ROUTING] Agent '{agent.name}' type={getattr(agent, 'type', 'unknown')} -> model_id={model_id}"
            )

            # Actionnable agents use the ReAct loop
            if getattr(agent, "type", "") == "actionnable":
                credentials = get_google_credentials(int(user_id), db)
                executor = AgentExecutor()
                result = executor.run(
                    question=request.question,
                    agent=agent,
                    history=history,
                    db=db,
                    user_id=int(user_id),
                    credentials=credentials,
                    selected_doc_ids=request.selected_documents,
                    use_rag=request.use_rag,
                    use_graph=request.use_graph,
                )
                response_time = time.time() - start_time
                logger.info(f"Question answered for user {user_id} in {response_time:.2f}s")
                event_tracker.track_question_asked(int(user_id), request.question, response_time)

                # If the loop suspended on a write tool, answer is None
                answer_text = result["answer"] or ""
                # If we have a thought from the last step, prepend it so the user sees the reasoning
                if not answer_text and result.get("action_proposal"):
                    thought = result["action_proposal"].get("thought", "")
                    if thought:
                        answer_text = thought

                return {
                    "answer": answer_text,
                    "sources": result.get("sources", []),
                    "graph_data": None,
                    "action_proposal": result.get("action_proposal"),
                    "steps": result.get("steps", []),
                }

            # Non-actionnable agents use the standard RAG pipeline
            question_finale = request.question
            prompt = f"Sachant le contexte et la discussion en cours, réponds à cette question : {question_finale}"
            result = get_answer(
                prompt,
                int(user_id),
                db,
                selected_doc_ids=request.selected_documents,
                agent_id=request.agent_id,
                history=history,
                model_id=model_id,
                company_id=agent.company_id,
                use_rag=request.use_rag,
                use_graph=request.use_graph,
            )
            answer = result["answer"] if isinstance(result, dict) else result
            sources = result.get("sources", []) if isinstance(result, dict) else []
            graph_data = result.get("graph_data") if isinstance(result, dict) else None
```

- [ ] **Step 5: Remove the old Stage 2 block**

Delete lines 178-226 (the `# Stage 2: Action detection for actionnable agents` block). The `action_proposal` variable initialization on line 179 should also be removed. Instead, initialize `action_proposal = None` before the `if request.agent_id:` block and leave it as-is for non-actionnable paths.

The final return for non-actionnable agents becomes:

```python
        response_time = time.time() - start_time
        logger.info(f"Question answered for user {user_id} in {response_time:.2f}s")
        event_tracker.track_question_asked(int(user_id), request.question, response_time)
        return {"answer": answer, "sources": sources, "graph_data": graph_data, "action_proposal": None}
```

- [ ] **Step 6: Verify the non-actionnable path is untouched**

Run: `cd backend && python -c "from routers.ask import router; print('ask.py loads OK')"`

Expected: no import errors.

- [ ] **Step 7: Commit**

```bash
git add backend/routers/ask.py
git commit -m "feat(ask): route actionnable agents to ReAct loop, delete legacy code"
```

---

## Task 7: Modify `action_executions.py` — Scope validation + loop resume

**Files:**
- Modify: `backend/routers/action_executions.py`

- [ ] **Step 1: Add scope validation and loop resume to confirm endpoint**

Replace the entire `confirm_action` function in `backend/routers/action_executions.py`:

```python
@router.post("/actions/{execution_id}/confirm")
async def confirm_action(
    execution_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Confirm and execute a pending action, then resume the ReAct loop."""
    ae = db.query(ActionExecution).filter(
        ActionExecution.id == execution_id,
        ActionExecution.user_id == int(user_id),
    ).first()
    if not ae:
        raise HTTPException(status_code=404, detail="Action execution not found")
    if ae.status != "pending_confirmation":
        raise HTTPException(status_code=400, detail=f"Action is not pending confirmation (status: {ae.status})")

    ae.status = "confirmed"
    ae.confirmed_at = datetime.utcnow()
    db.flush()

    # Get user credentials
    credentials = get_google_credentials(int(user_id), db)
    if not credentials:
        ae.status = "failed"
        ae.error_message = "Google account not connected. Please connect your Google account first."
        db.commit()
        raise HTTPException(status_code=400, detail="Google account not connected")

    # Scope validation
    plugin = plugin_manager.get_plugin(ae.plugin_name)
    if plugin:
        from google_credentials import check_scopes_covered
        from database import UserGoogleToken
        token = db.query(UserGoogleToken).filter(UserGoogleToken.user_id == int(user_id)).first()
        if token:
            granted = json.loads(token.granted_scopes) if token.granted_scopes else []
            if not check_scopes_covered(granted, plugin.required_scopes):
                ae.status = "failed"
                ae.error_message = "Required Google scopes not granted. Please reconnect your Google account."
                db.commit()
                raise HTTPException(status_code=400, detail=ae.error_message)

    # Execute the action
    ae.status = "executing"
    db.flush()

    params = json.loads(ae.action_params)
    result = _execute_action(ae.plugin_name, ae.action_name, params, credentials)

    if result.success:
        ae.status = "completed"
        ae.result = json.dumps(result.data)
        ae.executed_at = datetime.utcnow()
    else:
        ae.status = "failed"
        ae.error_message = result.error_message
        ae.executed_at = datetime.utcnow()

    db.commit()

    # Resume the ReAct loop if loop_state is present
    continuation = None
    if ae.loop_state and result.success:
        try:
            from agent_executor import AgentExecutor, _observation_from_result
            obs = _observation_from_result(result)
            executor = AgentExecutor()
            continuation = executor.resume(ae.loop_state, obs, db, credentials)
        except Exception as e:
            logger.error(f"Failed to resume ReAct loop: {e}", exc_info=True)
    elif ae.loop_state and not result.success:
        try:
            from agent_executor import AgentExecutor
            obs = f"Echec: {result.error_message}"
            executor = AgentExecutor()
            continuation = executor.resume(ae.loop_state, obs, db, credentials)
        except Exception as e:
            logger.error(f"Failed to resume ReAct loop after failure: {e}", exc_info=True)

    response = {
        "status": ae.status,
        "display_message": result.display_message,
        "resource_url": result.resource_url,
        "data": result.data,
        "error_message": result.error_message,
    }
    if continuation:
        response["continuation"] = {
            "answer": continuation.get("answer"),
            "steps": continuation.get("steps", []),
            "action_proposal": continuation.get("action_proposal"),
        }
    return response
```

- [ ] **Step 2: Add loop resume to cancel endpoint**

Replace the `cancel_action` function:

```python
@router.post("/actions/{execution_id}/cancel")
async def cancel_action(
    execution_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Cancel a pending action and resume the agent loop."""
    ae = db.query(ActionExecution).filter(
        ActionExecution.id == execution_id,
        ActionExecution.user_id == int(user_id),
    ).first()
    if not ae:
        raise HTTPException(status_code=404, detail="Action execution not found")
    if ae.status != "pending_confirmation":
        raise HTTPException(status_code=400, detail=f"Cannot cancel action with status: {ae.status}")

    ae.status = "cancelled"
    db.commit()

    # Resume the ReAct loop with cancellation observation
    continuation = None
    if ae.loop_state:
        try:
            from agent_executor import AgentExecutor
            credentials = get_google_credentials(int(user_id), db)
            executor = AgentExecutor()
            continuation = executor.resume(
                ae.loop_state,
                "Action annulee par l'utilisateur.",
                db,
                credentials,
            )
        except Exception as e:
            logger.error(f"Failed to resume ReAct loop after cancel: {e}", exc_info=True)

    response = {"status": "cancelled"}
    if continuation:
        response["continuation"] = {
            "answer": continuation.get("answer"),
            "steps": continuation.get("steps", []),
            "action_proposal": continuation.get("action_proposal"),
        }
    return response
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/action_executions.py
git commit -m "feat(actions): add scope validation and ReAct loop resume on confirm/cancel"
```

---

## Task 8: Frontend — Handle new SSE events and agent continuation

**Files:**
- Modify: `frontend/lib/streamingFetch.js`
- Modify: `frontend/components/ActionProposal.js`
- Modify: `frontend/pages/chat/[agentId].js`

- [ ] **Step 1: Add new SSE event callbacks to `streamingFetch.js`**

In `frontend/lib/streamingFetch.js`, update the callbacks destructuring (line 13) and the event type handling (lines 106-116):

```javascript
export async function streamAsk(path, body, callbacks, signal) {
  const { onToken, onDone, onError, onRouting, onContribution, onThought, onAction, onObservation, onActionProposal } = callbacks;
```

And in the event handling block (after the `contribution` case):

```javascript
        if (eventType === 'token') {
          onToken?.(data.t || '');
        } else if (eventType === 'done') {
          onDone?.(data);
        } else if (eventType === 'error') {
          onError?.(data);
        } else if (eventType === 'routing') {
          onRouting?.(data);
        } else if (eventType === 'contribution') {
          onContribution?.(data);
        } else if (eventType === 'thought') {
          onThought?.(data);
        } else if (eventType === 'action') {
          onAction?.(data);
        } else if (eventType === 'observation') {
          onObservation?.(data);
        } else if (eventType === 'action_proposal') {
          onActionProposal?.(data);
        }
```

- [ ] **Step 2: Update ActionProposal to show thought and handle continuation**

Replace `frontend/components/ActionProposal.js`:

```javascript
import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import { Play, X, Check, AlertCircle, Loader2, ExternalLink, ChevronDown, ChevronUp, FileText, Table, Mail, Calendar, Presentation, HardDrive, Brain } from 'lucide-react';
import api from '../lib/api';

const PLUGIN_ICONS = {
  google_docs: FileText,
  google_sheets: Table,
  gmail: Mail,
  google_calendar: Calendar,
  google_slides: Presentation,
  google_drive: HardDrive,
};

export default function ActionProposal({ proposal, onResult, onContinuation }) {
  const { t } = useTranslation(['chat']);
  const [status, setStatus] = useState('pending');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  const Icon = PLUGIN_ICONS[proposal.plugin] || FileText;

  const handleConfirm = async () => {
    setLoading(true);
    setStatus('executing');
    try {
      const res = await api.post(`/actions/${proposal.execution_id}/confirm`);
      setStatus(res.data.status);
      setResult(res.data);
      if (onResult) onResult(res.data);
      // If the agent continued after this action, propagate
      if (res.data.continuation && onContinuation) {
        onContinuation(res.data.continuation);
      }
    } catch (e) {
      setStatus('failed');
      setResult({ error_message: e.response?.data?.detail || 'Execution failed' });
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    try {
      const res = await api.post(`/actions/${proposal.execution_id}/cancel`);
      setStatus('cancelled');
      if (res.data.continuation && onContinuation) {
        onContinuation(res.data.continuation);
      }
    } catch (e) {
      console.error('Failed to cancel action:', e);
    }
  };

  return (
    <div className="mt-3 border border-gray-200 rounded-card overflow-hidden bg-gray-50">
      {/* Header */}
      <div className="flex items-center px-4 py-2 bg-gray-100 border-b border-gray-200">
        <Icon className="w-4 h-4 text-gray-600 mr-2" />
        <span className="text-sm font-medium text-gray-700">{t('chat:actions.actionProposed')}</span>
      </div>

      {/* Body */}
      <div className="px-4 py-3">
        {/* Agent thought */}
        {proposal.thought && (
          <div className="flex items-start gap-2 mb-2 text-sm text-gray-600 italic">
            <Brain className="w-4 h-4 mt-0.5 shrink-0 text-gray-400" />
            <span>{proposal.thought}</span>
          </div>
        )}

        {/* Human-readable summary */}
        <p className="text-sm text-gray-800 mb-1">{proposal.display_summary}</p>

        {/* Expandable details */}
        <button
          onClick={() => setShowDetails(!showDetails)}
          className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1 mb-2"
        >
          {showDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          {showDetails ? 'Masquer les details' : 'Voir les details'}
        </button>
        {showDetails && (
          <pre className="text-xs bg-white border rounded p-2 mb-2 overflow-x-auto">
            {JSON.stringify(proposal.params, null, 2)}
          </pre>
        )}

        {/* Action buttons */}
        {status === 'pending' && (
          <div className="flex gap-2 mt-3">
            <button
              onClick={handleConfirm}
              disabled={loading}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-button hover:bg-green-700 transition-colors disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Play className="w-4 h-4 mr-1" />}
              {t('chat:actions.confirm')}
            </button>
            <button
              onClick={handleCancel}
              disabled={loading}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-gray-700 bg-gray-200 rounded-button hover:bg-gray-300 transition-colors disabled:opacity-50"
            >
              <X className="w-4 h-4 mr-1" />
              {t('chat:actions.cancel')}
            </button>
          </div>
        )}

        {/* Status badges — same as before */}
        {status === 'executing' && (
          <div className="flex items-center mt-3 text-sm text-blue-600">
            <Loader2 className="w-4 h-4 mr-1 animate-spin" />
            {t('chat:actions.executing')}
          </div>
        )}

        {status === 'completed' && result && (
          <div className="mt-3 p-3 bg-green-50 rounded-button border border-green-200">
            <div className="flex items-center text-sm text-green-700">
              <Check className="w-4 h-4 mr-1" />
              {t('chat:actions.completed')}
            </div>
            {result.display_message && (
              <p className="text-sm text-green-800 mt-1">{result.display_message}</p>
            )}
            {result.resource_url && (
              <a href={result.resource_url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center mt-2 text-sm text-blue-600 hover:underline">
                <ExternalLink className="w-3 h-3 mr-1" /> {t('chat:messages.openButton')}
              </a>
            )}
          </div>
        )}

        {status === 'failed' && (
          <div className="mt-3 p-3 bg-red-50 rounded-button border border-red-200">
            <div className="flex items-center text-sm text-red-700">
              <AlertCircle className="w-4 h-4 mr-1" /> {t('chat:actions.failed')}
            </div>
            {result?.error_message && (
              <p className="text-sm text-red-600 mt-1">{result.error_message}</p>
            )}
          </div>
        )}

        {status === 'cancelled' && (
          <div className="mt-3 flex items-center text-sm text-gray-500">
            <X className="w-4 h-4 mr-1" /> {t('chat:actions.cancelled')}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Update chat page to handle continuation after confirm/cancel**

In `frontend/pages/chat/[agentId].js`, find where `ActionProposal` is rendered (around line 1055) and add the `onContinuation` callback:

```javascript
{msg.action_proposal && (
  <ActionProposal
    proposal={msg.action_proposal}
    onResult={(data) => {
      // existing onResult handling
    }}
    onContinuation={(continuation) => {
      if (continuation.answer) {
        // Append agent's continuation as a new message
        setMessages(prev => [...prev, {
          role: 'agent',
          content: continuation.answer,
          sources: [],
          action_proposal: continuation.action_proposal || undefined,
        }]);
      }
    }}
  />
)}
```

- [ ] **Step 4: Update the `/ask` response handling for actionnable agents**

In the `/ask` fallback path (around line 635), handle the `steps` field:

```javascript
iaActionProposal = resAsk.data.action_proposal || null;
const iaSteps = resAsk.data.steps || [];
```

And in the non-streaming `/ask` response handling (around line 445):

```javascript
const slashActionProposal = resAsk.data.action_proposal || null;
const slashSteps = resAsk.data.steps || [];
const assistantMsg = {
  role: 'agent',
  content: resAsk.data.answer,
  sources: slashSources,
  graph_data: slashGraphData,
  action_proposal: slashActionProposal,
  steps: slashSteps,
};
```

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/streamingFetch.js frontend/components/ActionProposal.js frontend/pages/chat/[agentId].js
git commit -m "feat(frontend): handle ReAct reasoning steps and agent continuation after confirm/cancel"
```

---

## Task 9: Add streaming support for actionnable agents

**Files:**
- Modify: `backend/agent_executor.py` (add `run_stream` method)
- Modify: `backend/routers/ask.py` (wire streaming path)

- [ ] **Step 1: Implement `run_stream` in AgentExecutor**

Add this method to the `AgentExecutor` class in `backend/agent_executor.py`:

```python
    def run_stream(
        self,
        question: str,
        agent,
        history: list[dict],
        db,
        user_id: int,
        credentials,
        selected_doc_ids: list[int] | None = None,
        use_rag: bool = True,
        use_graph: bool = True,
    ):
        """Generator yielding SSE event tuples for the ReAct loop.

        Yields: (event_type: str, data: dict)
        """
        from agent_tools import build_tools_from_plugins
        from plugins import plugin_manager
        from streaming_response import sse_event
        from database import ActionExecution
        from helpers.tenant import _get_caller_company_id

        # Setup (same as run)
        enabled_plugins = []
        if agent.enabled_plugins:
            try:
                enabled_plugins = json.loads(agent.enabled_plugins)
            except Exception:
                enabled_plugins = []
        tools = build_tools_from_plugins(enabled_plugins, plugin_manager)
        tool_names = [t.name for t in tools]
        tool_map = {t.name: t for t in tools}

        rag_context, sources = get_rag_context(
            agent, user_id, db, question,
            selected_doc_ids=selected_doc_ids,
            use_rag=use_rag, use_graph=use_graph,
            company_id=agent.company_id,
        )

        system_prompt = build_react_prompt(
            agent_name=agent.name,
            agent_contexte=getattr(agent, "contexte", "") or "",
            agent_biographie=getattr(agent, "biographie", "") or "",
            tools=tools,
            rag_context=rag_context,
        )

        model_id = agent.finetuned_model_id or resolve_model_id(agent)
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            for msg in history[-10:]:
                role = msg.get("role", "user")
                if role == "agent":
                    role = "assistant"
                elif role == "system":
                    continue
                messages.append({"role": role, "content": msg.get("content", "")})
        messages.append({"role": "user", "content": question})

        steps = []
        for i in range(self.MAX_ITERATIONS):
            llm_response = get_chat_response(messages, model_id=model_id)
            step = parse_llm_output(llm_response, tool_names)

            if isinstance(step, FinishStep):
                steps.append({"type": "finish", "answer": step.answer})
                # Stream the final answer token by token
                for char in step.answer:
                    yield sse_event("token", {"t": char})
                yield sse_event("done", {
                    "full_text": step.answer, "steps": steps, "sources": sources,
                    "graph_data": None, "action_proposal": None,
                })
                return

            if isinstance(step, FallbackStep):
                steps.append({"type": "fallback", "text": step.text})
                for char in step.text:
                    yield sse_event("token", {"t": char})
                yield sse_event("done", {
                    "full_text": step.text, "steps": steps, "sources": sources,
                    "graph_data": None, "action_proposal": None,
                })
                return

            if isinstance(step, ActionStep):
                tool_def = tool_map.get(step.tool_name)
                steps.append({
                    "type": "action", "thought": step.thought,
                    "tool": step.tool_name, "args": step.tool_args,
                    "side_effect": tool_def.side_effect if tool_def else True,
                })

                yield sse_event("thought", {"content": step.thought})
                yield sse_event("action", {
                    "tool": step.tool_name, "args": step.tool_args,
                    "type": "write" if (tool_def and tool_def.side_effect) else "read",
                })

                if tool_def and not tool_def.side_effect:
                    result = _execute_read_tool(tool_def.plugin_name, step.tool_name, step.tool_args, credentials)
                    obs = _observation_from_result(result)
                    steps.append({"type": "observation", "tool": step.tool_name, "result": obs})
                    yield sse_event("observation", {"tool": step.tool_name, "result": obs})
                    messages.append({"role": "assistant", "content": llm_response})
                    messages.append({"role": "user", "content": f"Observation: {obs}"})
                    continue
                else:
                    # Write tool — suspend
                    company_id = getattr(agent, "company_id", None) or _get_caller_company_id(str(user_id), db)
                    plugin_name = tool_def.plugin_name if tool_def else "unknown"

                    ae = ActionExecution(
                        agent_id=agent.id, user_id=user_id, company_id=company_id,
                        plugin_name=plugin_name, action_name=step.tool_name,
                        action_params=json.dumps(step.tool_args, ensure_ascii=False),
                        status="pending_confirmation",
                    )
                    db.add(ae)
                    messages.append({"role": "assistant", "content": llm_response})
                    state = AgentLoopState(
                        messages=messages, iteration=i + 1, steps=steps,
                        agent_id=agent.id, user_id=user_id, question=question,
                        model_id=model_id, sources=sources,
                    )
                    ae.loop_state = state.to_json()
                    db.commit()
                    db.refresh(ae)

                    display_parts = [f"{k}: {v}" for k, v in list(step.tool_args.items())[:3]]
                    display_summary = f"{tool_def.display_name if tool_def else step.tool_name} — {', '.join(display_parts)}"

                    proposal = {
                        "execution_id": ae.id, "plugin": plugin_name,
                        "action": step.tool_name, "params": step.tool_args,
                        "display_summary": display_summary, "thought": step.thought,
                    }
                    yield sse_event("action_proposal", proposal)
                    yield sse_event("done", {
                        "full_text": step.thought or "", "steps": steps, "sources": sources,
                        "graph_data": None, "action_proposal": proposal,
                    })
                    return

        # Max iterations
        messages.append({"role": "user", "content": "Tu as atteint le nombre maximum d'etapes. Donne ta reponse finale maintenant."})
        forced = get_chat_response(messages, model_id=model_id)
        forced_step = parse_llm_output(forced, tool_names)
        answer = forced_step.answer if isinstance(forced_step, FinishStep) else str(forced)
        steps.append({"type": "forced_finish", "answer": answer})
        for char in answer:
            yield sse_event("token", {"t": char})
        yield sse_event("done", {
            "full_text": answer, "steps": steps, "sources": sources,
            "graph_data": None, "action_proposal": None,
        })
```

- [ ] **Step 2: Wire `run_stream` into the `/ask-stream` endpoint**

In `backend/routers/ask.py`, inside the `event_generator()` function of the `/ask-stream` endpoint, add the actionnable agent path before the standard `get_answer_stream` call. Right after the `agent` and `model_id` are resolved:

```python
            if request.agent_id:
                agent = _user_can_access_agent(int(user_id), request.agent_id, db)
                model_id = agent.finetuned_model_id or resolve_model_id(agent)

                # Actionnable agents use the ReAct streaming loop
                if getattr(agent, "type", "") == "actionnable":
                    credentials = get_google_credentials(int(user_id), db)
                    executor = AgentExecutor()
                    yield from executor.run_stream(
                        question=request.question,
                        agent=agent,
                        history=history,
                        db=db,
                        user_id=int(user_id),
                        credentials=credentials,
                        selected_doc_ids=request.selected_documents,
                        use_rag=request.use_rag,
                        use_graph=request.use_graph,
                    )
                    return

                # Non-actionnable: standard streaming
                question_finale = request.question
                prompt = f"Sachant le contexte et la discussion en cours, réponds à cette question : {question_finale}"
                yield from get_answer_stream(
                    prompt, int(user_id), db, ...
                )
```

- [ ] **Step 3: Commit**

```bash
git add backend/agent_executor.py backend/routers/ask.py
git commit -m "feat: add ReAct streaming support for actionnable agents via /ask-stream"
```

---

## Task 10: Final cleanup and verification

**Files:**
- Verify: `backend/routers/ask.py` — no dead imports

- [ ] **Step 1: Remove unused imports from `ask.py`**

After deleting `detect_action_with_gemini` and the `_ACTIONNABLE_REMOVED` block, clean up any imports that are no longer needed. Specifically check if these are still used:
- `from utils_ai import normalize_model_output, extract_json_object_from_text` — likely only used by removed code
- `from actions import ...` — check if still referenced

Remove any that are now unused.

- [ ] **Step 2: Run the full backend test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short`

Expected: all existing tests pass, plus new tests from `test_agent_tools.py` and `test_agent_executor.py`.

- [ ] **Step 3: Run frontend lint**

Run: `cd frontend && npm run lint`

Expected: no new lint errors.

- [ ] **Step 4: Manual smoke test**

1. Start the full stack: `docker-compose up --build`
2. Create/edit an actionnable agent with Gmail plugin enabled
3. Connect Google account via PluginSelector
4. Ask: "peux tu envoyer un mail ?" — verify the agent says it CAN and proposes the action
5. Ask: "envoie un mail a test@example.com pour dire bonjour" — verify action proposal appears with thought + confirm/cancel
6. Click confirm — verify email sends and agent gives final answer
7. Test cancel flow — verify agent adapts response
8. Test a non-actionnable agent — verify it still works identically to before

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: cleanup dead imports after ReAct migration"
```
