"""Automations endpoints: questionnaire CRUD, invitations, responses, RAG export."""

import json
import logging
import os
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from auth import verify_token
from database import (
    Agent,
    Company,
    Questionnaire,
    QuestionnaireAnswer,
    QuestionnaireQuestion,
    QuestionnaireResponse,
    SessionLocal,
    get_db,
)
from email_service import send_questionnaire_invitation_email
from permissions import require_role
from schemas.questionnaires import (
    ExportRequest,
    InviteRequest,
    QuestionnaireCreate,
    QuestionnaireUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Consumed by the export endpoint (responses can only be exported to these agent types)
EXPORTABLE_AGENT_TYPES = ("conversationnel", "actionnable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_questionnaire_or_404(questionnaire_id: int, company_id: int, db: Session) -> Questionnaire:
    questionnaire = (
        db.query(Questionnaire)
        .filter(Questionnaire.id == questionnaire_id, Questionnaire.company_id == company_id)
        .first()
    )
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    return questionnaire


def _question_to_dict(question: QuestionnaireQuestion) -> dict:
    return {
        "id": question.id,
        "question_text": question.question_text,
        "question_type": question.question_type,
        "options": json.loads(question.options) if question.options else None,
        "position": question.position,
        "required": question.required,
    }


def _completed_count(questionnaire_id: int, company_id: int, db: Session) -> int:
    return (
        db.query(func.count(QuestionnaireResponse.id))
        .filter(
            QuestionnaireResponse.questionnaire_id == questionnaire_id,
            QuestionnaireResponse.company_id == company_id,
            QuestionnaireResponse.status == "completed",
        )
        .scalar()
        or 0
    )


def _questionnaire_detail(questionnaire: Questionnaire, db: Session) -> dict:
    invited = (
        db.query(func.count(QuestionnaireResponse.id))
        .filter(
            QuestionnaireResponse.questionnaire_id == questionnaire.id,
            QuestionnaireResponse.company_id == questionnaire.company_id,
        )
        .scalar()
        or 0
    )
    return {
        "id": questionnaire.id,
        "title": questionnaire.title,
        "description": questionnaire.description,
        "created_at": questionnaire.created_at.isoformat() if questionnaire.created_at else None,
        "updated_at": questionnaire.updated_at.isoformat() if questionnaire.updated_at else None,
        "questions": [_question_to_dict(q) for q in questionnaire.questions],
        "invited_count": invited,
        "completed_count": _completed_count(questionnaire.id, questionnaire.company_id, db),
    }


def _insert_questions(questionnaire: Questionnaire, questions, db: Session) -> None:
    for idx, qi in enumerate(questions):
        db.add(
            QuestionnaireQuestion(
                questionnaire_id=questionnaire.id,
                company_id=questionnaire.company_id,
                question_text=qi.question_text.strip(),
                question_type=qi.question_type,
                options=json.dumps(qi.options) if qi.options is not None else None,
                position=idx,
                required=qi.required,
            )
        )


# ---------------------------------------------------------------------------
# Questionnaire CRUD
# ---------------------------------------------------------------------------


@router.get("/api/automations/questionnaires")
async def list_questionnaires(user_id: int = Depends(verify_token), db: Session = Depends(get_db)):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")

    questionnaires = (
        db.query(Questionnaire)
        .filter(Questionnaire.company_id == membership.company_id)
        .order_by(Questionnaire.created_at.desc())
        .all()
    )
    ids = [q.id for q in questionnaires]
    question_counts, invited_counts, completed_counts = {}, {}, {}
    if ids:
        question_counts = dict(
            db.query(QuestionnaireQuestion.questionnaire_id, func.count())
            .filter(QuestionnaireQuestion.questionnaire_id.in_(ids))
            .group_by(QuestionnaireQuestion.questionnaire_id)
            .all()
        )
        invited_counts = dict(
            db.query(QuestionnaireResponse.questionnaire_id, func.count())
            .filter(QuestionnaireResponse.questionnaire_id.in_(ids))
            .group_by(QuestionnaireResponse.questionnaire_id)
            .all()
        )
        completed_counts = dict(
            db.query(QuestionnaireResponse.questionnaire_id, func.count())
            .filter(
                QuestionnaireResponse.questionnaire_id.in_(ids),
                QuestionnaireResponse.status == "completed",
            )
            .group_by(QuestionnaireResponse.questionnaire_id)
            .all()
        )

    return {
        "questionnaires": [
            {
                "id": q.id,
                "title": q.title,
                "description": q.description,
                "created_at": q.created_at.isoformat() if q.created_at else None,
                "question_count": question_counts.get(q.id, 0),
                "invited_count": invited_counts.get(q.id, 0),
                "completed_count": completed_counts.get(q.id, 0),
            }
            for q in questionnaires
        ]
    }


@router.post("/api/automations/questionnaires")
async def create_questionnaire(
    body: QuestionnaireCreate,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")

    questionnaire = Questionnaire(
        company_id=membership.company_id,
        user_id=user_id,
        title=body.title.strip(),
        description=body.description,
    )
    db.add(questionnaire)
    db.flush()
    _insert_questions(questionnaire, body.questions, db)
    db.commit()
    db.refresh(questionnaire)
    return {"questionnaire": _questionnaire_detail(questionnaire, db)}


@router.get("/api/automations/questionnaires/{questionnaire_id}")
async def get_questionnaire(
    questionnaire_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)
    return {"questionnaire": _questionnaire_detail(questionnaire, db)}


@router.put("/api/automations/questionnaires/{questionnaire_id}")
async def update_questionnaire(
    questionnaire_id: int,
    body: QuestionnaireUpdate,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    if _completed_count(questionnaire.id, questionnaire.company_id, db) > 0:
        raise HTTPException(
            status_code=409,
            detail="Des réponses ont déjà été reçues : le questionnaire n'est plus modifiable.",
        )

    questionnaire.title = body.title.strip()
    questionnaire.description = body.description
    questionnaire.updated_at = datetime.utcnow()
    db.query(QuestionnaireQuestion).filter(QuestionnaireQuestion.questionnaire_id == questionnaire.id).delete(
        synchronize_session=False
    )
    _insert_questions(questionnaire, body.questions, db)
    db.commit()
    db.refresh(questionnaire)
    return {"questionnaire": _questionnaire_detail(questionnaire, db)}


@router.delete("/api/automations/questionnaires/{questionnaire_id}")
async def delete_questionnaire(
    questionnaire_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)
    db.delete(questionnaire)
    db.commit()
    return {"success": True}


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


def _send_invitations(response_ids: list):
    """Background task: send invitation emails and flag email_sent.

    Failures are logged and leave email_sent=False so the invitation stays
    visible and resendable in the UI — never blocking.

    Runs in a worker thread with the scheduling request's context; the
    questionnaire tables have no RLS so app.company_id is inert here.
    """
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    db = SessionLocal()
    try:
        responses = (
            db.query(QuestionnaireResponse)
            .options(joinedload(QuestionnaireResponse.questionnaire))
            .filter(QuestionnaireResponse.id.in_(response_ids))
            .all()
        )
        if not responses:
            return
        # All response_ids in one call always belong to one questionnaire
        # (invite and resend both guarantee it) — fetch company once.
        questionnaire = responses[0].questionnaire
        company = db.query(Company).filter(Company.id == questionnaire.company_id).first()
        company_name = company.name if company else "TAIC"
        for response in responses:
            try:
                send_questionnaire_invitation_email(
                    to_email=response.respondent_email,
                    questionnaire_name=response.questionnaire.title,
                    company_name=company_name,
                    respondent_name=response.respondent_name,
                    questionnaire_url=f"{frontend_url}/questionnaire/{response.token}",
                )
                response.email_sent = True
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(
                    "Failed to send questionnaire invitation to %s (response %s): %s",
                    response.respondent_email,
                    response.id,
                    e,
                )
    finally:
        db.close()


@router.post("/api/automations/questionnaires/{questionnaire_id}/invite")
async def invite_respondents(
    questionnaire_id: int,
    body: InviteRequest,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    if not questionnaire.questions:
        raise HTTPException(status_code=400, detail="Le questionnaire n'a aucune question.")

    emails = [r.email for r in body.recipients]
    already_invited = {
        row[0]
        for row in db.query(QuestionnaireResponse.respondent_email)
        .filter(
            QuestionnaireResponse.questionnaire_id == questionnaire.id,
            QuestionnaireResponse.respondent_email.in_(emails),
        )
        .all()
    }

    created = []
    seen = set(already_invited)
    for recipient in body.recipients:
        if recipient.email in seen:
            continue
        seen.add(recipient.email)
        response = QuestionnaireResponse(
            questionnaire_id=questionnaire.id,
            company_id=questionnaire.company_id,
            respondent_email=recipient.email,
            respondent_name=recipient.name,
            token=secrets.token_urlsafe(32),
            status="pending",
            email_sent=False,
        )
        db.add(response)
        created.append(response)

    db.flush()
    created_ids = [r.id for r in created]
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Invitation déjà envoyée pour une de ces adresses (requête concurrente).",
        )

    if created_ids:
        background_tasks.add_task(_send_invitations, created_ids)

    return {"invited": len(created_ids), "skipped": len(body.recipients) - len(created_ids)}


@router.post("/api/automations/questionnaires/{questionnaire_id}/responses/{response_id}/resend")
async def resend_invitation(
    questionnaire_id: int,
    response_id: int,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    response = (
        db.query(QuestionnaireResponse)
        .filter(
            QuestionnaireResponse.id == response_id,
            QuestionnaireResponse.questionnaire_id == questionnaire.id,
        )
        .first()
    )
    if not response:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if response.status == "completed":
        raise HTTPException(status_code=409, detail="Ce questionnaire a déjà été complété.")

    background_tasks.add_task(_send_invitations, [response.id])
    return {"success": True}


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


def _response_to_dict(response: QuestionnaireResponse) -> dict:
    return {
        "id": response.id,
        "respondent_email": response.respondent_email,
        "respondent_name": response.respondent_name,
        "status": response.status,
        "email_sent": response.email_sent,
        "invited_at": response.invited_at.isoformat() if response.invited_at else None,
        "completed_at": response.completed_at.isoformat() if response.completed_at else None,
    }


def _get_response_or_404(response_id: int, questionnaire: Questionnaire, db: Session) -> QuestionnaireResponse:
    response = (
        db.query(QuestionnaireResponse)
        .filter(
            QuestionnaireResponse.id == response_id,
            QuestionnaireResponse.questionnaire_id == questionnaire.id,
        )
        .first()
    )
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")
    return response


@router.get("/api/automations/questionnaires/{questionnaire_id}/responses")
async def list_responses(
    questionnaire_id: int,
    status: Optional[str] = Query(None, pattern="^(pending|completed)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    base = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.questionnaire_id == questionnaire.id)
    total = base.count()
    completed_count = _completed_count(questionnaire.id, questionnaire.company_id, db)

    query = base
    if status:
        query = query.filter(QuestionnaireResponse.status == status)
    filtered_total = query.count() if status else total
    rows = query.order_by(QuestionnaireResponse.invited_at.desc()).offset(offset).limit(limit).all()
    return {
        "responses": [_response_to_dict(r) for r in rows],
        "total": total,
        "filtered_total": filtered_total,
        "completed_count": completed_count,
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/automations/questionnaires/{questionnaire_id}/responses/{response_id}")
async def get_response(
    questionnaire_id: int,
    response_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)
    response = _get_response_or_404(response_id, questionnaire, db)

    rows = (
        db.query(QuestionnaireAnswer, QuestionnaireQuestion)
        .join(QuestionnaireQuestion, QuestionnaireAnswer.question_id == QuestionnaireQuestion.id)
        .filter(QuestionnaireAnswer.response_id == response.id)
        .order_by(QuestionnaireQuestion.position)
        .all()
    )
    data = _response_to_dict(response)
    data["answers"] = [
        {
            "question_id": question.id,
            "question_text": question.question_text,
            "question_type": question.question_type,
            "answer_text": answer.answer_text,
        }
        for answer, question in rows
    ]
    return {"response": data}


@router.delete("/api/automations/questionnaires/{questionnaire_id}/responses/{response_id}")
async def delete_response(
    questionnaire_id: int,
    response_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)
    response = _get_response_or_404(response_id, questionnaire, db)
    db.delete(response)
    db.commit()
    return {"success": True}


# ---------------------------------------------------------------------------
# Export to companion RAG
# ---------------------------------------------------------------------------


def _build_response_markdown(questionnaire: Questionnaire, response: QuestionnaireResponse, db: Session) -> str:
    lines = [
        f"# {questionnaire.title} — Réponse de {response.respondent_name or response.respondent_email}",
        "",
    ]
    if response.completed_at:
        lines.append(f"Complété le : {response.completed_at.strftime('%d/%m/%Y %H:%M')}")
        lines.append("")
    rows = (
        db.query(QuestionnaireAnswer, QuestionnaireQuestion)
        .join(QuestionnaireQuestion, QuestionnaireAnswer.question_id == QuestionnaireQuestion.id)
        .filter(QuestionnaireAnswer.response_id == response.id)
        .order_by(QuestionnaireQuestion.position)
        .all()
    )
    for answer, question in rows:
        value = answer.answer_text or ""
        if question.question_type == "multiple_choice" and value:
            try:
                value = ", ".join(json.loads(value))
            except (ValueError, TypeError):
                pass
        lines.append(f"**Q : {question.question_text}**")
        lines.append(f"R : {value}")
        lines.append("")
    return "\n".join(lines)


@router.post("/api/automations/questionnaires/{questionnaire_id}/export")
async def export_responses_to_rag(
    questionnaire_id: int,
    body: ExportRequest,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    agent = db.query(Agent).filter(Agent.id == body.target_agent_id, Agent.company_id == membership.company_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Target agent not found")
    if agent.type not in EXPORTABLE_AGENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="L'export RAG n'est possible que vers un companion conversationnel ou actionnable.",
        )

    responses = (
        db.query(QuestionnaireResponse)
        .filter(
            QuestionnaireResponse.id.in_(body.response_ids),
            QuestionnaireResponse.questionnaire_id == questionnaire.id,
            QuestionnaireResponse.status == "completed",
        )
        .all()
    )
    if not responses:
        raise HTTPException(status_code=400, detail="Aucune réponse complétée à exporter.")

    from rag_engine import ingest_text_content

    exported = 0
    failed_ids = []
    for response in responses:
        markdown = _build_response_markdown(questionnaire, response, db)
        filename = f"questionnaire-{questionnaire.id}-reponse-{response.id}.md"
        try:
            ingest_text_content(
                markdown,
                filename,
                user_id,
                agent.id,
                db,
                company_id=membership.company_id,
            )
            exported += 1
        except Exception as e:
            # ingest_text_content commits per document; a failure here leaves
            # previously exported responses ingested — report rather than 500.
            logger.error("Export failed for response %s: %s", response.id, e)
            failed_ids.append(response.id)

    return {"exported": exported, "failed_response_ids": failed_ids, "target_agent_id": agent.id}
