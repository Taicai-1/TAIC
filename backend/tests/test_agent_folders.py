"""DB-backed tests for the companion-RAG folder feature (skipped locally, run in CI)."""

import pytest


def _make_folder(db_session, agent, name, is_active=True):
    from tests.factories import AgentFolderFactory

    folder = AgentFolderFactory.build(agent_id=agent.id, company_id=agent.company_id, name=name, is_active=is_active)
    db_session.add(folder)
    db_session.flush()
    return folder


def _make_agent_doc(db_session, user_id, agent, agent_folder_id=None):
    from tests.factories import DocumentFactory

    doc = DocumentFactory.build(
        user_id=user_id, agent_id=agent.id, company_id=agent.company_id, agent_folder_id=agent_folder_id
    )
    db_session.add(doc)
    db_session.flush()
    return doc


# -- create + list -----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_folder_happy_path(client, auth_cookies, test_agent):
    resp = await client.post(f"/api/agents/{test_agent.id}/folders", json={"name": "Contrats"}, cookies=auth_cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Contrats"
    assert body["is_active"] is True
    assert body["document_count"] == 0
    assert isinstance(body["id"], int)


@pytest.mark.asyncio
async def test_list_folders_with_counts(client, auth_cookies, db_session, test_user, test_agent):
    folder = _make_folder(db_session, test_agent, "RH")
    _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=folder.id)
    _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=None)  # sans dossier

    resp = await client.get(f"/api/agents/{test_agent.id}/folders", cookies=auth_cookies)
    assert resp.status_code == 200
    body = resp.json()
    match = next((f for f in body["folders"] if f["id"] == folder.id), None)
    assert match is not None
    assert match["name"] == "RH"
    assert match["document_count"] == 1
    assert body["uncategorized_count"] == 1


@pytest.mark.asyncio
async def test_create_folder_duplicate_409(client, auth_cookies, db_session, test_agent):
    _make_folder(db_session, test_agent, "Finance")
    resp = await client.post(f"/api/agents/{test_agent.id}/folders", json={"name": "Finance"}, cookies=auth_cookies)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_folder_empty_name_400(client, auth_cookies, test_agent):
    resp = await client.post(f"/api/agents/{test_agent.id}/folders", json={"name": "   "}, cookies=auth_cookies)
    assert resp.status_code == 400


# -- rename + toggle ---------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_folder(client, auth_cookies, db_session, test_agent):
    folder = _make_folder(db_session, test_agent, "Old")
    resp = await client.put(
        f"/api/agents/{test_agent.id}/folders/{folder.id}", json={"name": "New"}, cookies=auth_cookies
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


@pytest.mark.asyncio
async def test_toggle_folder_active(client, auth_cookies, db_session, test_agent):
    folder = _make_folder(db_session, test_agent, "Archive", is_active=True)
    resp = await client.put(
        f"/api/agents/{test_agent.id}/folders/{folder.id}", json={"is_active": False}, cookies=auth_cookies
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_rename_collision_409(client, auth_cookies, db_session, test_agent):
    _make_folder(db_session, test_agent, "Existing")
    target = _make_folder(db_session, test_agent, "ToRename")
    resp = await client.put(
        f"/api/agents/{test_agent.id}/folders/{target.id}", json={"name": "Existing"}, cookies=auth_cookies
    )
    assert resp.status_code == 409


# -- delete ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_empty_folder(client, auth_cookies, db_session, test_agent):
    folder = _make_folder(db_session, test_agent, "Empty")
    resp = await client.delete(f"/api/agents/{test_agent.id}/folders/{folder.id}", cookies=auth_cookies)
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_delete_non_empty_folder_409(client, auth_cookies, db_session, test_user, test_agent):
    folder = _make_folder(db_session, test_agent, "Full")
    _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=folder.id)
    resp = await client.delete(f"/api/agents/{test_agent.id}/folders/{folder.id}", cookies=auth_cookies)
    assert resp.status_code == 409


# -- move document -----------------------------------------------------------


@pytest.mark.asyncio
async def test_move_document_to_folder(client, auth_cookies, db_session, test_user, test_agent):
    src = _make_folder(db_session, test_agent, "Src")
    dst = _make_folder(db_session, test_agent, "Dst")
    doc = _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=src.id)
    resp = await client.put(
        f"/api/agents/{test_agent.id}/documents/{doc.id}/folder", json={"folder_id": dst.id}, cookies=auth_cookies
    )
    assert resp.status_code == 200
    assert resp.json()["folder_id"] == dst.id


@pytest.mark.asyncio
async def test_move_document_to_uncategorized(client, auth_cookies, db_session, test_user, test_agent):
    src = _make_folder(db_session, test_agent, "Src2")
    doc = _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=src.id)
    resp = await client.put(
        f"/api/agents/{test_agent.id}/documents/{doc.id}/folder", json={"folder_id": None}, cookies=auth_cookies
    )
    assert resp.status_code == 200
    assert resp.json()["folder_id"] is None


