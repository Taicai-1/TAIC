"""Tests for the automations questionnaire feature (models, schemas, admin + public endpoints)."""

import pytest


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_questionnaire_model_roundtrip(db_session, test_questionnaire):
    from database import Questionnaire

    loaded = db_session.query(Questionnaire).filter(Questionnaire.id == test_questionnaire.id).first()
    assert loaded is not None
    assert len(loaded.questions) == 2
    assert loaded.questions[0].position == 0  # relationship ordered by position
    assert loaded.questions[0].question_type == "open"
    assert loaded.questions[1].question_type == "single_choice"


def test_questionnaire_cascade_delete(db_session, test_questionnaire, test_company):
    from database import QuestionnaireAnswer, QuestionnaireQuestion, QuestionnaireResponse
    from tests.factories import QuestionnaireAnswerFactory, QuestionnaireResponseFactory

    response = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id
    )
    db_session.add(response)
    db_session.flush()
    answer = QuestionnaireAnswerFactory.build(
        response_id=response.id,
        question_id=test_questionnaire.questions[0].id,
        company_id=test_company.id,
    )
    db_session.add(answer)
    db_session.flush()

    questionnaire_id = test_questionnaire.id
    response_id = response.id
    db_session.delete(test_questionnaire)
    db_session.flush()

    assert db_session.query(QuestionnaireQuestion).filter(
        QuestionnaireQuestion.questionnaire_id == questionnaire_id
    ).count() == 0
    assert db_session.query(QuestionnaireResponse).filter(
        QuestionnaireResponse.questionnaire_id == questionnaire_id
    ).count() == 0
    assert db_session.query(QuestionnaireAnswer).filter(
        QuestionnaireAnswer.response_id == response_id
    ).count() == 0


# ---------------------------------------------------------------------------
# Schema unit tests (no DB required)
# ---------------------------------------------------------------------------

from pydantic import ValidationError  # noqa: E402

from schemas.questionnaires import InviteRequest, QuestionInput  # noqa: E402


class TestQuestionInputSchema:
    def test_open_question_defaults(self):
        q = QuestionInput(question_text="Votre avis ?")
        assert q.question_type == "open"
        assert q.options is None
        assert q.required is True

    def test_open_question_drops_options(self):
        q = QuestionInput(question_text="Avis ?", question_type="open", options=["a"])
        assert q.options is None

    def test_choice_requires_options(self):
        with pytest.raises(ValidationError):
            QuestionInput(question_text="Choix ?", question_type="single_choice", options=None)

    def test_choice_rejects_blank_options(self):
        with pytest.raises(ValidationError):
            QuestionInput(question_text="Choix ?", question_type="multiple_choice", options=["  "])

    def test_rating_normalizes_missing_options(self):
        q = QuestionInput(question_text="Note ?", question_type="rating", options=None)
        assert q.options == {"min": 1, "max": 5}

    def test_rating_rejects_inverted_bounds(self):
        with pytest.raises(ValidationError):
            QuestionInput(question_text="Note ?", question_type="rating", options={"min": 5, "max": 1})

    def test_unknown_type_rejected(self):
        with pytest.raises(ValidationError):
            QuestionInput(question_text="?", question_type="dropdown")

    def test_blank_question_text_rejected(self):
        with pytest.raises(ValidationError):
            QuestionInput(question_text="   ")

    def test_rating_rejects_negative_bounds(self):
        with pytest.raises(ValidationError):
            QuestionInput(question_text="Note ?", question_type="rating", options={"min": -5, "max": -1})


class TestInviteRequestSchema:
    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            InviteRequest(recipients=[{"email": "not-an-email"}])

    def test_email_normalized(self):
        req = InviteRequest(recipients=[{"email": "  Marie@Example.COM ", "name": "Marie"}])
        assert req.recipients[0].email == "marie@example.com"

    def test_empty_recipients_rejected(self):
        with pytest.raises(ValidationError):
            InviteRequest(recipients=[])


class TestQuestionnaireUpdateSchema:
    def test_blank_title_rejected(self):
        from schemas.questionnaires import QuestionnaireUpdate

        with pytest.raises(ValidationError):
            QuestionnaireUpdate(title="", questions=[])


# ---------------------------------------------------------------------------
# Admin endpoint tests — CRUD
# ---------------------------------------------------------------------------

CREATE_PAYLOAD = {
    "title": "Enquête satisfaction",
    "description": "Donnez-nous votre avis",
    "questions": [
        {"question_text": "Votre avis général ?", "question_type": "open", "position": 0, "required": True},
        {
            "question_text": "Recommanderiez-vous ?",
            "question_type": "single_choice",
            "options": ["Oui", "Non"],
            "position": 1,
            "required": True,
        },
        {
            "question_text": "Note globale ?",
            "question_type": "rating",
            "options": {"min": 1, "max": 5},
            "position": 2,
            "required": False,
        },
    ],
}


