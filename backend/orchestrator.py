"""Team orchestration engine.

Handles LLM-based routing, parallel agent execution, response synthesis,
and auto-detection of agent specializations.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from mistral_client import generate_text
from rag_engine import get_answer
from helpers.agent_helpers import resolve_model_id

logger = logging.getLogger(__name__)

DEFAULT_ROUTING_PROMPT = """Tu es le coordinateur d'une equipe d'agents specialises.
Analyse la question suivante et determine quel(s) agent(s) consulter.

Agents disponibles:
{agent_list}

Regles:
- Selectionne 1 a 3 agents maximum
- Si la question est transverse, selectionne plusieurs agents
- Si aucun agent n'est pertinent, retourne une liste vide (tu repondras toi-meme)

Retourne UNIQUEMENT un JSON: {{"agent_ids": [5, 8], "reasoning": "..."}}"""

DEFAULT_SYNTHESIS_PROMPT = """Tu es le coordinateur de l'equipe "{team_name}". {team_contexte}

Voici les contributions de tes agents specialises:

{contributions_text}

Synthetise ces contributions en une reponse claire et complete pour l'utilisateur.
Integre naturellement les informations sans repetition."""

SPECIALIZATION_PROMPT = """Analyse les informations suivantes sur un agent IA et genere une description courte (1-2 phrases) de sa specialite/expertise.

Nom: {name}
Contexte systeme: {contexte}
Biographie: {biographie}
Documents: {documents}

Retourne UNIQUEMENT la description de specialite, rien d'autre."""


def _call_llm_for_routing(prompt: str, model_id: str) -> dict:
    """Call LLM and parse JSON routing response."""
    raw = generate_text(prompt, model_name=model_id, temperature=0.1, max_tokens=500)
    # Extract JSON from response (may be wrapped in markdown code block)
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    parsed = json.loads(text)
    if not isinstance(parsed.get("agent_ids"), list):
        raise ValueError("Missing or invalid agent_ids in routing response")
    return parsed


def _call_llm_for_specialization(prompt: str) -> str:
    """Call LLM to generate specialization description."""
    return generate_text(prompt, model_name="mistral-small-latest", temperature=0.3, max_tokens=200).strip()


def select_agents_for_question(
    question: str,
    members: list[dict],
    model_id: str,
    custom_routing_prompt: str | None = None,
) -> dict:
    """Use LLM to decide which agents should answer this question.

    Args:
        question: The user's question.
        members: List of dicts with agent_id, name, role, specialization.
        model_id: LLM model to use for routing.
        custom_routing_prompt: Optional override for the routing prompt template.

    Returns:
        Dict with "agent_ids" (list[int]) and "reasoning" (str).
    """
    agent_list = "\n".join(
        f'- Agent #{m["agent_id"]} "{m["name"]}" -- Specialite: {m.get("specialization") or "non definie"}'
        for m in members
        if m["role"] == "member"
    )

    template = custom_routing_prompt or DEFAULT_ROUTING_PROMPT
    prompt = template.format(agent_list=agent_list) + f"\n\nQuestion de l'utilisateur: {question}"

    try:
        result = _call_llm_for_routing(prompt, model_id)
        # Cap at 3 agents
        result["agent_ids"] = result["agent_ids"][:3]
        # Filter to valid member IDs only
        valid_ids = {m["agent_id"] for m in members if m["role"] == "member"}
        result["agent_ids"] = [aid for aid in result["agent_ids"] if aid in valid_ids]
        return result
    except Exception as e:
        logger.warning(f"Routing LLM failed, returning empty: {e}")
        return {"agent_ids": [], "reasoning": f"Fallback: routing error ({e})"}


def execute_agent(
    agent_id: int,
    question: str,
    user_id: int,
    db,
    selected_doc_ids: list[int],
    history: list,
    model_id: str,
    company_id: int | None,
    use_rag: bool = True,
    use_graph: bool = True,
) -> dict:
    """Execute a single agent's get_answer call. Returns contribution dict."""
    prompt = f"Sachant le contexte et la discussion en cours, reponds a cette question : {question}"
    try:
        result = get_answer(
            prompt, user_id, db,
            selected_doc_ids=selected_doc_ids,
            agent_id=agent_id,
            history=history,
            model_id=model_id,
            company_id=company_id,
            use_rag=use_rag,
            use_graph=use_graph,
        )
        answer = result["answer"] if isinstance(result, dict) else result
        sources = result.get("sources", []) if isinstance(result, dict) else []
        return {"agent_id": agent_id, "content": answer, "sources": sources, "status": "ok"}
    except Exception as e:
        logger.error(f"Agent {agent_id} execution failed: {e}")
        return {"agent_id": agent_id, "content": "", "sources": [], "status": "error", "error": str(e)}


