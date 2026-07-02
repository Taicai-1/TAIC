"""Conversational CV intelligence: intent router + three read-only tools
(sourcing / analytics / candidate Q&A) layered on top of the RAG answer path.

Activated only for companions whose company-RAG folders include a CV-base folder;
otherwise callers fall back to the normal RAG flow (answer_cv returns None)."""

import json
import logging

from openai_client import get_chat_response, get_chat_response_with_tools

logger = logging.getLogger(__name__)


def folders_include_cv_base(db, company_id, folder_ids):
    """True if the company has a CV-base folder within ``folder_ids`` (or any, if None)."""
    if not company_id:
        return False
    from database import CompanyFolder

    q = db.query(CompanyFolder.id).filter(
        CompanyFolder.company_id == company_id,
        CompanyFolder.is_cv_base.is_(True),
    )
    if folder_ids:
        q = q.filter(CompanyFolder.id.in_(folder_ids))
    return bool(db.query(q.exists()).scalar())


CV_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cv_sourcing",
            "description": "Find and rank candidate CVs matching required skills / seniority / location. Use for 'find/trouve/cherche des candidats/profils qui ...'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Required skills, e.g. ['python','react']",
                    },
                    "seniority": {"type": "string", "description": "junior|confirmé|senior|lead"},
                    "location": {"type": "string"},
                    "min_years": {"type": "integer"},
                    "free_text": {
                        "type": "string",
                        "description": "Free-text of the need / job offer for semantic ranking",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cv_analytics",
            "description": "Aggregate statistics over the CV base (counts, averages, distributions). Use for 'combien / how many / moyenne / répartition ...'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "enum": ["count", "avg_experience", "distribution"]},
                    "dimension": {"type": "string", "enum": ["skill", "seniority", "location", "language"]},
                    "filter": {
                        "type": "object",
                        "properties": {
                            "skill": {"type": "string"},
                            "seniority": {"type": "string"},
                            "location": {"type": "string"},
                            "min_years": {"type": "integer"},
                        },
                    },
                },
                "required": ["metric", "dimension"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cv_qa",
            "description": "Answer a question about ONE specific named candidate. Use for 'résume le parcours de X', 'quelles compétences a X'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_name": {"type": "string", "description": "Full or partial name of the candidate"},
                    "question": {"type": "string", "description": "The question to answer about the candidate"},
                },
                "required": ["candidate_name", "question"],
            },
        },
    },
]

_ROUTER_SYSTEM = (
    "You route a recruiter's message about a CV database to the right tool. "
    "Call cv_sourcing to find/rank candidates, cv_analytics for counts/averages/distributions, "
    "cv_qa for a question about one named candidate. "
    "If the message is small talk or unrelated to the CV base, DO NOT call any tool."
)


def route_cv_intent(question, history, model_id):
    """Return (tool_name, args_dict) chosen by the LLM, or None to fall back to normal RAG."""
    messages = [{"role": "system", "content": _ROUTER_SYSTEM}]
    for m in (history or [])[-6:]:  # last 3 turns for routing context
        role = m.get("role") if isinstance(m, dict) else None
        content = m.get("content") if isinstance(m, dict) else None
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    try:
        resp = get_chat_response_with_tools(messages, tools=CV_TOOLS, model_id=model_id)
    except Exception as e:
        logger.warning(f"cv route failed: {e}")
        return None
    if resp.tool_call is None:
        return None
    return resp.tool_call.name, (resp.tool_call.arguments or {})


class _CvContext:
    """Everything a tool handler needs, bundled so handlers share one signature."""

    def __init__(self, question, user_id, db, agent_id, history, model_id, company_id, folder_ids):
        self.question = question
        self.user_id = user_id
        self.db = db
        self.agent_id = agent_id
        self.history = history
        self.model_id = model_id
        self.company_id = company_id
        self.folder_ids = folder_ids


# Populated by later tasks: {"cv_qa": fn, "cv_sourcing": fn, "cv_analytics": fn}.
# Each handler has signature (args: dict, ctx: _CvContext) -> dict | None.
_HANDLERS = {}


def answer_cv(question, user_id, db, agent_id, history, model_id, company_id, folder_ids):
    """Route the message to a CV tool and return an answer dict, or None to fall back to RAG."""
    routed = route_cv_intent(question, history, model_id)
    if routed is None:
        return None
    name, args = routed
    handler = _HANDLERS.get(name)
    if handler is None:
        return None
    try:
        ctx = _CvContext(question, user_id, db, agent_id, history, model_id, company_id, folder_ids)
        result = handler(args, ctx)
        if result is None:
            return None
        if not result:  # empty dict = handler bug; fall back to RAG but make it visible
            logger.warning(f"cv_agent handler '{name}' returned an empty result")
            return None
        # A handler may ask the orchestrator to run targeted single-CV RAG (Q&A).
        if result.get("stream_doc_id"):
            import rag_engine

            return rag_engine.get_answer(
                result.get("question", ctx.question),
                ctx.user_id,
                ctx.db,
                selected_doc_ids=[result["stream_doc_id"]],
                agent_id=ctx.agent_id,
                history=ctx.history,
                model_id=ctx.model_id,
                company_id=ctx.company_id,
            )
        return result
    except Exception as e:
        logger.warning(f"cv_agent handler '{name}' failed: {e}")
        return None
