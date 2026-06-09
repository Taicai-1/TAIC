"""Questionnaire endpoints: question CRUD, invitations, responses, PDF export, RAG integration."""

import json
import logging
import secrets
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from auth import verify_token
from database import get_db, Agent, Document, DocumentChunk, QuestionnaireQuestion, QuestionnaireResponse, QuestionnaireAnswer, Company
from helpers.tenant import _get_caller_company_id
from schemas.questionnaires import (
    QuestionCreate,
    QuestionUpdate,
    QuestionOut,
    ReorderRequest,
    InviteRequest,
    ResponseSummary,
    ResponseDetail,
    AnswerOut,
    ExportRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_questionnaire_agent(agent_id: int, user_id: int, db: Session) -> Agent:
    """Verify the agent exists, belongs to the caller's company, and has type 'questionnaire'."""
    company_id = _get_caller_company_id(user_id, db)

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check tenant isolation
    if agent.company_id != company_id:
        raise HTTPException(status_code=403, detail="Access denied to this agent")

    # Verify agent type
    if agent.type != "questionnaire":
        raise HTTPException(status_code=400, detail="Agent is not a questionnaire type")

    return agent


##### Question CRUD #####


@router.get("/api/agents/{agent_id}/questions", response_model=List[QuestionOut])
async def list_questions(agent_id: int, user: dict = Depends(verify_token), db: Session = Depends(get_db)):
    """List all questions for a questionnaire agent, ordered by position."""
    _get_questionnaire_agent(agent_id, user["user_id"], db)

    questions = (
        db.query(QuestionnaireQuestion)
        .filter(QuestionnaireQuestion.agent_id == agent_id)
        .order_by(QuestionnaireQuestion.position)
        .all()
    )

    return questions


@router.post("/api/agents/{agent_id}/questions", response_model=QuestionOut)
async def create_question(
    agent_id: int,
    question: QuestionCreate,
    user: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Create a new question for a questionnaire agent."""
    agent = _get_questionnaire_agent(agent_id, user["user_id"], db)

    # Auto-assign position if 0
    position = question.position
    if position == 0:
        max_pos = (
            db.query(QuestionnaireQuestion.position)
            .filter(QuestionnaireQuestion.agent_id == agent_id)
            .order_by(QuestionnaireQuestion.position.desc())
            .first()
        )
        position = (max_pos[0] + 1) if max_pos else 1

    new_question = QuestionnaireQuestion(
        agent_id=agent_id,
        company_id=agent.company_id,
        question_text=question.question_text,
        question_type=question.question_type,
        options=question.options,
        position=position,
        required=question.required,
    )

    db.add(new_question)
    db.commit()
    db.refresh(new_question)

    logger.info(f"Question created: {new_question.id} for agent {agent_id}")
    return new_question


@router.patch("/api/agents/{agent_id}/questions/{question_id}", response_model=QuestionOut)
async def update_question(
    agent_id: int,
    question_id: int,
    question_update: QuestionUpdate,
    user: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Update a question."""
    _get_questionnaire_agent(agent_id, user["user_id"], db)

    question = (
        db.query(QuestionnaireQuestion)
        .filter(QuestionnaireQuestion.id == question_id, QuestionnaireQuestion.agent_id == agent_id)
        .first()
    )

    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    # Update fields
    if question_update.question_text is not None:
        question.question_text = question_update.question_text
    if question_update.question_type is not None:
        question.question_type = question_update.question_type
    if question_update.options is not None:
        question.options = question_update.options
    if question_update.position is not None:
        question.position = question_update.position
    if question_update.required is not None:
        question.required = question_update.required

    db.commit()
    db.refresh(question)

    logger.info(f"Question updated: {question_id}")
    return question


@router.delete("/api/agents/{agent_id}/questions/{question_id}")
async def delete_question(
    agent_id: int, question_id: int, user: dict = Depends(verify_token), db: Session = Depends(get_db)
):
    """Delete a question."""
    _get_questionnaire_agent(agent_id, user["user_id"], db)

    question = (
        db.query(QuestionnaireQuestion)
        .filter(QuestionnaireQuestion.id == question_id, QuestionnaireQuestion.agent_id == agent_id)
        .first()
    )

    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    db.delete(question)
    db.commit()

    logger.info(f"Question deleted: {question_id}")
    return {"message": "Question deleted"}


@router.put("/api/agents/{agent_id}/questions/reorder")
async def reorder_questions(
    agent_id: int, reorder: ReorderRequest, user: dict = Depends(verify_token), db: Session = Depends(get_db)
):
    """Reorder questions by providing a list of question IDs in the desired order."""
    _get_questionnaire_agent(agent_id, user["user_id"], db)

    # Verify all question IDs belong to this agent
    questions = (
        db.query(QuestionnaireQuestion)
        .filter(QuestionnaireQuestion.agent_id == agent_id, QuestionnaireQuestion.id.in_(reorder.question_ids))
        .all()
    )

    if len(questions) != len(reorder.question_ids):
        raise HTTPException(status_code=400, detail="Some question IDs are invalid")

    # Update positions
    for idx, question_id in enumerate(reorder.question_ids):
        question = next(q for q in questions if q.id == question_id)
        question.position = idx + 1

    db.commit()

    logger.info(f"Questions reordered for agent {agent_id}")
    return {"message": "Questions reordered"}


##### Invitations #####


@router.post("/api/agents/{agent_id}/invite")
async def invite_respondents(
    agent_id: int, invite: InviteRequest, user: dict = Depends(verify_token), db: Session = Depends(get_db)
):
    """Send questionnaire invitations to a list of emails."""
    import os
    from email_service import send_questionnaire_invitation_email

    agent = _get_questionnaire_agent(agent_id, user["user_id"], db)

    # Get company name
    company = db.query(Company).filter(Company.id == agent.company_id).first()
    company_name = company.name if company else "TAIC Companion"

    # Get frontend URL from env
    frontend_url = os.getenv("NEXT_PUBLIC_FRONTEND_URL") or os.getenv("FRONTEND_URL") or "http://localhost:3000"

    invited_count = 0
    skipped_count = 0

    # Prepare names list
    names = invite.names if invite.names else [None] * len(invite.emails)

    for idx, email in enumerate(invite.emails):
        respondent_name = names[idx] if idx < len(names) else None

        # Check if already invited
        existing = (
            db.query(QuestionnaireResponse)
            .filter(QuestionnaireResponse.agent_id == agent_id, QuestionnaireResponse.respondent_email == email)
            .first()
        )

        if existing:
            logger.info(f"Skipping already invited email: {email}")
            skipped_count += 1
            continue

        # Generate token
        token = secrets.token_urlsafe(48)

        # Create response record
        new_response = QuestionnaireResponse(
            agent_id=agent_id,
            company_id=agent.company_id,
            respondent_email=email,
            respondent_name=respondent_name,
            token=token,
            status="pending",
        )

        db.add(new_response)
        db.flush()  # Get the ID

        # Send email
        questionnaire_url = f"{frontend_url}/questionnaire/{token}"
        try:
            send_questionnaire_invitation_email(
                to_email=email,
                questionnaire_name=agent.name,
                company_name=company_name,
                respondent_name=respondent_name or "",
                questionnaire_url=questionnaire_url,
            )
            invited_count += 1
            logger.info(f"Invitation sent to {email}")
        except Exception as e:
            logger.error(f"Failed to send invitation to {email}: {e}")
            # Continue with other emails even if one fails

    db.commit()

    return {
        "message": f"Invitations sent: {invited_count}, skipped: {skipped_count}",
        "invited": invited_count,
        "skipped": skipped_count,
    }
