"""ReAct agent executor for actionnable agents.

Implements a Reasoning + Acting loop using native LLM function calling:
- Builds a system prompt with agent personality and RAG context
- Iteratively calls the LLM with tools via function calling API
- Auto-executes read-only tools, suspends on write tools for user confirmation
- Resumes after confirmation with the action result
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step types returned by the loop
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


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_REACT_SYSTEM_TEMPLATE = """Tu es {agent_name}, un assistant IA actionnable.
{agent_contexte}
{agent_biographie}

REGLES :
1. Raisonne etape par etape avant d'agir.
2. Tu peux enchainer plusieurs appels d'outils avant de donner ta reponse finale.
3. Ne fabrique JAMAIS le resultat d'un outil. Attends toujours le retour.
4. Si tu n'as pas besoin d'outil, reponds directement en texte.
5. Reponds toujours dans la langue de l'utilisateur.
{rag_block}"""


def build_react_prompt(
    agent_name: str,
    agent_contexte: str,
    agent_biographie: str,
    tools: list,
    rag_context: str,
) -> str:
    """Build the system prompt for the agent (tools are provided via function calling API)."""
    rag_block = ""
    if rag_context:
        rag_block = f"\n\n--- Contexte documentaire ---\n{rag_context}"

    return _REACT_SYSTEM_TEMPLATE.format(
        agent_name=agent_name,
        agent_contexte=agent_contexte.strip() if agent_contexte else "",
        agent_biographie=agent_biographie.strip() if agent_biographie else "",
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


from openai_client import get_chat_response, get_chat_response_with_tools
from helpers.agent_helpers import resolve_model_id


# ---------------------------------------------------------------------------
# RAG context retrieval (delegates to rag_engine)
# ---------------------------------------------------------------------------


def get_rag_context(
    agent, user_id: int, db, question: str, selected_doc_ids=None, use_rag=True, use_graph=True, company_id=None
) -> tuple[str, list]:
    """Retrieve RAG document context for the agent.

    Returns (context_text, sources). Delegates to rag_engine internals
    but only retrieves chunks — does NOT call the LLM.
    """
    if not use_rag:
        return "", []

    from rag_engine import search_similar_texts_for_user, get_embedding
    from database import Document

    try:
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
            query_embedding,
            user_id,
            db,
            top_k=8,
            selected_doc_ids=selected_doc_ids,
            agent_id=agent.id,
            company_id=company_id,
        )

        sources = [
            {
                "text": r["text"],
                "document_name": r["document_name"],
                "score": round(r["similarity"] * 100, 1),
                "document_id": r["document_id"],
            }
            for r in results
        ]

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
        return ActionResult(
            success=False,
            data={},
            display_message="",
            resource_url=None,
            error_message=f"Plugin '{plugin_name}' not found",
        )
    return plugin.execute(action_name, args, credentials)


def _observation_from_result(result: "ActionResult") -> str:
    """Format an ActionResult as an Observation string for the LLM."""
    if result.success:
        data_str = json.dumps(result.data, ensure_ascii=False, default=str)
        if len(data_str) > 3000:
            data_str = data_str[:3000] + "... (tronque)"
        return f"Succes. {result.display_message}\nDonnees: {data_str}"
    else:
        return f"Echec: {result.error_message}"


# ---------------------------------------------------------------------------
# Shared helpers for run() and run_stream()
# ---------------------------------------------------------------------------


def _load_agent_tools(agent):
    """Load tools from agent's enabled plugins.

    Returns (tools, tool_names, tool_map, openai_tools).
    """
    from agent_tools import build_tools_from_plugins, tools_to_openai_format
    from plugins import plugin_manager

    enabled_plugins = []
    if agent.enabled_plugins:
        try:
            enabled_plugins = json.loads(agent.enabled_plugins)
        except Exception:
            enabled_plugins = []
    tools = build_tools_from_plugins(enabled_plugins, plugin_manager)
    tool_names = [t.name for t in tools]
    tool_map = {t.name: t for t in tools}
    openai_tools = tools_to_openai_format(tools)
    return tools, tool_names, tool_map, openai_tools


def _build_initial_messages(agent, question: str, history: list[dict], tools: list, rag_context: str):
    """Build the initial messages list and resolve model_id.

    Returns (model_id, messages).
    """
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
    return model_id, messages


# ---------------------------------------------------------------------------
# Iteration result — structured outcome of a single ReAct iteration
# ---------------------------------------------------------------------------


@dataclass
class _IterationResult:
    """Result of a single ReAct loop iteration."""

    kind: str  # "finish", "read_continue", "write_suspend", "empty"
    step: ActionStep | FinishStep | None = None
    llm_response: str = ""
    observation: str = ""
    # Only set for write_suspend
    action_execution_id: int | None = None
    loop_state_json: str | None = None
    display_summary: str = ""
    proposal: dict | None = None


def _process_iteration(
    messages: list[dict],
    steps: list[dict],
    tool_names: list[str],
    tool_map: dict,
    openai_tools: list[dict],
    model_id: str,
    sources: list,
    agent,
    user_id: int,
    question: str,
    db,
    credentials,
    iteration: int,
) -> _IterationResult:
    """Process a single iteration of the ReAct loop using native function calling.

    Calls the LLM with tools, then:
    - If tool_call is present -> ActionStep (read: auto-execute, write: suspend)
    - If only content -> FinishStep (direct text answer)
    - If neither -> empty
    """
    from database import ActionExecution
    from helpers.tenant import _get_caller_company_id

    response = get_chat_response_with_tools(messages, tools=openai_tools, model_id=model_id)

    if response.tool_call is None and not response.content:
        logger.warning(f"[ReAct iter {iteration}] LLM returned empty response")
        return _IterationResult(kind="empty")

    # No tool call -> treat content as final answer
    if response.tool_call is None:
        answer = response.content or ""
        logger.info(f"[ReAct iter {iteration}] Final answer: {answer[:300]}")
        step = FinishStep(answer=answer)
        steps.append({"type": "finish", "answer": answer})
        return _IterationResult(kind="finish", step=step, llm_response=answer)

    # Tool call present
    tc = response.tool_call
    thought = response.content or ""  # Some providers put reasoning in content alongside the tool call
    logger.info(f"[ReAct iter {iteration}] Tool call: {tc.name}({json.dumps(tc.arguments, ensure_ascii=False)[:200]})")

    tool_def = tool_map.get(tc.name)
    step = ActionStep(thought=thought, tool_name=tc.name, tool_args=tc.arguments)
    steps.append(
        {
            "type": "action",
            "thought": thought,
            "tool": tc.name,
            "args": tc.arguments,
            "side_effect": tool_def.side_effect if tool_def else True,
        }
    )

    # Build OpenAI-compatible assistant + tool messages for multi-turn
    assistant_msg = {
        "role": "assistant",
        "content": thought or None,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
        ],
    }
    tool_result_msg = {
        "role": "tool",
        "tool_call_id": tc.id,
        "content": "",  # filled in below
    }

    if tool_def and not tool_def.side_effect:
        # Read-only tool — execute immediately
        result = _execute_read_tool(tool_def.plugin_name, tc.name, tc.arguments, credentials)
        obs = _observation_from_result(result)
        steps.append({"type": "observation", "tool": tc.name, "result": obs})

        messages.append(assistant_msg)
        tool_result_msg["content"] = obs
        messages.append(tool_result_msg)
        return _IterationResult(kind="read_continue", step=step, llm_response=thought, observation=obs)

    # Write tool — suspend for user confirmation
    company_id = getattr(agent, "company_id", None) or _get_caller_company_id(str(user_id), db)
    plugin_name = tool_def.plugin_name if tool_def else "unknown"

    ae = ActionExecution(
        agent_id=agent.id,
        user_id=user_id,
        company_id=company_id,
        plugin_name=plugin_name,
        action_name=tc.name,
        action_params=json.dumps(tc.arguments, ensure_ascii=False),
        status="pending_confirmation",
    )
    db.add(ae)

    # Store assistant message with tool call for resume
    messages.append(assistant_msg)

    state = AgentLoopState(
        messages=messages,
        iteration=iteration + 1,
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

    display_parts = [f"{k}: {v}" for k, v in list(tc.arguments.items())[:3]]
    display_summary = f"{tool_def.display_name if tool_def else tc.name} — {', '.join(display_parts)}"

    proposal = {
        "execution_id": ae.id,
        "plugin": plugin_name,
        "action": tc.name,
        "params": tc.arguments,
        "display_summary": display_summary,
        "thought": thought,
    }

    return _IterationResult(
        kind="write_suspend",
        step=step,
        llm_response=thought,
        action_execution_id=ae.id,
        loop_state_json=state.to_json(),
        display_summary=display_summary,
        proposal=proposal,
    )


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
                "answer": str | None,
                "steps": list[dict],
                "action_proposal": dict | None,
                "loop_state": str | None,
                "sources": list,
            }
        """
        tools, tool_names, tool_map, openai_tools = _load_agent_tools(agent)

        rag_context, sources = get_rag_context(
            agent,
            user_id,
            db,
            question,
            selected_doc_ids=selected_doc_ids,
            use_rag=use_rag,
            use_graph=use_graph,
            company_id=agent.company_id,
        )

        model_id, messages = _build_initial_messages(agent, question, history, tools, rag_context)

        steps = []
        return self._loop(
            messages,
            steps,
            tool_names,
            tool_map,
            openai_tools,
            model_id,
            sources,
            agent,
            user_id,
            question,
            db,
            credentials,
            iteration=0,
        )

    def resume(self, loop_state: str, observation: str, db, credentials) -> dict:
        """Resume a suspended loop after user confirmation/cancellation."""
        state = AgentLoopState.from_json(loop_state)

        from database import Agent

        agent = db.query(Agent).filter(Agent.id == state.agent_id).first()
        _, tool_names, tool_map, openai_tools = _load_agent_tools(agent)

        messages = state.messages
        # After confirmation, add the tool result.
        # New format: assistant msg has tool_calls array -> use role "tool" with tool_call_id.
        # Old format (pre-migration): no tool_calls -> use role "user" with Observation prefix.
        last_tool_call_id = None
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                last_tool_call_id = msg["tool_calls"][0].get("id", "")
                break
        if last_tool_call_id:
            messages.append({"role": "tool", "tool_call_id": last_tool_call_id, "content": observation})
        else:
            messages.append({"role": "user", "content": f"Observation: {observation}"})

        return self._loop(
            messages,
            state.steps,
            tool_names,
            tool_map,
            openai_tools,
            state.model_id,
            state.sources,
            agent,
            state.user_id,
            state.question,
            db,
            credentials,
            iteration=state.iteration,
        )

    def _loop(
        self,
        messages,
        steps,
        tool_names,
        tool_map,
        openai_tools,
        model_id,
        sources,
        agent,
        user_id,
        question,
        db,
        credentials,
        iteration,
    ):
        """Core ReAct loop shared by run() and resume()."""
        for i in range(iteration, self.MAX_ITERATIONS):
            result = _process_iteration(
                messages,
                steps,
                tool_names,
                tool_map,
                openai_tools,
                model_id,
                sources,
                agent,
                user_id,
                question,
                db,
                credentials,
                i,
            )

            if result.kind == "empty":
                return {
                    "answer": "Désolé, je n'ai pas pu générer de réponse.",
                    "steps": steps,
                    "action_proposal": None,
                    "loop_state": None,
                    "sources": sources,
                }

            if result.kind == "finish":
                return {
                    "answer": result.step.answer,
                    "steps": steps,
                    "action_proposal": None,
                    "loop_state": None,
                    "sources": sources,
                }

            if result.kind == "read_continue":
                continue

            if result.kind == "write_suspend":
                return {
                    "answer": None,
                    "steps": steps,
                    "action_proposal": result.proposal,
                    "loop_state": result.loop_state_json,
                    "sources": sources,
                }

        # Max iterations reached — force a text-only response (no tools)
        messages.append(
            {
                "role": "user",
                "content": "Tu as atteint le nombre maximum d'etapes. Donne ta reponse finale maintenant avec ce que tu sais.",
            }
        )
        forced = get_chat_response(messages, model_id=model_id)
        answer = forced if forced else "Désolé, je n'ai pas pu finaliser ma réponse."
        steps.append({"type": "forced_finish", "answer": answer})
        return {
            "answer": answer,
            "steps": steps,
            "action_proposal": None,
            "loop_state": None,
            "sources": sources,
        }

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
        """Generator yielding SSE event strings for the ReAct loop.

        Yields: str (formatted SSE events via sse_event())
        """
        from streaming_response import sse_event

        tools, tool_names, tool_map, openai_tools = _load_agent_tools(agent)

        rag_context, sources = get_rag_context(
            agent,
            user_id,
            db,
            question,
            selected_doc_ids=selected_doc_ids,
            use_rag=use_rag,
            use_graph=use_graph,
            company_id=agent.company_id,
        )

        model_id, messages = _build_initial_messages(agent, question, history, tools, rag_context)

        steps = []
        for i in range(self.MAX_ITERATIONS):
            result = _process_iteration(
                messages,
                steps,
                tool_names,
                tool_map,
                openai_tools,
                model_id,
                sources,
                agent,
                user_id,
                question,
                db,
                credentials,
                i,
            )

            if result.kind == "empty":
                yield sse_event("done", {"full_text": "Désolé, je n'ai pas pu générer de réponse.", "sources": sources})
                return

            if result.kind == "finish":
                for char in result.step.answer:
                    yield sse_event("token", {"t": char})
                yield sse_event(
                    "done",
                    {
                        "full_text": result.step.answer,
                        "steps": steps,
                        "sources": sources,
                        "graph_data": None,
                        "action_proposal": None,
                    },
                )
                return

            if result.kind == "read_continue":
                yield sse_event("thought", {"content": result.step.thought})
                yield sse_event(
                    "action",
                    {
                        "tool": result.step.tool_name,
                        "args": result.step.tool_args,
                        "type": "read",
                    },
                )
                yield sse_event("observation", {"tool": result.step.tool_name, "result": result.observation})
                continue

            if result.kind == "write_suspend":
                yield sse_event("thought", {"content": result.step.thought})
                yield sse_event(
                    "action",
                    {
                        "tool": result.step.tool_name,
                        "args": result.step.tool_args,
                        "type": "write",
                    },
                )
                yield sse_event("action_proposal", result.proposal)
                yield sse_event(
                    "done",
                    {
                        "full_text": result.step.thought or "",
                        "steps": steps,
                        "sources": sources,
                        "graph_data": None,
                        "action_proposal": result.proposal,
                    },
                )
                return

        # Max iterations
        messages.append(
            {"role": "user", "content": "Tu as atteint le nombre maximum d'etapes. Donne ta reponse finale maintenant."}
        )
        forced = get_chat_response(messages, model_id=model_id)
        answer = forced if forced else "Désolé, je n'ai pas pu finaliser ma réponse."
        steps.append({"type": "forced_finish", "answer": answer})
        for char in answer:
            yield sse_event("token", {"t": char})
        yield sse_event(
            "done",
            {
                "full_text": answer,
                "steps": steps,
                "sources": sources,
                "graph_data": None,
                "action_proposal": None,
            },
        )