@pytest.mark.asyncio
async def test_create_and_get_questionnaire(client, member_cookies):
    resp = await client.post(
        "/api/automations/questionnaires", json=CREATE_PAYLOAD, cookies=member_cookies
    )
    assert resp.status_code == 200
    data = resp.json()["questionnaire"]
    assert data["title"] == "Enquête satisfaction"
    assert len(data["questions"]) == 3
    assert data["questions"][1]["options"] == ["Oui", "Non"]
    assert data["questions"][2]["options"] == {"min": 1, "max": 5}

    detail = await client.get(
        f"/api/automations/questionnaires/{data['id']}", cookies=member_cookies
    )
    assert detail.status_code == 200
    assert len(detail.json()["questionnaire"]["questions"]) == 3


@pytest.mark.asyncio
async def test_create_questionnaire_validation_422(client, member_cookies):
    resp = await client.post(
        "/api/automations/questionnaires",
        json={"title": "", "questions": []},
        cookies=member_cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_questionnaires_with_counts(client, member_cookies, test_questionnaire):
    resp = await client.get("/api/automations/questionnaires", cookies=member_cookies)
    assert resp.status_code == 200
    items = resp.json()["questionnaires"]
    assert len(items) == 1
    assert items[0]["question_count"] == 2
    assert items[0]["invited_count"] == 0
    assert items[0]["completed_count"] == 0


@pytest.mark.asyncio
async def test_questionnaire_cross_company_404(client, member_cookies, db_session):
    from tests.factories import CompanyFactory, QuestionnaireFactory, UserFactory

    other_company = CompanyFactory.build()
    db_session.add(other_company)
    db_session.flush()
    other_user = UserFactory.build(company_id=other_company.id)
    db_session.add(other_user)
    db_session.flush()
    foreign = QuestionnaireFactory.build(company_id=other_company.id, user_id=other_user.id)
    db_session.add(foreign)
    db_session.flush()

    resp = await client.get(
        f"/api/automations/questionnaires/{foreign.id}", cookies=member_cookies
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_replaces_questions(client, member_cookies, test_questionnaire):
    payload = {
        "title": "Titre modifié",
        "description": None,
        "questions": [
            {"question_text": "Nouvelle question unique ?", "question_type": "open", "position": 0, "required": True}
        ],
    }
    resp = await client.put(
        f"/api/automations/questionnaires/{test_questionnaire.id}",
        json=payload,
        cookies=member_cookies,
    )
    assert resp.status_code == 200
    data = resp.json()["questionnaire"]
    assert data["title"] == "Titre modifié"
    assert len(data["questions"]) == 1


@pytest.mark.asyncio
async def test_update_blocked_when_completed_responses(
    client, member_cookies, db_session, test_questionnaire, test_company
):
    from tests.factories import QuestionnaireResponseFactory

    done = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id, status="completed"
    )
    db_session.add(done)
    db_session.flush()

    resp = await client.put(
        f"/api/automations/questionnaires/{test_questionnaire.id}",
        json={"title": "X", "questions": []},
        cookies=member_cookies,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_delete_questionnaire(client, member_cookies, test_questionnaire):
    resp = await client.delete(
        f"/api/automations/questionnaires/{test_questionnaire.id}", cookies=member_cookies
    )
    assert resp.status_code == 200
    again = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}", cookies=member_cookies
    )
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_list_requires_company_membership(client, auth_cookies):
    # test_user has no CompanyMembership -> require_role returns 404
    resp = await client.get("/api/automations/questionnaires", cookies=auth_cookies)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin endpoint tests — invitations
# ---------------------------------------------------------------------------

from unittest.mock import patch  # noqa: E402


@pytest.mark.asyncio
async def test_invite_dedupes_and_schedules_emails(client, member_cookies, db_session, test_questionnaire):
    from database import QuestionnaireResponse

    with patch("routers.automations._send_invitations") as mock_send:
        resp = await client.post(
            f"/api/automations/questionnaires/{test_questionnaire.id}/invite",
            json={
                "recipients": [
                    {"email": "a@test.com"},
                    {"email": "A@test.com"},  # duplicate after normalization
                    {"email": "b@test.com", "name": "Bob"},
                ]
            },
            cookies=member_cookies,
        )
    assert resp.status_code == 200
    assert resp.json()["invited"] == 2
    assert resp.json()["skipped"] == 1

    rows = (
        db_session.query(QuestionnaireResponse)
        .filter(QuestionnaireResponse.questionnaire_id == test_questionnaire.id)
        .all()
    )
    assert len(rows) == 2
    assert all(r.status == "pending" and r.email_sent is False and r.token for r in rows)
    assert mock_send.called
    assert sorted(mock_send.call_args[0][0]) == sorted([r.id for r in rows])


