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


def _give_company(db_session, user, agent):
    """Assign a real company to the user + agent.

    The default test_user/test_agent fixtures have company_id=None, but
    search_similar_texts_for_user refuses to run without a resolvable tenant
    (returns [] to avoid a cross-tenant leak), so retrieval tests must set one.
    """
    from tests.factories import CompanyFactory

    company = CompanyFactory.build()
    db_session.add(company)
    db_session.flush()
    user.company_id = company.id
    agent.company_id = company.id
    db_session.add(user)
    db_session.add(agent)
    db_session.flush()
    return company.id


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
    r_delete = await client.delete(f"/api/agents/{test_agent.id}/folders/{folder_b.id}", cookies=auth_cookies)
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
    resp = await client.post(f"/api/agents/{test_agent.id}/folders", json={"name": "x" * 101}, cookies=auth_cookies)
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
    client, auth_cookies, db_session, test_agent, mock_gcs, mock_event_tracker, monkeypatch
):
    """With Redis off, /upload-agent stores the doc in the given folder (sync path)."""
    # documents.py imports get_redis by value, so patch it on that module directly.
    import routers.documents as docs_router

    monkeypatch.setattr(docs_router, "get_redis", lambda: None)

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


@pytest.mark.asyncio
async def test_upload_into_folder_async(client, auth_cookies, db_session, test_agent, monkeypatch):
    """With Redis on, /upload-agent schedules the background worker with agent_folder_id."""
    import fakeredis
    from unittest.mock import MagicMock
    import routers.documents as docs_router

    folder = _make_folder(db_session, test_agent, "CibleAsync")

    # documents.py imports get_redis by value; patch it on that module so the
    # endpoint takes the async (Redis-available) path. fakeredis backs r.setex(...).
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(docs_router, "get_redis", lambda: fake)

    captured = MagicMock()
    monkeypatch.setattr(docs_router, "_process_document_background", captured)

    files = {"file": ("note.txt", b"contenu", "text/plain")}
    data = {"agent_id": str(test_agent.id), "folder_id": str(folder.id)}
    resp = await client.post("/upload-agent", files=files, data=data, cookies=auth_cookies)
    assert resp.status_code == 200

    assert captured.called
    _, kwargs = captured.call_args
    assert kwargs.get("agent_folder_id") == folder.id


# -- retrieval filtering -----------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_folder_ids_helper(db_session, test_agent):
    """The helper returns only the agent's inactive folder ids."""
    from rag_engine import _inactive_agent_folder_ids

    active = _make_folder(db_session, test_agent, "Actif", is_active=True)
    inactive = _make_folder(db_session, test_agent, "Inactif", is_active=False)

    ids = _inactive_agent_folder_ids(test_agent.id, db_session)
    assert inactive.id in ids
    assert active.id not in ids


@pytest.mark.asyncio
async def test_retrieval_excludes_inactive_folder(db_session, test_user, test_agent):
    """search_similar_texts_for_user returns docs from active/no folder, not inactive."""
    from rag_engine import search_similar_texts_for_user
    from database import DocumentChunk

    _give_company(db_session, test_user, test_agent)
    active = _make_folder(db_session, test_agent, "RetrActive", is_active=True)
    inactive = _make_folder(db_session, test_agent, "RetrInactive", is_active=False)

    # One non-zero unit vector so cosine_distance is well-defined (dim 1024).
    vec = [1.0] + [0.0] * 1023

    def _doc_with_chunk(folder_id, fname):
        doc = _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=folder_id)
        doc.filename = fname
        chunk = DocumentChunk(
            document_id=doc.id,
            company_id=test_agent.company_id,
            chunk_text=f"chunk {fname}",
            embedding_vec=vec,
            chunk_index=0,
        )
        db_session.add(chunk)
        db_session.flush()
        return doc

    _doc_with_chunk(None, "no_folder.txt")
    _doc_with_chunk(active.id, "active.txt")
    _doc_with_chunk(inactive.id, "inactive.txt")

    results = search_similar_texts_for_user(
        vec, test_user.id, db_session, top_k=10, agent_id=test_agent.id, company_id=test_agent.company_id
    )
    filenames = {r["document_name"] for r in results}
    assert "no_folder.txt" in filenames
    assert "active.txt" in filenames
    assert "inactive.txt" not in filenames