def _execute_agent_in_thread(
    config: dict,
    question: str,
    user_id: int,
    selected_doc_ids: list[int],
    history: list,
    company_id_for_tenant: int | None,
    use_rag: bool,
    use_graph: bool,
) -> dict:
    """Run a single agent in its own thread with a dedicated DB session."""
    from database import SessionLocal, set_current_company_id

    # Propagate tenant context to this thread
    if company_id_for_tenant is not None:
        set_current_company_id(company_id_for_tenant)

    db = SessionLocal()
    try:
        result = execute_agent(
            agent_id=config["agent_id"],
            question=question,
            user_id=user_id,
            db=db,
            selected_doc_ids=selected_doc_ids,
            history=history,
            model_id=config["model_id"],
            company_id=config.get("company_id"),
            use_rag=use_rag,
            use_graph=use_graph,
        )
        result["agent_name"] = config["name"]
        result["specialization"] = config.get("specialization", "")
        return result
    finally:
        db.close()


def execute_agents_parallel(
    agent_configs: list[dict],
    question: str,
    user_id: int,
    db,
    selected_doc_ids: list[int],
    history: list,
    use_rag: bool = True,
    use_graph: bool = True,
) -> list[dict]:
    """Execute multiple agents in parallel using threads.

    Each thread gets its own DB session to avoid SQLAlchemy thread-safety issues.
    Falls back to sequential execution if only one agent is selected.

    Each agent_config is: {"agent_id": int, "model_id": str, "company_id": int|None,
                           "name": str, "specialization": str}
    Returns list of contribution dicts in the same order as agent_configs.
    """
    if len(agent_configs) <= 1:
        # No point spawning threads for a single agent
        contributions = []
        for config in agent_configs:
            result = execute_agent(
                agent_id=config["agent_id"],
                question=question,
                user_id=user_id,
                db=db,
                selected_doc_ids=selected_doc_ids,
                history=history,
                model_id=config["model_id"],
                company_id=config.get("company_id"),
                use_rag=use_rag,
                use_graph=use_graph,
            )
            result["agent_name"] = config["name"]
            result["specialization"] = config.get("specialization", "")
            contributions.append(result)
        return contributions

    # Capture current tenant context to propagate to threads
    from database import _current_company_id
    tenant_company_id = _current_company_id.get()

    contributions = [None] * len(agent_configs)
    max_workers = min(len(agent_configs), 3)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {}
        for i, config in enumerate(agent_configs):
            future = executor.submit(
                _execute_agent_in_thread,
                config=config,
                question=question,
                user_id=user_id,
                selected_doc_ids=selected_doc_ids,
                history=history,
                company_id_for_tenant=tenant_company_id,
                use_rag=use_rag,
                use_graph=use_graph,
            )
            future_to_index[future] = i

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                contributions[idx] = future.result()
            except Exception as e:
                logger.error(f"Agent thread {idx} failed: {e}")
                config = agent_configs[idx]
                contributions[idx] = {
                    "agent_id": config["agent_id"],
                    "agent_name": config["name"],
                    "specialization": config.get("specialization", ""),
                    "content": "",
                    "sources": [],
                    "status": "error",
                    "error": str(e),
                }

    return contributions


def synthesize_contributions(
    question: str,
    contributions: list[dict],
    team_name: str,
    team_contexte: str,
    leader_model_id: str,
) -> str:
    """Use leader LLM to synthesize agent contributions into a unified response."""
    successful = [c for c in contributions if c["status"] == "ok" and c["content"]]
    if not successful:
        return ""

    contributions_text = "\n\n".join(
        f'[Agent "{c["agent_name"]}" -- {c.get("specialization", "general")}]:\n{c["content"]}'
        for c in successful
    )

    prompt = DEFAULT_SYNTHESIS_PROMPT.format(
        team_name=team_name,
        team_contexte=team_contexte or "",
        contributions_text=contributions_text,
    ) + f"\n\nQuestion originale: {question}"

    try:
        return generate_text(prompt, model_name=leader_model_id, temperature=0.3, max_tokens=4000).strip()
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        # Fallback: concatenate contributions
        return "\n\n---\n\n".join(
            f"**{c['agent_name']}**: {c['content']}" for c in successful
        )


