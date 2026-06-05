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
                "answer": str | None,
                "steps": list[dict],
                "action_proposal": dict | None,
                "loop_state": str | None,
                "sources": list,
            }
        """
        from agent_tools import build_tools_from_plugins
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
        return self._loop(messages, steps, tool_names, tool_map, model_id, sources,
                         agent, user_id, question, db, credentials, iteration=0)

    def resume(self, loop_state: str, observation: str, db, credentials) -> dict:
        """Resume a suspended loop after user confirmation/cancellation."""
        state = AgentLoopState.from_json(loop_state)

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
            llm_response = get_chat_response(messages, model_id=model_id)
            if not llm_response:
                logger.warning(f"[ReAct iter {i}] LLM returned empty response")
                return {
                    "answer": "Désolé, je n'ai pas pu générer de réponse.",
                    "steps": steps, "action_proposal": None, "loop_state": None, "sources": sources,
                }
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
                    result = _execute_read_tool(tool_def.plugin_name, step.tool_name, step.tool_args, credentials)
                    obs = _observation_from_result(result)
                    steps.append({"type": "observation", "tool": step.tool_name, "result": obs})
                    messages.append({"role": "assistant", "content": llm_response})
                    messages.append({"role": "user", "content": f"Observation: {obs}"})
                    continue

                else:
                    company_id = getattr(agent, "company_id", None) or _get_caller_company_id(str(user_id), db)
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

        # Max iterations reached
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
            if not llm_response:
                logger.warning(f"[ReAct stream iter {i}] LLM returned empty response")
                yield sse_event("done", {"full_text": "Désolé, je n'ai pas pu générer de réponse.", "sources": sources})
                return
            step = parse_llm_output(llm_response, tool_names)

            if isinstance(step, FinishStep):
                steps.append({"type": "finish", "answer": step.answer})
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