@pytest.mark.asyncio
async def test_move_document_wrong_doc_404(client, auth_cookies, db_session, test_agent):
    folder = _make_folder(db_session, test_agent, "F")
    resp = await client.put(
        f"/api/agents/{test_agent.id}/documents/999999/folder", json={"folder_id": folder.id}, cookies=auth_cookies
    )
    assert resp.status_code == 404


# -- permissions -------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_owner_cannot_create_folder(client, db_session, test_agent):
    """A different user with no share on the agent gets 403."""
    from tests.factories import UserFactory
    from auth import create_access_token

    other = UserFactory.build()
    db_session.add(other)
    db_session.flush()
    other_cookies = {"token": create_access_token(data={"sub": str(other.id)})}

    resp = await client.post(f"/api/agents/{test_agent.id}/folders", json={"name": "Nope"}, cookies=other_cookies)
    assert resp.status_code == 403


# -- cross-agent isolation ---------------------------------------------------


@pytest.mark.asyncio
async def test_cross_agent_folder_isolation(client, auth_cookies, db_session, test_user, test_agent):
    """A folder owned by agent B is not reachable through agent A's path (404)."""
    from tests.factories import AgentFactory

    agent_b = AgentFactory.build(user_id=test_user.id, company_id=test_agent.company_id)
    db_session.add(agent_b)
    db_session.flush()
    folder_b = _make_folder(db_session, agent_b, "B-Folder")

    r_rename = await client.put(
        f"/api/agents/{test_agent.id}/folders/{folder_b.id}", json={"name": "X"}, cookies=auth_cookies
    )
    assert r_rename.status_code == 404
    r_delete = await client.delete(
        f"/api/agents/{test_agent.id}/folders/{folder_b.id}", cookies=auth_cookies
    )
    assert r_delete.status_code == 404


@pytest.mark.asyncio
async def test_move_into_other_agent_folder_404(client, auth_cookies, db_session, test_user, test_agent):
    """Cannot move agent A's document into agent B's folder (404)."""
    from tests.factories import AgentFactory

    agent_b = AgentFactory.build(user_id=test_user.id, company_id=test_agent.company_id)
    db_session.add(agent_b)
    db_session.flush()
    folder_b = _make_folder(db_session, agent_b, "B-Folder2")
    doc_a = _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=None)

    resp = await client.put(
        f"/api/agents/{test_agent.id}/documents/{doc_a.id}/folder",
        json={"folder_id": folder_b.id},
        cookies=auth_cookies,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_folder_name_too_long_400(client, auth_cookies, test_agent):
    resp = await client.post(
        f"/api/agents/{test_agent.id}/folders", json={"name": "x" * 101}, cookies=auth_cookies
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_traceability_doc_not_counted_or_blocking(client, auth_cookies, db_session, test_user, test_agent):
    """A non-rag doc in a folder is excluded from counts and does not block deletion."""
    from tests.factories import DocumentFactory

    folder = _make_folder(db_session, test_agent, "OnlyTrace")
    trace = DocumentFactory.build(
        user_id=test_user.id,
        agent_id=test_agent.id,
        company_id=test_agent.company_id,
        agent_folder_id=folder.id,
        document_type="traceability",
    )
    db_session.add(trace)
    db_session.flush()

    lst = await client.get(f"/api/agents/{test_agent.id}/folders", cookies=auth_cookies)
    match = next(f for f in lst.json()["folders"] if f["id"] == folder.id)
    assert match["document_count"] == 0

    dele = await client.delete(f"/api/agents/{test_agent.id}/folders/{folder.id}", cookies=auth_cookies)
    assert dele.status_code == 200


# -- upload into a folder ----------------------------------------------------


@pytest.mark.asyncio
async def test_upload_into_folder_sync(
    client, auth_cookies, db_session, test_agent, mock_redis_none, mock_gcs, mock_event_tracker, monkeypatch
):
    """With Redis off, /upload-agent stores the doc in the given folder (sync path)."""
    folder = _make_folder(db_session, test_agent, "Cible")

    # Avoid real embeddings: stub ingest to create a Document directly.
    import rag_engine
    from database import Document

    def _fake_ingest(text_content, filename, user_id, agent_id, db, **kwargs):
        doc = Document(
            filename=filename,
            content=text_content,
            user_id=user_id,
            agent_id=agent_id,
            company_id=kwargs.get("company_id"),
            agent_folder_id=kwargs.get("agent_folder_id"),
            document_type="rag",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc.id

    monkeypatch.setattr(rag_engine, "ingest_text_content", _fake_ingest)

    files = {"file": ("note.txt", b"contenu de test", "text/plain")}
    data = {"agent_id": str(test_agent.id), "folder_id": str(folder.id)}
    resp = await client.post("/upload-agent", files=files, data=data, cookies=auth_cookies)
    assert resp.status_code == 200

    doc = db_session.query(Document).filter(Document.agent_id == test_agent.id).order_by(Document.id.desc()).first()
    assert doc is not None
    assert doc.agent_folder_id == folder.id