def suggest_specialization(
    agent_name: str,
    agent_contexte: str,
    agent_biographie: str,
    document_names: list[str],
) -> str:
    """Auto-detect agent specialization from its context and documents."""
    prompt = SPECIALIZATION_PROMPT.format(
        name=agent_name,
        contexte=(agent_contexte or "")[:500],
        biographie=(agent_biographie or "")[:200],
        documents=", ".join(document_names[:10]) if document_names else "Aucun",
    )
    try:
        return _call_llm_for_specialization(prompt)
    except Exception as e:
        logger.error(f"Specialization suggestion failed: {e}")
        return ""


def orchestrate_team_question(
    question: str,
    team,
    members_with_agents: list[dict],
    user_id: int,
    db,
    selected_doc_ids: list[int],
    history: list,
    use_rag: bool = True,
    use_graph: bool = True,
) -> dict:
    """Full orchestration pipeline: route -> execute -> synthesize.

    Args:
        question: User's question.
        team: Team SQLAlchemy object.
        members_with_agents: List of dicts with keys:
            agent_id, name, role, specialization, model_id, company_id, agent (SQLAlchemy obj)
        user_id: Authenticated user ID.
        db: DB session.
        selected_doc_ids: Selected document IDs.
        history: Conversation history.
        use_rag: Whether to use RAG.
        use_graph: Whether to use graph.

    Returns:
        Dict with: answer, contributions, routing_reasoning, sources
    """
    leader_info = next((m for m in members_with_agents if m["role"] == "leader"), None)
    if not leader_info:
        raise ValueError("Team has no leader")

    leader_model_id = leader_info["model_id"]

    # Phase 1: Routing
    routing_result = select_agents_for_question(
        question=question,
        members=members_with_agents,
        model_id=leader_model_id,
        custom_routing_prompt=team.orchestration_prompt,
    )

    selected_ids = routing_result["agent_ids"]

    # If no agents selected, leader responds alone
    if not selected_ids:
        leader_result = execute_agent(
            agent_id=leader_info["agent_id"],
            question=question,
            user_id=user_id,
            db=db,
            selected_doc_ids=selected_doc_ids,
            history=history,
            model_id=leader_model_id,
            company_id=leader_info.get("company_id"),
            use_rag=use_rag,
            use_graph=use_graph,
        )
        return {
            "answer": leader_result["content"],
            "contributions": [],
            "routing_reasoning": routing_result["reasoning"],
            "sources": leader_result.get("sources", []),
        }

    # Phase 2: Parallel execution
    agent_configs = [
        m for m in members_with_agents if m["agent_id"] in selected_ids
    ]
    contributions = execute_agents_parallel(
        agent_configs=agent_configs,
        question=question,
        user_id=user_id,
        db=db,
        selected_doc_ids=selected_doc_ids,
        history=history,
        use_rag=use_rag,
        use_graph=use_graph,
    )

    # If all agents failed, leader responds alone
    successful = [c for c in contributions if c["status"] == "ok" and c["content"]]
    if not successful:
        leader_result = execute_agent(
            agent_id=leader_info["agent_id"],
            question=question,
            user_id=user_id,
            db=db,
            selected_doc_ids=selected_doc_ids,
            history=history,
            model_id=leader_model_id,
            company_id=leader_info.get("company_id"),
            use_rag=use_rag,
            use_graph=use_graph,
        )
        return {
            "answer": leader_result["content"],
            "contributions": contributions,
            "routing_reasoning": routing_result["reasoning"],
            "sources": leader_result.get("sources", []),
        }

    # Phase 3: Synthesis
    answer = synthesize_contributions(
        question=question,
        contributions=contributions,
        team_name=team.name,
        team_contexte=team.contexte or "",
        leader_model_id=leader_model_id,
    )

    all_sources = []
    for c in successful:
        all_sources.extend(c.get("sources", []))

    return {
        "answer": answer,
        "contributions": [
            {
                "agent_id": c["agent_id"],
                "agent_name": c["agent_name"],
                "specialization": c.get("specialization", ""),
                "content": c["content"],
            }
            for c in contributions
        ],
        "routing_reasoning": routing_result["reasoning"],
        "sources": all_sources,
    }
