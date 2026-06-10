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
