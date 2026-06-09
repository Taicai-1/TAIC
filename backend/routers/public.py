"""Public endpoints: health-nltk, public agent get/chat (no auth required)."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db, Agent, QuestionnaireQuestion, QuestionnaireResponse, QuestionnaireAnswer
from helpers.agent_helpers import resolve_model_id
from helpers.rate_limiting import _check_rate_limit
from rag_engine import get_answer
from schemas.public import PublicChatRequest
from schemas.questionnaires import PublicAnswerSubmit

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health-nltk")
async def health_nltk():
    """Health check for NLTK and chunking logic"""
    from file_loader import chunk_text

    test_text = "Hello world. This is a test.\n\nNew paragraph."
    try:
        chunks = chunk_text(test_text)
        return {"status": "ok", "chunks": chunks, "n_chunks": len(chunks)}
    except Exception as e:
        logger.error(f"Health check NLTK failed: {e}")
        return {"status": "error", "detail": "NLTK health check failed"}


##### Public agents endpoints (no auth) #####


@router.get("/public/agents/{agent_id}")
async def public_get_agent(agent_id: int, request: Request, db: Session = Depends(get_db)):
    """Return public agent profile if statut == 'public'"""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.statut == "public").first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found or not public")
    # Only expose non-sensitive fields
    return {
        "id": agent.id,
        "name": agent.name,
        "contexte": agent.contexte,
        "biographie": agent.biographie,
        "profile_photo": agent.profile_photo,
        "created_at": agent.created_at.isoformat() if hasattr(agent, "created_at") else None,
        "slug": getattr(agent, "slug", None),
    }


@router.post("/public/agents/{agent_id}/chat")
async def public_agent_chat(agent_id: int, req: PublicChatRequest, request: Request, db: Session = Depends(get_db)):
    """Public chat endpoint for a public agent. Rate-limited by IP."""
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.statut == "public").first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found or not public")

    # Rate limiting (distributed via Redis)
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again in 1 hour.")

    # Build history for the model if provided
    history = req.history or []
    # Append the current user message as last user message in history
    history.append({"role": "user", "content": req.message})

    # Resolve model_id from agent type (mistral for conversationnel, perplexity for recherche_live)
    public_model_id = agent.finetuned_model_id or resolve_model_id(agent)

    try:
        result = get_answer(
            req.message,
            None,
            db,
            agent_id=agent_id,
            history=history,
            model_id=public_model_id,
            company_id=agent.company_id,
        )
        answer = result["answer"] if isinstance(result, dict) else result
    except Exception as e:
        logger.exception(f"Error generating public chat answer for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Error generating answer")

    return {"answer": answer}


##### Public questionnaire endpoints #####


@router.get("/questionnaire/{token}")
async def get_questionnaire(token: str, request: Request, db: Session = Depends(get_db)):
    """Get questionnaire data by token. Public endpoint, rate-limited by IP."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    # Find response by token
    response = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.token == token).first()
    if not response:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    # Check if already completed
    if response.status == "completed":
        return {
            "completed": True,
            "message": "Ce questionnaire a déjà été complété. Merci pour votre participation.",
        }

    # Get agent
    agent = db.query(Agent).filter(Agent.id == response.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get questions
    questions = (
        db.query(QuestionnaireQuestion)
        .filter(QuestionnaireQuestion.agent_id == response.agent_id)
        .order_by(QuestionnaireQuestion.position)
        .all()
    )

    # Get already answered question IDs
    answered_ids = (
        db.query(QuestionnaireAnswer.question_id)
        .filter(QuestionnaireAnswer.response_id == response.id)
        .all()
    )
    answered_question_ids = [aid[0] for aid in answered_ids]

    return {
        "completed": False,
        "agent_name": agent.name,
        "welcome_message": agent.welcome_message,
        "closing_message": agent.closing_message,
        "respondent_name": response.respondent_name,
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "options": q.options,
                "position": q.position,
                "required": q.required,
            }
            for q in questions
        ],
        "answered_question_ids": answered_question_ids,
    }


@router.post("/questionnaire/{token}/answer")
async def submit_answer(
    token: str, answer_data: PublicAnswerSubmit, request: Request, db: Session = Depends(get_db)
):
    """Submit an answer to a questionnaire question. Public endpoint, rate-limited by IP."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    # Find response by token
    response = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.token == token).first()
    if not response:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    if response.status == "completed":
        raise HTTPException(status_code=400, detail="Questionnaire already completed")

    # Verify question belongs to this agent
    question = (
        db.query(QuestionnaireQuestion)
        .filter(
            QuestionnaireQuestion.id == answer_data.question_id,
            QuestionnaireQuestion.agent_id == response.agent_id,
        )
        .first()
    )

    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    # Check if answer already exists
    existing_answer = (
        db.query(QuestionnaireAnswer)
        .filter(
            QuestionnaireAnswer.response_id == response.id,
            QuestionnaireAnswer.question_id == answer_data.question_id,
        )
        .first()
    )

    if existing_answer:
        # Update existing answer
        existing_answer.answer_text = answer_data.answer_text
        existing_answer.answered_at = datetime.utcnow()
    else:
        # Create new answer
        new_answer = QuestionnaireAnswer(
            response_id=response.id,
            question_id=answer_data.question_id,
            company_id=response.company_id,
            answer_text=answer_data.answer_text,
        )
        db.add(new_answer)

    # If this is the first answer, mark as in_progress
    if response.status == "pending":
        response.status = "in_progress"
        response.started_at = datetime.utcnow()

    db.commit()

    logger.info(f"Answer submitted for question {answer_data.question_id} in response {response.id}")
    return {"message": "Answer saved"}


@router.post("/questionnaire/{token}/complete")
async def complete_questionnaire(token: str, request: Request, db: Session = Depends(get_db)):
    """Mark a questionnaire response as completed and generate a closing message. Public endpoint, rate-limited by IP."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    # Find response by token
    response = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.token == token).first()
    if not response:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    if response.status == "completed":
        raise HTTPException(status_code=400, detail="Questionnaire already completed")

    # Mark as completed
    response.status = "completed"
    response.completed_at = datetime.utcnow()
    db.commit()

    # Generate closing message using Mistral
    agent = db.query(Agent).filter(Agent.id == response.agent_id).first()
    closing_message = agent.closing_message if agent and agent.closing_message else "Merci pour vos réponses."

    try:
        from mistral_client import generate_text

        prompt = f"""Tu es un assistant courtois. Génère un court message de remerciement en français (2-3 phrases maximum) pour quelqu'un qui vient de compléter un questionnaire.

Le message de base est : "{closing_message}"

Reformule ce message de manière personnelle et chaleureuse, sans utiliser de markdown."""

        generated_message = generate_text(prompt, temperature=0.8, max_tokens=200)
        logger.info(f"Generated closing message for response {response.id}")
        return {"message": generated_message.strip()}
    except Exception as e:
        logger.error(f"Failed to generate closing message: {e}")
        # Fallback to the agent's closing message
        return {"message": closing_message}