@pytest.mark.asyncio
async def test_retrieval_no_inactive_folder_returns_all(db_session, test_user, test_agent):
    """When all folders are active, agent retrieval returns its docs unchanged."""
    from rag_engine import search_similar_texts_for_user
    from database import DocumentChunk

    _give_company(db_session, test_user, test_agent)
    active = _make_folder(db_session, test_agent, "AlwaysActive", is_active=True)
    vec = [1.0] + [0.0] * 1023
    doc = _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=active.id)
    doc.filename = "should_appear.txt"
    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            company_id=test_agent.company_id,
            chunk_text="content",
            embedding_vec=vec,
            chunk_index=0,
        )
    )
    db_session.flush()

    results = search_similar_texts_for_user(
        vec, test_user.id, db_session, top_k=10, agent_id=test_agent.id, company_id=test_agent.company_id
    )
    assert any(r["document_name"] == "should_appear.txt" for r in results)


@pytest.mark.asyncio
async def test_inactive_folder_ids_helper_is_agent_scoped(db_session, test_user, test_agent):
    """_inactive_agent_folder_ids only returns the queried agent's inactive folders."""
    from rag_engine import _inactive_agent_folder_ids
    from tests.factories import AgentFactory

    agent_b = AgentFactory.build(user_id=test_user.id, company_id=test_agent.company_id)
    db_session.add(agent_b)
    db_session.flush()

    mine_inactive = _make_folder(db_session, test_agent, "MineInactive", is_active=False)
    other_inactive = _make_folder(db_session, agent_b, "OtherInactive", is_active=False)

    ids = _inactive_agent_folder_ids(test_agent.id, db_session)
    assert mine_inactive.id in ids
    assert other_inactive.id not in ids


# -- sources endpoint --------------------------------------------------------


@pytest.mark.asyncio
async def test_sources_includes_folders_and_doc_folder_id(client, auth_cookies, db_session, test_user, test_agent):
    folder = _make_folder(db_session, test_agent, "SourcesFolder")
    _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=folder.id)

    resp = await client.get(f"/api/agents/{test_agent.id}/sources", cookies=auth_cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert any(f["id"] == folder.id and f["is_active"] is True for f in body["folders"])
    assert all("agent_folder_id" in d for d in body["documents"])
    assert any(d["agent_folder_id"] == folder.id for d in body["documents"])


# -- rag cache key -----------------------------------------------------------


def test_rag_cache_key_varies_with_inactive_folders():
    """The cache key changes when the inactive-folder signature changes."""
    from rag_engine import _rag_cache_key

    base = _rag_cache_key(1, "q", [1, 2], "conversationnel", extra="")
    toggled = _rag_cache_key(1, "q", [1, 2], "conversationnel", extra="7")
    assert base != toggled
    # Same inputs => same key (stable).
    assert base == _rag_cache_key(1, "q", [1, 2], "conversationnel", extra="")


# -- folder tree expansion (pure, runs locally) ------------------------------


def test_descendant_folder_ids_basic():
    from rag_engine import _descendant_folder_ids

    # tree: 1 -> 2 -> 4, 1 -> 3
    pairs = [(1, None), (2, 1), (3, 1), (4, 2), (5, None)]
    assert _descendant_folder_ids([1], pairs) == {1, 2, 3, 4}
    assert _descendant_folder_ids([2], pairs) == {2, 4}
    assert _descendant_folder_ids([5], pairs) == {5}
    assert _descendant_folder_ids([], pairs) == set()


def test_descendant_folder_ids_cycle_safe():
    from rag_engine import _descendant_folder_ids

    # defensive: a malformed cycle must not loop forever
    pairs = [(1, 2), (2, 1)]
    assert _descendant_folder_ids([1], pairs) == {1, 2}


@pytest.mark.asyncio
async def test_retrieval_excludes_inactive_parent_subtree(db_session, test_user, test_agent):
    """An inactive PARENT folder excludes documents sitting in its child subfolder."""
    from rag_engine import search_similar_texts_for_user
    from database import DocumentChunk
    from tests.factories import AgentFolderFactory

    _give_company(db_session, test_user, test_agent)

    parent = AgentFolderFactory.build(
        agent_id=test_agent.id, company_id=test_agent.company_id, name="Parent", is_active=False
    )
    db_session.add(parent)
    db_session.flush()
    child = AgentFolderFactory.build(
        agent_id=test_agent.id, company_id=test_agent.company_id, name="Child", is_active=True, parent_id=parent.id
    )
    db_session.add(child)
    db_session.flush()

    vec = [1.0] + [0.0] * 1023
    doc = _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=child.id)
    doc.filename = "in_child.txt"
    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            company_id=test_agent.company_id,
            chunk_text="content",
            embedding_vec=vec,
            chunk_index=0,
        )
    )
    db_session.flush()

    results = search_similar_texts_for_user(
        vec, test_user.id, db_session, top_k=10, agent_id=test_agent.id, company_id=test_agent.company_id
    )
    assert all(r["document_name"] != "in_child.txt" for r in results)


