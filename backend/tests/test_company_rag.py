"""Tests for the company RAG feature (shared org documents + per-agent inclusion)."""

import pytest


@pytest.mark.asyncio
async def test_company_rag_columns_default_false(db_session, test_company):
    """New columns exist and default to False."""
    from tests.factories import UserFactory, AgentFactory, DocumentFactory

    user = UserFactory.build(company_id=test_company.id)
    db_session.add(user)
    db_session.flush()

    agent = AgentFactory.build(user_id=user.id, company_id=test_company.id)
    db_session.add(agent)
    db_session.flush()

    doc = DocumentFactory.build(user_id=user.id, company_id=test_company.id)
    db_session.add(doc)
    db_session.flush()

    assert agent.include_company_rag is False
    assert doc.is_company_rag is False
