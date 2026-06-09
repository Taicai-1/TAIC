"""Questionnaire endpoints: question CRUD, invitations, responses, PDF export, RAG integration."""

import json
import logging
import secrets
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response as FastAPIResponse
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


##### Responses #####


@router.get("/api/agents/{agent_id}/responses")
async def list_responses(
    agent_id: int,
    status: Optional[str] = Query(None, regex="^(pending|in_progress|completed)$"),
    user: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List all responses for a questionnaire agent with optional status filter."""
    _get_questionnaire_agent(agent_id, user["user_id"], db)

    query = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.agent_id == agent_id)

    if status:
        query = query.filter(QuestionnaireResponse.status == status)

    responses = query.order_by(QuestionnaireResponse.invited_at.desc()).all()

    # Calculate totals
    total_invited = db.query(QuestionnaireResponse).filter(QuestionnaireResponse.agent_id == agent_id).count()
    total_completed = (
        db.query(QuestionnaireResponse)
        .filter(QuestionnaireResponse.agent_id == agent_id, QuestionnaireResponse.status == "completed")
        .count()
    )

    # Build response summaries
    summaries = [
        ResponseSummary(
            id=r.id,
            respondent_email=r.respondent_email,
            respondent_name=r.respondent_name,
            status=r.status,
            invited_at=r.invited_at,
            completed_at=r.completed_at,
        )
        for r in responses
    ]

    return {"total_invited": total_invited, "total_completed": total_completed, "responses": summaries}


@router.get("/api/agents/{agent_id}/responses/{response_id}", response_model=ResponseDetail)
async def get_response_detail(
    agent_id: int, response_id: int, user: dict = Depends(verify_token), db: Session = Depends(get_db)
):
    """Get full details of a questionnaire response including all answers."""
    _get_questionnaire_agent(agent_id, user["user_id"], db)

    response = (
        db.query(QuestionnaireResponse)
        .filter(QuestionnaireResponse.id == response_id, QuestionnaireResponse.agent_id == agent_id)
        .first()
    )

    if not response:
        raise HTTPException(status_code=404, detail="Response not found")

    # Get all answers with question details
    answers = (
        db.query(QuestionnaireAnswer, QuestionnaireQuestion)
        .join(QuestionnaireQuestion, QuestionnaireAnswer.question_id == QuestionnaireQuestion.id)
        .filter(QuestionnaireAnswer.response_id == response_id)
        .order_by(QuestionnaireQuestion.position)
        .all()
    )

    answer_list = [
        AnswerOut(
            id=ans.id,
            question_id=ans.question_id,
            question_text=q.question_text,
            question_type=q.question_type,
            answer_text=ans.answer_text,
            answered_at=ans.answered_at,
        )
        for ans, q in answers
    ]

    return ResponseDetail(
        id=response.id,
        respondent_email=response.respondent_email,
        respondent_name=response.respondent_name,
        status=response.status,
        invited_at=response.invited_at,
        started_at=response.started_at,
        completed_at=response.completed_at,
        answers=answer_list,
    )


@router.get("/api/agents/{agent_id}/responses/{response_id}/pdf")
async def export_response_pdf(
    agent_id: int, response_id: int, user: dict = Depends(verify_token), db: Session = Depends(get_db)
):
    """Generate a PDF of a questionnaire response."""
    agent = _get_questionnaire_agent(agent_id, user["user_id"], db)

    response = (
        db.query(QuestionnaireResponse)
        .filter(QuestionnaireResponse.id == response_id, QuestionnaireResponse.agent_id == agent_id)
        .first()
    )

    if not response:
        raise HTTPException(status_code=404, detail="Response not found")

    # Get all answers with question details
    answers = (
        db.query(QuestionnaireAnswer, QuestionnaireQuestion)
        .join(QuestionnaireQuestion, QuestionnaireAnswer.question_id == QuestionnaireQuestion.id)
        .filter(QuestionnaireAnswer.response_id == response_id)
        .order_by(QuestionnaireQuestion.position)
        .all()
    )

    # Build HTML
    answers_html = ""
    for ans, q in answers:
        answer_display = ans.answer_text or "(pas de réponse)"
        answers_html += f"""
        <div style="margin-bottom: 24px; padding: 16px; background: #f9fafb; border-left: 4px solid #6366f1; border-radius: 4px;">
            <div style="font-weight: 600; color: #1f2937; margin-bottom: 8px;">{q.question_text}</div>
            <div style="color: #4b5563; font-size: 14px;">Type: {q.question_type}</div>
            <div style="margin-top: 8px; color: #111827;">{answer_display}</div>
        </div>
        """

    completed_date = response.completed_at.strftime("%d/%m/%Y %H:%M") if response.completed_at else "N/A"
    respondent_name = response.respondent_name or response.respondent_email

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <title>Réponse Questionnaire - {agent.name}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 32px;
            color: #1f2937;
        }}
        .header {{
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            color: white;
            padding: 32px;
            border-radius: 8px;
            margin-bottom: 32px;
        }}
        .header h1 {{
            margin: 0;
            font-size: 28px;
            font-weight: 700;
        }}
        .info {{
            margin-top: 16px;
            font-size: 14px;
            opacity: 0.95;
        }}
        .content {{
            max-width: 800px;
            margin: 0 auto;
        }}
    </style>
</head>
<body>
    <div class="content">
        <div class="header">
            <h1>Questionnaire : {agent.name}</h1>
            <div class="info">
                <div><strong>Répondant :</strong> {respondent_name}</div>
                <div><strong>Email :</strong> {response.respondent_email}</div>
                <div><strong>Date de complétion :</strong> {completed_date}</div>
            </div>
        </div>
        {answers_html}
    </div>
</body>
</html>"""

    # Try weasyprint, fallback to HTML if not available
    try:
        from weasyprint import HTML

        pdf_bytes = HTML(string=html).write_pdf()
        filename = f"questionnaire_{agent.name.replace(' ', '_')}_{response_id}.pdf"

        return FastAPIResponse(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ImportError:
        logger.warning("weasyprint not installed, returning HTML instead of PDF")
        return FastAPIResponse(content=html, media_type="text/html")


##### RAG Export #####


def _build_response_markdown(agent_name: str, resp: QuestionnaireResponse, answers_data: list) -> str:
    """Build a structured markdown document for a questionnaire response."""
    respondent_display = f"{resp.respondent_name} ({resp.respondent_email})" if resp.respondent_name else resp.respondent_email
    date_display = resp.completed_at.strftime("%d/%m/%Y") if resp.completed_at else "N/A"

    md = f"""# Questionnaire : {agent_name}
## Répondant : {respondent_display}
## Date : {date_display}

"""

    for ans, q in answers_data:
        answer_text = ans.answer_text or "(pas de réponse)"

        # Format based on question type
        if q.question_type == "rating":
            answer_display = f"Note : {answer_text}"
        elif q.question_type in ("single_choice", "multiple_choice"):
            answer_display = answer_text
        else:
            answer_display = answer_text

        md += f"""### {q.question_text}
{answer_display}

"""

    return md


@router.post("/api/agents/{agent_id}/responses/export")
async def export_responses_to_rag(
    agent_id: int, export: ExportRequest, user: dict = Depends(verify_token), db: Session = Depends(get_db)
):
    """Export completed questionnaire responses to a target agent's RAG knowledge base."""
    from file_loader import chunk_text
    from mistral_embeddings import get_embedding

    agent = _get_questionnaire_agent(agent_id, user["user_id"], db)
    company_id = agent.company_id

    # Verify target agent exists and belongs to same company
    target_agent = db.query(Agent).filter(Agent.id == export.target_agent_id).first()
    if not target_agent:
        raise HTTPException(status_code=404, detail="Target agent not found")

    if target_agent.company_id != company_id:
        raise HTTPException(status_code=403, detail="Target agent does not belong to same company")

    if target_agent.type not in ("conversationnel", "actionnable"):
        raise HTTPException(status_code=400, detail="Target agent must be conversationnel or actionnable type")

    # Get responses
    responses = (
        db.query(QuestionnaireResponse)
        .filter(
            QuestionnaireResponse.id.in_(export.response_ids),
            QuestionnaireResponse.agent_id == agent_id,
            QuestionnaireResponse.status == "completed",
        )
        .all()
    )

    if not responses:
        raise HTTPException(status_code=404, detail="No completed responses found with given IDs")

    exported_count = 0

    for resp in responses:
        # Get answers with questions
        answers_data = (
            db.query(QuestionnaireAnswer, QuestionnaireQuestion)
            .join(QuestionnaireQuestion, QuestionnaireAnswer.question_id == QuestionnaireQuestion.id)
            .filter(QuestionnaireAnswer.response_id == resp.id)
            .order_by(QuestionnaireQuestion.position)
            .all()
        )

        # Build markdown
        markdown_content = _build_response_markdown(agent.name, resp, answers_data)

        # Create document
        doc = Document(
            agent_id=export.target_agent_id,
            company_id=company_id,
            file_name=f"Questionnaire_{resp.id}_{resp.respondent_email}.md",
            file_path=None,  # No physical file
            document_type="rag",
        )
        db.add(doc)
        db.flush()

        # Chunk the markdown
        chunks = chunk_text(markdown_content, chunk_size=512, overlap=50)

        # Embed and store chunks
        for i, chunk_text_str in enumerate(chunks):
            try:
                embedding = get_embedding(chunk_text_str)

                chunk = DocumentChunk(
                    document_id=doc.id,
                    agent_id=export.target_agent_id,
                    company_id=company_id,
                    chunk_text=chunk_text_str,
                    chunk_index=i,
                    embedding=embedding,
                )
                db.add(chunk)
            except Exception as e:
                logger.error(f"Failed to embed chunk {i} for response {resp.id}: {e}")
                # Continue with other chunks

        exported_count += 1
        logger.info(f"Exported response {resp.id} to agent {export.target_agent_id}")

    db.commit()

    return {"message": f"Exported {exported_count} responses to agent {export.target_agent_id}", "exported": exported_count}
