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
    assert loaded.questions[1].question_type == "single_choice"


def test_questionnaire_cascade_delete(db_session, test_questionnaire, test_company):
    from database import QuestionnaireQuestion
    from tests.factories import QuestionnaireResponseFactory

    response = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id
    )
    db_session.add(response)
    db_session.flush()

    db_session.delete(test_questionnaire)
    db_session.flush()
    assert db_session.query(QuestionnaireQuestion).filter(
        QuestionnaireQuestion.questionnaire_id == test_questionnaire.id
    ).count() == 0
