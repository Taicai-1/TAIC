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
