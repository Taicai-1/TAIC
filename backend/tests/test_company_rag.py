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


def _seed_company_doc_with_chunk(db_session, company, user, vec):
    """Create a company RAG document with one embedded chunk. Returns the Document."""
    from tests.factories import DocumentFactory, DocumentChunkFactory

    doc = DocumentFactory.build(
        user_id=user.id,
        agent_id=None,
        company_id=company.id,
        is_company_rag=True,
        filename="company-handbook.txt",
    )
    db_session.add(doc)
    db_session.flush()

    chunk = DocumentChunkFactory.build(
        document_id=doc.id,
        company_id=company.id,
        chunk_text="The company travel policy reimburses economy flights.",
        embedding_vec=vec,
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.flush()
    return doc


@pytest.mark.asyncio
async def test_company_doc_excluded_when_toggle_off(db_session, test_company):
    from rag_engine import search_similar_texts_for_user
    from tests.factories import UserFactory, AgentFactory

    user = UserFactory.build(company_id=test_company.id)
    db_session.add(user)
    db_session.flush()
    agent = AgentFactory.build(user_id=user.id, company_id=test_company.id)
    db_session.add(agent)
    db_session.flush()

    vec = [1.0] + [0.0] * 1023
    _seed_company_doc_with_chunk(db_session, test_company, user, vec)

    results = search_similar_texts_for_user(
        query_embedding=vec, user_id=user.id, db=db_session,
        top_k=5, agent_id=agent.id, company_id=test_company.id,
        include_company_rag=False,
    )
    assert results == []


@pytest.mark.asyncio
async def test_company_doc_included_when_toggle_on(db_session, test_company):
    from rag_engine import search_similar_texts_for_user
    from tests.factories import UserFactory, AgentFactory

    user = UserFactory.build(company_id=test_company.id)
    db_session.add(user)
    db_session.flush()
    agent = AgentFactory.build(user_id=user.id, company_id=test_company.id)
    db_session.add(agent)
    db_session.flush()

    vec = [1.0] + [0.0] * 1023
    doc = _seed_company_doc_with_chunk(db_session, test_company, user, vec)

    results = search_similar_texts_for_user(
        query_embedding=vec, user_id=user.id, db=db_session,
        top_k=5, agent_id=agent.id, company_id=test_company.id,
        include_company_rag=True,
    )
    assert any(r["document_id"] == doc.id for r in results)
