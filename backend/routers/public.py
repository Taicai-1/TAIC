"""Public endpoints: health-nltk, public agent get/chat (no auth required)."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db, Agent, QuestionnaireAnswer, QuestionnaireResponse
from helpers.agent_helpers import resolve_model_id
from helpers.rate_limiting import _check_rate_limit
from rag_engine import get_answer
from schemas.public import PublicChatRequest
from schemas.questionnaires import PublicSubmitRequest

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


##### Public questionnaire endpoints (token-based, no auth) #####


def _validate_answer_value(question, value):
    """Validate a submitted value against its question type.

    Returns the string to store, or None when the (optional) question was
    left unanswered. Raises HTTPException(422) on invalid values.
    """
    if value is None or value == "" or value == []:
        return None
    options = json.loads(question.options) if question.options else None

    if question.question_type == "open":
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail=f"Question {question.id}: texte attendu")
        return value[:10000]

    if question.question_type == "single_choice":
        if not isinstance(value, str) or (isinstance(options, list) and value not in options):
            raise HTTPException(status_code=422, detail=f"Question {question.id}: choix invalide")
        return value

    if question.question_type == "multiple_choice":
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(v, str) for v in value)
        ):
            raise HTTPException(
                status_code=422, detail=f"Question {question.id}: liste de choix attendue"
            )
        if isinstance(options, list) and any(v not in options for v in value):
            raise HTTPException(status_code=422, detail=f"Question {question.id}: choix invalide")
        value = list(dict.fromkeys(value))
        return json.dumps(value)

    if question.question_type == "rating":
        if isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"Question {question.id}: note attendue")
        try:
            rating = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"Question {question.id}: note attendue")
        bounds = options if isinstance(options, dict) else {"min": 1, "max": 5}
        if not (bounds.get("min", 1) <= rating <= bounds.get("max", 5)):
            raise HTTPException(
                status_code=422, detail=f"Question {question.id}: note hors limites"
            )
        return str(rating)

    return None


@router.get("/questionnaire/{token}")
async def public_get_questionnaire(token: str, request: Request, db: Session = Depends(get_db)):
    """Return the questionnaire form data for a respondent token. Rate-limited by IP."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    response = (
        db.query(QuestionnaireResponse).filter(QuestionnaireResponse.token == token).first()
    )
    if not response:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    if response.status == "completed":
        return {"completed": True}

    questionnaire = response.questionnaire
    return {
        "completed": False,
        "title": questionnaire.title,
        "description": questionnaire.description,
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "options": json.loads(q.options) if q.options else None,
                "position": q.position,
                "required": q.required,
            }
            for q in questionnaire.questions
        ],
    }


@router.post("/questionnaire/{token}/submit")
async def public_submit_questionnaire(
    token: str, body: PublicSubmitRequest, request: Request, db: Session = Depends(get_db)
):
    """Single-shot submit of all answers. Rate-limited by IP."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    response = (
        db.query(QuestionnaireResponse)
        .filter(QuestionnaireResponse.token == token)
        .with_for_update()
        .first()
    )
    if not response:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    if response.status == "completed":
        raise HTTPException(status_code=409, detail="Ce questionnaire a déjà été complété.")

    questions = {q.id: q for q in response.questionnaire.questions}

    provided = {}
    for item in body.answers:
        if item.question_id not in questions:
            raise HTTPException(
                status_code=422, detail=f"Question inconnue : {item.question_id}"
            )
        provided[item.question_id] = item.value

    missing = [
        q.id
        for q in questions.values()
        if q.required and provided.get(q.id) in (None, "", [])
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"message": "Questions obligatoires sans réponse", "missing_question_ids": missing},
        )

    for question_id, value in provided.items():
        answer_text = _validate_answer_value(questions[question_id], value)
        if answer_text is None:
            continue
        db.add(
            QuestionnaireAnswer(
                response_id=response.id,
                question_id=question_id,
                company_id=response.company_id,
                answer_text=answer_text,
            )
        )

    if body.respondent_name:
        response.respondent_name = body.respondent_name.strip()[:255]
    response.status = "completed"
    response.completed_at = datetime.utcnow()
    db.commit()
    return {"success": True}
