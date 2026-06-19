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
        query_embedding=vec,
        user_id=user.id,
        db=db_session,
        top_k=5,
        agent_id=agent.id,
        company_id=test_company.id,
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
        query_embedding=vec,
        user_id=user.id,
        db=db_session,
        top_k=5,
        agent_id=agent.id,
        company_id=test_company.id,
        include_company_rag=True,
    )
    assert any(r["document_id"] == doc.id for r in results)


from unittest.mock import patch


@pytest.mark.asyncio
async def test_member_cannot_upload_company_doc(client, member_cookies):
    # folder_id is a required form field (validated before the handler); supply
    # one so the request reaches the role check, which is what we assert (403).
    files = {"file": ("policy.txt", b"hello company", "text/plain")}
    resp = await client.post("/api/company-rag/documents", files=files, data={"folder_id": "1"}, cookies=member_cookies)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_uploads_company_doc(
    client, admin_cookies, test_admin_user, db_session, mock_redis_none, mock_event_tracker
):
    from database import CompanyFolder

    folder = CompanyFolder(company_id=test_admin_user.company_id, name="Général")
    db_session.add(folder)
    db_session.flush()

    with patch("routers.company_rag.process_document_for_user", return_value=777) as mock_proc:
        files = {"file": ("policy.txt", b"hello company", "text/plain")}
        resp = await client.post(
            "/api/company-rag/documents", files=files, data={"folder_id": str(folder.id)}, cookies=admin_cookies
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["document_id"] == 777
    kwargs = mock_proc.call_args.kwargs
    assert kwargs["is_company_rag"] is True
    assert kwargs["agent_id"] is None
    assert kwargs["company_id"] == test_admin_user.company_id


@pytest.mark.asyncio
async def test_member_can_list_company_docs(client, member_cookies, db_session, test_company, test_member_user):
    from tests.factories import DocumentFactory

    doc = DocumentFactory.build(
        user_id=test_member_user.id,
        agent_id=None,
        company_id=test_company.id,
        is_company_rag=True,
        filename="shared.txt",
    )
    db_session.add(doc)
    db_session.flush()

    resp = await client.get("/api/company-rag/documents", cookies=member_cookies)
    assert resp.status_code == 200
    names = [d["filename"] for d in resp.json()["documents"]]
    assert "shared.txt" in names


@pytest.mark.asyncio
async def test_admin_deletes_company_doc(client, admin_cookies, db_session, test_admin_user):
    from tests.factories import DocumentFactory

    doc = DocumentFactory.build(
        user_id=test_admin_user.id,
        agent_id=None,
        company_id=test_admin_user.company_id,
        is_company_rag=True,
        filename="to-delete.txt",
    )
    db_session.add(doc)
    db_session.flush()

    resp = await client.delete(f"/api/company-rag/documents/{doc.id}", cookies=admin_cookies)
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    from database import Document

    assert db_session.query(Document).filter(Document.id == doc.id).first() is None


@pytest.mark.asyncio
async def test_member_can_get_download_url_for_company_doc(
    client, member_cookies, db_session, test_company, test_admin_user, mock_gcs
):
    from tests.factories import DocumentFactory

    doc = DocumentFactory.build(
        user_id=test_admin_user.id,
        agent_id=None,
        company_id=test_company.id,
        is_company_rag=True,
        filename="shared.pdf",
        gcs_url="https://storage.googleapis.com/test-bucket/shared.pdf",
    )
    db_session.add(doc)
    db_session.flush()
    resp = await client.get(f"/documents/{doc.id}/download-url", cookies=member_cookies)
    # Member is in the same company as the uploader (test_admin_user) -> never 403
    assert resp.status_code != 403