@pytest.mark.asyncio
async def test_invite_skips_already_invited(client, member_cookies, db_session, test_questionnaire, test_company):
    from tests.factories import QuestionnaireResponseFactory

    existing = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id,
        company_id=test_company.id,
        respondent_email="deja@test.com",
    )
    db_session.add(existing)
    db_session.flush()

    with patch("routers.automations._send_invitations") as mock_send:
        resp = await client.post(
            f"/api/automations/questionnaires/{test_questionnaire.id}/invite",
            json={"recipients": [{"email": "deja@test.com"}]},
            cookies=member_cookies,
        )
    assert resp.status_code == 200
    assert resp.json() == {"invited": 0, "skipped": 1}
    assert not mock_send.called


@pytest.mark.asyncio
async def test_invite_requires_questions(client, member_cookies, db_session, test_member_user, test_company):
    from tests.factories import QuestionnaireFactory

    empty = QuestionnaireFactory.build(company_id=test_company.id, user_id=test_member_user.id)
    db_session.add(empty)
    db_session.flush()

    resp = await client.post(
        f"/api/automations/questionnaires/{empty.id}/invite",
        json={"recipients": [{"email": "x@test.com"}]},
        cookies=member_cookies,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_resend_invitation(client, member_cookies, db_session, test_questionnaire, test_company):
    from tests.factories import QuestionnaireResponseFactory

    invitation = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id
    )
    db_session.add(invitation)
    db_session.flush()

    with patch("routers.automations._send_invitations") as mock_send:
        resp = await client.post(
            f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{invitation.id}/resend",
            cookies=member_cookies,
        )
    assert resp.status_code == 200
    assert mock_send.called
    assert mock_send.call_args[0][0] == [invitation.id]


@pytest.mark.asyncio
async def test_resend_rejected_for_completed(client, member_cookies, db_session, test_questionnaire, test_company):
    from tests.factories import QuestionnaireResponseFactory

    done = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id, status="completed"
    )
    db_session.add(done)
    db_session.flush()

    resp = await client.post(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{done.id}/resend",
        cookies=member_cookies,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_resend_404_for_foreign_questionnaire_response(
    client, member_cookies, db_session, test_questionnaire, test_member_user, test_company
):
    from tests.factories import QuestionnaireFactory, QuestionnaireResponseFactory

    other = QuestionnaireFactory.build(company_id=test_company.id, user_id=test_member_user.id)
    db_session.add(other)
    db_session.flush()
    response = QuestionnaireResponseFactory.build(
        questionnaire_id=other.id, company_id=test_company.id
    )
    db_session.add(response)
    db_session.flush()

    resp = await client.post(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{response.id}/resend",
        cookies=member_cookies,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin endpoint tests — responses
# ---------------------------------------------------------------------------


@pytest.fixture
def test_completed_response(db_session, test_questionnaire, test_company):
    """A completed response with one answer on the first (open) question."""
    from tests.factories import QuestionnaireAnswerFactory, QuestionnaireResponseFactory
    from datetime import datetime

    response = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id,
        company_id=test_company.id,
        status="completed",
        completed_at=datetime.utcnow(),
    )
    db_session.add(response)
    db_session.flush()
    answer = QuestionnaireAnswerFactory.build(
        response_id=response.id,
        question_id=test_questionnaire.questions[0].id,
        company_id=test_company.id,
        answer_text="Très satisfait",
    )
    db_session.add(answer)
    db_session.flush()
    return response


@pytest.mark.asyncio
async def test_list_responses_with_filter_and_pagination(
    client, member_cookies, db_session, test_questionnaire, test_company, test_completed_response
):
    from tests.factories import QuestionnaireResponseFactory

    pending = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id
    )
    db_session.add(pending)
    db_session.flush()

    resp = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses",
        cookies=member_cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["completed_count"] == 1
    assert len(data["responses"]) == 2

    only_completed = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses?status=completed",
        cookies=member_cookies,
    )
    assert len(only_completed.json()["responses"]) == 1
    assert only_completed.json()["filtered_total"] == 1
    assert only_completed.json()["total"] == 2

    paged = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses?limit=1&offset=0",
        cookies=member_cookies,
    )
    assert len(paged.json()["responses"]) == 1
    assert paged.json()["total"] == 2


@pytest.mark.asyncio
async def test_response_detail_with_answers(
    client, member_cookies, test_questionnaire, test_completed_response
):
    resp = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{test_completed_response.id}",
        cookies=member_cookies,
    )
    assert resp.status_code == 200
    data = resp.json()["response"]
    assert data["status"] == "completed"
    assert len(data["answers"]) == 1
    assert data["answers"][0]["answer_text"] == "Très satisfait"
    assert data["answers"][0]["question_text"] == test_questionnaire.questions[0].question_text