# -- subfolders (companion) --------------------------------------------------


@pytest.mark.asyncio
async def test_create_subfolder(client, auth_cookies, db_session, test_agent):
    parent = _make_folder(db_session, test_agent, "Parent")
    resp = await client.post(
        f"/api/agents/{test_agent.id}/folders",
        json={"name": "Child", "parent_id": parent.id},
        cookies=auth_cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["parent_id"] == parent.id


@pytest.mark.asyncio
async def test_create_subfolder_bad_parent_404(client, auth_cookies, test_agent):
    resp = await client.post(
        f"/api/agents/{test_agent.id}/folders",
        json={"name": "Child", "parent_id": 999999},
        cookies=auth_cookies,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_same_name_under_different_parents_ok(client, auth_cookies, db_session, test_agent):
    p1 = _make_folder(db_session, test_agent, "P1")
    p2 = _make_folder(db_session, test_agent, "P2")
    r1 = await client.post(
        f"/api/agents/{test_agent.id}/folders", json={"name": "2024", "parent_id": p1.id}, cookies=auth_cookies
    )
    r2 = await client.post(
        f"/api/agents/{test_agent.id}/folders", json={"name": "2024", "parent_id": p2.id}, cookies=auth_cookies
    )
    assert r1.status_code == 200 and r2.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_name_same_parent_409(client, auth_cookies, db_session, test_agent):
    parent = _make_folder(db_session, test_agent, "Parent2")
    await client.post(
        f"/api/agents/{test_agent.id}/folders", json={"name": "Dup", "parent_id": parent.id}, cookies=auth_cookies
    )
    r2 = await client.post(
        f"/api/agents/{test_agent.id}/folders", json={"name": "Dup", "parent_id": parent.id}, cookies=auth_cookies
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_list_returns_parent_id(client, auth_cookies, db_session, test_agent):
    parent = _make_folder(db_session, test_agent, "ListParent")
    resp = await client.get(f"/api/agents/{test_agent.id}/folders", cookies=auth_cookies)
    assert resp.status_code == 200
    match = next(f for f in resp.json()["folders"] if f["id"] == parent.id)
    assert "parent_id" in match and match["parent_id"] is None


@pytest.mark.asyncio
async def test_delete_folder_with_subfolder_409(client, auth_cookies, db_session, test_agent):
    parent = _make_folder(db_session, test_agent, "HasChild")
    from tests.factories import AgentFolderFactory

    child = AgentFolderFactory.build(
        agent_id=test_agent.id, company_id=test_agent.company_id, name="C", parent_id=parent.id
    )
    db_session.add(child)
    db_session.flush()
    resp = await client.delete(f"/api/agents/{test_agent.id}/folders/{parent.id}", cookies=auth_cookies)
    assert resp.status_code == 409


# -- folder import (companion) -----------------------------------------------


def _fake_agent_ingest(filename, content, user_id, db, agent_id=None, company_id=None, agent_folder_id=None, **kw):
    """Stand-in for process_document_for_user: insert a Document row, skip GCS/embeddings."""
    from database import Document

    doc = Document(
        filename=filename,
        user_id=user_id,
        agent_id=agent_id,
        company_id=company_id,
        agent_folder_id=agent_folder_id,
        document_type="rag",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc.id


@pytest.mark.asyncio
async def test_import_creates_tree_and_docs(client, auth_cookies, db_session, test_agent, mock_redis_none):
    """Import recreates the directory tree and attaches docs to the right subfolder."""
    from unittest.mock import patch

    from database import AgentFolder, Document

    files = [
        ("files", ("a.txt", b"hello world", "text/plain")),
        ("files", ("b.txt", b"second file", "text/plain")),
        ("files", ("skip.exe", b"MZ", "application/octet-stream")),
    ]
    data = {"paths": ["Root/Sub/a.txt", "Root/b.txt", "Root/Sub/skip.exe"]}
    with patch("routers.agent_folders.process_document_for_user", side_effect=_fake_agent_ingest):
        resp = await client.post(
            f"/api/agents/{test_agent.id}/folders/import", files=files, data=data, cookies=auth_cookies
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["done"] == 2 and body["skipped"] == 1

    root = (
        db_session.query(AgentFolder)
        .filter(
            AgentFolder.agent_id == test_agent.id,
            AgentFolder.name == "Root",
            AgentFolder.parent_id.is_(None),
        )
        .first()
    )
    assert root is not None
    sub = (
        db_session.query(AgentFolder)
        .filter(
            AgentFolder.agent_id == test_agent.id,
            AgentFolder.name == "Sub",
            AgentFolder.parent_id == root.id,
        )
        .first()
    )
    assert sub is not None
    a_doc = db_session.query(Document).filter(Document.agent_id == test_agent.id, Document.filename == "a.txt").first()
    assert a_doc.agent_folder_id == sub.id


@pytest.mark.asyncio
async def test_import_merges_into_existing_folder(client, auth_cookies, db_session, test_agent, mock_redis_none):
    from unittest.mock import patch

    from database import AgentFolder

    existing = _make_folder(db_session, test_agent, "Root")
    with patch("routers.agent_folders.process_document_for_user", side_effect=_fake_agent_ingest):
        resp = await client.post(
            f"/api/agents/{test_agent.id}/folders/import",
            files=[("files", ("a.txt", b"hi", "text/plain"))],
            data={"paths": ["Root/a.txt"]},
            cookies=auth_cookies,
        )
    assert resp.status_code == 200
    roots = (
        db_session.query(AgentFolder)
        .filter(
            AgentFolder.agent_id == test_agent.id,
            AgentFolder.name == "Root",
            AgentFolder.parent_id.is_(None),
        )
        .all()
    )
    assert len(roots) == 1 and roots[0].id == existing.id  # merged, not duplicated


@pytest.mark.asyncio
async def test_import_rejects_too_many_files(client, auth_cookies, test_agent, monkeypatch):
    import routers.agent_folders as af

    monkeypatch.setattr(af, "MAX_IMPORT_FILES", 1)
    files = [
        ("files", ("a.txt", b"x", "text/plain")),
        ("files", ("b.txt", b"y", "text/plain")),
    ]
    data = {"paths": ["R/a.txt", "R/b.txt"]}
    resp = await client.post(
        f"/api/agents/{test_agent.id}/folders/import", files=files, data=data, cookies=auth_cookies
    )
    assert resp.status_code == 413
