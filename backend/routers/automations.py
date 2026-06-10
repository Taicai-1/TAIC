"""Automations endpoints: questionnaire CRUD, invitations, responses, RAG export."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import verify_token
from database import (
    Questionnaire,
    QuestionnaireQuestion,
    QuestionnaireResponse,
    get_db,
)
from permissions import require_role
from schemas.questionnaires import (
    QuestionnaireCreate,
    QuestionnaireUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()

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


def _completed_count(questionnaire_id: int, db: Session) -> int:
    return (
        db.query(func.count(QuestionnaireResponse.id))
        .filter(
            QuestionnaireResponse.questionnaire_id == questionnaire_id,
            QuestionnaireResponse.status == "completed",
        )
        .scalar()
        or 0
    )


def _questionnaire_detail(questionnaire: Questionnaire, db: Session) -> dict:
    invited = (
        db.query(func.count(QuestionnaireResponse.id))
        .filter(QuestionnaireResponse.questionnaire_id == questionnaire.id)
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
        "completed_count": _completed_count(questionnaire.id, db),
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
async def list_questionnaires(
    user_id: int = Depends(verify_token), db: Session = Depends(get_db)
):
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
    membership = require_role(user_id, db, "member")

    questionnaire = Questionnaire(
        company_id=membership.company_id,
        user_id=int(user_id),
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
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    if _completed_count(questionnaire.id, db) > 0:
        raise HTTPException(
            status_code=409,
            detail="Des réponses ont déjà été reçues : le questionnaire n'est plus modifiable.",
        )

    questionnaire.title = body.title.strip()
    questionnaire.description = body.description
    questionnaire.updated_at = datetime.utcnow()
    db.query(QuestionnaireQuestion).filter(
        QuestionnaireQuestion.questionnaire_id == questionnaire.id
    ).delete()
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
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)
    db.delete(questionnaire)
    db.commit()
    return {"success": True}
