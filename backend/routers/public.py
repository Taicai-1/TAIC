"""Public endpoints: health-nltk, public agent get/chat (no auth required)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db, Agent
from helpers.agent_helpers import resolve_model_id
from helpers.rate_limiting import _check_rate_limit
from rag_engine import get_answer
from schemas.public import PublicChatRequest

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
        answer = get_answer(
            req.message,
            None,
            db,
            agent_id=agent_id,
            history=history,
            model_id=public_model_id,
            company_id=agent.company_id,
        )
    except Exception as e:
        logger.exception(f"Error generating public chat answer for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Error generating answer")

    return {"answer": answer}
