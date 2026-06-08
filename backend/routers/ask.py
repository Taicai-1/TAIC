"""Ask endpoint: POST /ask - main Q&A endpoint."""

import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, Agent, Message, Team, TeamMember
from helpers.agent_helpers import resolve_model_id, _user_can_access_agent
from helpers.conversation_helpers import verify_conversation_owner
from helpers.rate_limiting import _check_api_rate_limit, _API_ASK_LIMIT
from rag_engine import get_answer, get_answer_stream
from utils import event_tracker
from validation import QuestionRequestValidated
from agent_executor import AgentExecutor
from google_credentials import get_google_credentials

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ask")
async def ask_question(
    request: QuestionRequestValidated, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Ask question to RAG system (toujours avec mémoire et bon modèle)"""
    if not _check_api_rate_limit(user_id, "ask", _API_ASK_LIMIT):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    start_time = time.time()
    try:
        logger.info(f"Processing question from user {user_id}: {request.question}")
        logger.info(f"Selected documents: {request.selected_documents}")

        # Récupérer l'historique complet de la conversation si conversation_id fourni
        history = []
        if hasattr(request, "conversation_id") and request.conversation_id:
            # Security: verify the user owns this conversation before loading messages
            verify_conversation_owner(request.conversation_id, user_id, db)
            msgs = (
                db.query(Message)
                .filter(Message.conversation_id == request.conversation_id)
                .order_by(Message.timestamp.asc())
                .all()
            )
            history = [{"role": m.role, "content": m.content} for m in msgs]
        elif hasattr(request, "history") and request.history:
            # fallback: si le frontend envoie déjà l'historique
            history = request.history

        answer = None
        sources = []
        graph_data = None
        agent = None
        model_id = None
        # Si agent_id fourni, comportement agent classique
        if request.agent_id:
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

                answer_text = result["answer"] or ""
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
        # Si team_id fourni, orchestration via leader + sous-agents
        elif request.team_id:
            from orchestrator import orchestrate_team_question

            team = db.query(Team).filter(Team.id == request.team_id).first()
            if not team:
                raise HTTPException(status_code=404, detail="Team not found")
            if team.user_id != int(user_id):
                raise HTTPException(status_code=403, detail="Access denied to this team")

            # Load members with agent data
            members_db = db.query(TeamMember).filter(TeamMember.team_id == team.id).order_by(TeamMember.position).all()
            agent_ids = [m.agent_id for m in members_db]
            agents_db = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
            agent_lookup = {a.id: a for a in agents_db}

            members_with_agents = []
            for m in members_db:
                a = agent_lookup.get(m.agent_id)
                if not a:
                    continue
                members_with_agents.append({
                    "agent_id": m.agent_id,
                    "name": a.name,
                    "role": m.role,
                    "specialization": m.specialization or m.auto_specialization or "",
                    "model_id": a.finetuned_model_id or resolve_model_id(a),
                    "company_id": a.company_id,
                    "agent": a,
                })

            result = orchestrate_team_question(
                question=request.question,
                team=team,
                members_with_agents=members_with_agents,
                user_id=int(user_id),
                db=db,
                selected_doc_ids=request.selected_documents,
                history=history,
                use_rag=request.use_rag,
                use_graph=request.use_graph,
            )

            answer = result["answer"]
            sources = result.get("sources", [])
            graph_data = None
            agent = agent_lookup.get(members_with_agents[0]["agent_id"]) if members_with_agents else None

        if answer is None:
            raise HTTPException(status_code=400, detail="Aucun agent ou équipe valide fourni.")

        response_time = time.time() - start_time
        logger.info(f"Question answered for user {user_id} in {response_time:.2f}s")
        event_tracker.track_question_asked(int(user_id), request.question, response_time)
        return {"answer": answer, "sources": sources, "graph_data": graph_data, "action_proposal": None}
    except Exception as e:
        logger.error(f"Error answering question for user {user_id}: {e}", exc_info=True)
        return {"answer": "Désolé, une erreur s'est produite lors du traitement de votre question. Veuillez réessayer."}


@router.post("/ask-stream")
async def ask_question_stream(
    request: QuestionRequestValidated, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Streaming version of /ask. Returns Server-Sent Events with token-by-token response."""
    from streaming_response import sse_event

    if not _check_api_rate_limit(user_id, "ask", _API_ASK_LIMIT):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    # Retrieve conversation history
    history = []
    if hasattr(request, "conversation_id") and request.conversation_id:
        # Security: verify the user owns this conversation before loading messages
        verify_conversation_owner(request.conversation_id, user_id, db)
        msgs = (
            db.query(Message)
            .filter(Message.conversation_id == request.conversation_id)
            .order_by(Message.timestamp.asc())
            .all()
        )
        history = [{"role": m.role, "content": m.content} for m in msgs]
    elif hasattr(request, "history") and request.history:
        history = request.history

    def event_generator():
        try:
            agent = None
            model_id = None

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
            elif request.team_id:
                from orchestrator import (
                    select_agents_for_question,
                    execute_agents_parallel,
                    DEFAULT_SYNTHESIS_PROMPT,
                )
                from openai_client import get_chat_response_stream

                team = db.query(Team).filter(Team.id == request.team_id).first()
                if not team:
                    yield sse_event("error", {"message": "Team not found", "code": "not_found"})
                    return
                if team.user_id != int(user_id):
                    yield sse_event("error", {"message": "Access denied", "code": "forbidden"})
                    return

                members_db = db.query(TeamMember).filter(TeamMember.team_id == team.id).order_by(TeamMember.position).all()
                agent_ids = [m.agent_id for m in members_db]
                agents_db = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
                agent_lookup = {a.id: a for a in agents_db}

                members_with_agents = []
                for m in members_db:
                    a = agent_lookup.get(m.agent_id)
                    if not a:
                        continue
                    members_with_agents.append({
                        "agent_id": m.agent_id,
                        "name": a.name,
                        "role": m.role,
                        "specialization": m.specialization or m.auto_specialization or "",
                        "model_id": a.finetuned_model_id or resolve_model_id(a),
                        "company_id": a.company_id,
                    })

                leader_info = next((m for m in members_with_agents if m["role"] == "leader"), None)
                if not leader_info:
                    yield sse_event("error", {"message": "No leader in team", "code": "bad_config"})
                    return

                # Phase 1: Routing (buffered)
                routing_result = select_agents_for_question(
                    question=request.question,
                    members=members_with_agents,
                    model_id=leader_info["model_id"],
                    custom_routing_prompt=team.orchestration_prompt,
                )
                selected_ids = routing_result["agent_ids"]

                if not selected_ids:
                    # Leader responds alone, stream directly
                    prompt = f"Sachant le contexte et la discussion en cours, reponds a cette question : {request.question}"
                    yield from get_answer_stream(
                        prompt, int(user_id), db,
                        selected_doc_ids=request.selected_documents,
                        agent_id=leader_info["agent_id"],
                        history=history,
                        model_id=leader_info["model_id"],
                        company_id=leader_info.get("company_id"),
                        use_rag=request.use_rag,
                        use_graph=request.use_graph,
                    )
                    return

                # Emit routing event
                routed_agents = [
                    {"id": m["agent_id"], "name": m["name"], "specialization": m.get("specialization", "")}
                    for m in members_with_agents if m["agent_id"] in selected_ids
                ]
                yield sse_event("routing", {"agents": routed_agents})

                # Phase 2: Execution (buffered)
                agent_configs = [m for m in members_with_agents if m["agent_id"] in selected_ids]
                contributions = execute_agents_parallel(
                    agent_configs=agent_configs,
                    question=request.question,
                    user_id=int(user_id),
                    db=db,
                    selected_doc_ids=request.selected_documents,
                    history=history,
                    use_rag=request.use_rag,
                    use_graph=request.use_graph,
                )

                # Emit contribution events
                for c in contributions:
                    yield sse_event("contribution", {
                        "agent_id": c["agent_id"],
                        "agent_name": c.get("agent_name", ""),
                        "specialization": c.get("specialization", ""),
                        "content": c["content"],
                        "status": c["status"],
                    })

                # Phase 3: Synthesis (streamed)
                successful = [c for c in contributions if c["status"] == "ok" and c["content"]]
                if not successful:
                    # All failed, leader responds alone
                    prompt = f"Sachant le contexte et la discussion en cours, reponds a cette question : {request.question}"
                    yield from get_answer_stream(
                        prompt, int(user_id), db,
                        selected_doc_ids=request.selected_documents,
                        agent_id=leader_info["agent_id"],
                        history=history,
                        model_id=leader_info["model_id"],
                        company_id=leader_info.get("company_id"),
                        use_rag=request.use_rag,
                        use_graph=request.use_graph,
                    )
                    return

                contributions_text = "\n\n".join(
                    f'[Agent "{c["agent_name"]}" -- {c.get("specialization", "")}]:\n{c["content"]}'
                    for c in successful
                )
                synthesis_prompt = DEFAULT_SYNTHESIS_PROMPT.format(
                    team_name=team.name,
                    team_contexte=team.contexte or "",
                    contributions_text=contributions_text,
                ) + f"\n\nQuestion originale: {request.question}"

                messages = [{"role": "user", "content": synthesis_prompt}]
                full_text = ""
                for chunk in get_chat_response_stream(messages, model_id=leader_info["model_id"]):
                    full_text += chunk
                    yield sse_event("token", {"t": chunk})

                yield sse_event("done", {
                    "full_text": full_text,
                    "contributions": [
                        {"agent_id": c["agent_id"], "agent_name": c.get("agent_name", ""), "specialization": c.get("specialization", ""), "content": c["content"]}
                        for c in contributions
                    ],
                    "sources": [],
                    "graph_data": None,
                })
            else:
                yield sse_event("error", {"message": "Aucun agent ou équipe valide fourni.", "code": "bad_request"})

        except Exception as e:
            logger.error(f"Error in ask-stream: {e}", exc_info=True)
            yield sse_event("error", {"message": str(e), "code": "llm_error"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