@pytest.mark.asyncio
async def test_delete_response(client, member_cookies, test_questionnaire, test_completed_response):
    resp = await client.delete(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{test_completed_response.id}",
        cookies=member_cookies,
    )
    assert resp.status_code == 200
    again = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{test_completed_response.id}",
        cookies=member_cookies,
    )
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_list_responses_invalid_status_422(client, member_cookies, test_questionnaire):
    resp = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses?status=bogus",
        cookies=member_cookies,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Admin endpoint tests — export to RAG
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_to_rag(
    client, member_cookies, db_session, test_questionnaire, test_company,
    test_member_user, test_completed_response,
):
    from tests.factories import AgentFactory

    agent = AgentFactory.build(
        user_id=test_member_user.id, company_id=test_company.id, type="conversationnel"
    )
    db_session.add(agent)
    db_session.flush()

    with patch("rag_engine.ingest_text_content", return_value=1) as mock_ingest:
        resp = await client.post(
            f"/api/automations/questionnaires/{test_questionnaire.id}/export",
            json={"response_ids": [test_completed_response.id], "target_agent_id": agent.id},
            cookies=member_cookies,
        )
    assert resp.status_code == 200
    assert resp.json()["exported"] == 1
    mock_ingest.assert_called_once()
    markdown = mock_ingest.call_args[0][0]
    assert test_questionnaire.questions[0].question_text in markdown
    assert "Très satisfait" in markdown
    args, kwargs = mock_ingest.call_args
    assert args[1] == f"questionnaire-{test_questionnaire.id}-reponse-{test_completed_response.id}.md"
    assert kwargs["company_id"] == test_company.id
    assert args[3] == agent.id
    assert resp.json()["failed_response_ids"] == []


@pytest.mark.asyncio
async def test_export_rejects_foreign_agent(
    client, member_cookies, db_session, test_questionnaire, test_completed_response
):
    from tests.factories import AgentFactory, CompanyFactory, UserFactory

    other_company = CompanyFactory.build()
    db_session.add(other_company)
    db_session.flush()
    other_user = UserFactory.build(company_id=other_company.id)
    db_session.add(other_user)
    db_session.flush()
    foreign_agent = AgentFactory.build(user_id=other_user.id, company_id=other_company.id)
    db_session.add(foreign_agent)
    db_session.flush()

    resp = await client.post(
        f"/api/automations/questionnaires/{test_questionnaire.id}/export",
        json={"response_ids": [test_completed_response.id], "target_agent_id": foreign_agent.id},
        cookies=member_cookies,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_requires_completed_responses(
    client, member_cookies, db_session, test_questionnaire, test_company, test_member_user
):
    from tests.factories import AgentFactory, QuestionnaireResponseFactory

    agent = AgentFactory.build(
        user_id=test_member_user.id, company_id=test_company.id, type="conversationnel"
    )
    pending = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id
    )
    db_session.add(agent)
    db_session.add(pending)
    db_session.flush()

    resp = await client.post(
        f"/api/automations/questionnaires/{test_questionnaire.id}/export",
        json={"response_ids": [pending.id], "target_agent_id": agent.id},
        cookies=member_cookies,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_export_rejects_wrong_agent_type(
    client, member_cookies, db_session, test_questionnaire, test_company,
    test_member_user, test_completed_response,
):
    from tests.factories import AgentFactory

    visuel = AgentFactory.build(
        user_id=test_member_user.id, company_id=test_company.id, type="visuel"
    )
    db_session.add(visuel)
    db_session.flush()

    resp = await client.post(
        f"/api/automations/questionnaires/{test_questionnaire.id}/export",
        json={"response_ids": [test_completed_response.id], "target_agent_id": visuel.id},
        cookies=member_cookies,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_export_reports_partial_failure(
    client, member_cookies, db_session, test_questionnaire, test_company,
    test_member_user, test_completed_response,
):
    from datetime import datetime

    from tests.factories import AgentFactory, QuestionnaireResponseFactory

    agent = AgentFactory.build(
        user_id=test_member_user.id, company_id=test_company.id, type="conversationnel"
    )
    second = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id,
        company_id=test_company.id,
        status="completed",
        completed_at=datetime.utcnow(),
    )
    db_session.add(agent)
    db_session.add(second)
    db_session.flush()

    with patch("rag_engine.ingest_text_content", side_effect=[1, RuntimeError("embed down")]) as mock_ingest:
        resp = await client.post(
            f"/api/automations/questionnaires/{test_questionnaire.id}/export",
            json={
                "response_ids": [test_completed_response.id, second.id],
                "target_agent_id": agent.id,
            },
            cookies=member_cookies,
        )
    assert resp.status_code == 200
    assert resp.json()["exported"] == 1
    assert len(resp.json()["failed_response_ids"]) == 1
    assert mock_ingest.call_count == 2
