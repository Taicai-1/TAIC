"""Tests for the company-RAG folder feature.

Part 1 (top): Pure unit tests for _parse_folder_ids / _folder_ids_out helpers.
  These do NOT require a DB and always run.

Part 2 (bottom): DB-backed integration tests for the folder CRUD endpoints.
  These require PostgreSQL and are skipped locally (conftest.py's db_session
  fixture calls pytest.skip when the DB is unreachable) — they run in CI.
"""

import json

import pytest

from routers.agents import _parse_folder_ids, _folder_ids_out

# ---------------------------------------------------------------------------
# Part 1: Pure helper tests (always run, no DB needed)
# ---------------------------------------------------------------------------


def test_parse_folder_ids_empty_means_all():
    assert _parse_folder_ids("") is None
    assert _parse_folder_ids("[]") is None
    assert _parse_folder_ids(None) is None


def test_parse_folder_ids_valid_list():
    # Assert on the parsed value, not exact JSON whitespace.
    assert json.loads(_parse_folder_ids("[1, 2, 3]")) == [1, 2, 3]
    # String-form ids are accepted too.
    assert json.loads(_parse_folder_ids('["4", "5"]')) == [4, 5]


def test_parse_folder_ids_garbage_means_all():
    assert _parse_folder_ids("not json") is None
    assert _parse_folder_ids('{"a":1}') is None


def test_parse_folder_ids_drops_non_positive_and_non_int():
    # Negatives, zero, booleans and non-numeric entries are dropped.
    assert _parse_folder_ids("[-1, 0, 2]") == json.dumps([2])
    assert _parse_folder_ids("[true, false, 3]") == json.dumps([3])
    assert _parse_folder_ids('["x", null, 7]') == json.dumps([7])
    # A list with only invalid ids collapses to None (= all folders).
    assert _parse_folder_ids("[-1, 0]") is None


def test_folder_ids_out_filters_types():
    assert _folder_ids_out(None) == []
    assert _folder_ids_out("[1, 2]") == [1, 2]
    assert _folder_ids_out("garbage") == []
    assert _folder_ids_out('{"a": 1}') == []
    # Corrupt stored data: non-int elements are dropped, bools excluded.
    assert _folder_ids_out('[1, "evil", null, true, 3]') == [1, 3]


def test_parse_then_out_round_trip():
    for raw in ["[1, 2, 3]", "[42]", "[]", None, "", "[-1, 0]"]:
        stored = _parse_folder_ids(raw)
        out = _folder_ids_out(stored)
        assert isinstance(out, list)
        assert all(isinstance(i, int) and not isinstance(i, bool) for i in out)
        if stored is not None:
            assert len(out) > 0


# ---------------------------------------------------------------------------
# Part 2: DB-backed integration tests for folder CRUD endpoints
# ---------------------------------------------------------------------------
# These use the fixtures defined in conftest.py:
#   client, db_session, test_company, test_admin_user, admin_cookies,
#   test_member_user, member_cookies, mock_redis_none, mock_event_tracker
#
# The db_session fixture calls pytest.skip("PostgreSQL not available") when
# the DB is unreachable, so all tests below skip cleanly on dev machines.
# ---------------------------------------------------------------------------


def _make_folder(db_session, company_id, name):
    """Helper: directly insert a CompanyFolder row and return it."""
    from database import CompanyFolder

    folder = CompanyFolder(company_id=company_id, name=name)
    db_session.add(folder)
    db_session.flush()
    return folder


def _make_company_doc(db_session, user_id, company_id, folder_id):
    """Helper: insert a company-RAG Document in the given folder and return it."""
    from tests.factories import DocumentFactory

    doc = DocumentFactory.build(
        user_id=user_id,
        agent_id=None,
        company_id=company_id,
        is_company_rag=True,
        folder_id=folder_id,
    )
    db_session.add(doc)
    db_session.flush()
    return doc


# -- create + list -----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_folder_happy_path(client, admin_cookies, test_company):
    """Admin can create a folder; response includes id, name, document_count=0."""
    resp = await client.post(
        "/api/company-rag/folders",
        json={"name": "Legal"},
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Legal"
    assert body["document_count"] == 0
    assert isinstance(body["id"], int)


@pytest.mark.asyncio
async def test_list_folders_with_document_count(
    client, admin_cookies, member_cookies, db_session, test_company, test_admin_user
):
    """GET /folders returns all folders with accurate document_count; accessible to members."""
    folder = _make_folder(db_session, test_company.id, "HR Docs")
    _make_company_doc(db_session, test_admin_user.id, test_company.id, folder.id)
    _make_company_doc(db_session, test_admin_user.id, test_company.id, folder.id)

    resp = await client.get("/api/company-rag/folders", cookies=member_cookies)
    assert resp.status_code == 200
    folders = resp.json()["folders"]
    match = next((f for f in folders if f["id"] == folder.id), None)
    assert match is not None
    assert match["name"] == "HR Docs"
    assert match["document_count"] == 2


@pytest.mark.asyncio
async def test_create_folder_duplicate_name_409(client, admin_cookies, db_session, test_company):
    """Creating a folder with an already-used name returns 409."""
    _make_folder(db_session, test_company.id, "Finance")

    resp = await client.post(
        "/api/company-rag/folders",
        json={"name": "Finance"},
        cookies=admin_cookies,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_folder_empty_name_400(client, admin_cookies):
    """Creating a folder with a blank name returns 400."""
    resp = await client.post(
        "/api/company-rag/folders",
        json={"name": "   "},
        cookies=admin_cookies,
    )
    assert resp.status_code == 400


# -- rename ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_folder_happy_path(client, admin_cookies, db_session, test_company):
    """Admin can rename a folder; response echoes new name."""
    folder = _make_folder(db_session, test_company.id, "OldName")

    resp = await client.put(
        f"/api/company-rag/folders/{folder.id}",
        json={"name": "NewName"},
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "NewName"
    assert body["id"] == folder.id


@pytest.mark.asyncio
async def test_rename_folder_collision_409(client, admin_cookies, db_session, test_company):
    """Renaming a folder to a name already used by another folder returns 409."""
    _make_folder(db_session, test_company.id, "Existing")
    target = _make_folder(db_session, test_company.id, "ToRename")

    resp = await client.put(
        f"/api/company-rag/folders/{target.id}",
        json={"name": "Existing"},
        cookies=admin_cookies,
    )
    assert resp.status_code == 409


# -- delete ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_empty_folder_200(client, admin_cookies, db_session, test_company):
    """Admin can delete an empty folder; returns status=deleted."""
    folder = _make_folder(db_session, test_company.id, "Empty Folder")

    resp = await client.delete(
        f"/api/company-rag/folders/{folder.id}",
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_delete_non_empty_folder_409(client, admin_cookies, db_session, test_company, test_admin_user):
    """Deleting a folder that still contains documents returns 409 (not 400)."""
    folder = _make_folder(db_session, test_company.id, "Not Empty")
    _make_company_doc(db_session, test_admin_user.id, test_company.id, folder.id)

    resp = await client.delete(
        f"/api/company-rag/folders/{folder.id}",
        cookies=admin_cookies,
    )
    assert resp.status_code == 409


# -- upload requires folder_id -----------------------------------------------


@pytest.mark.asyncio
async def test_upload_without_folder_id_422(client, admin_cookies):
    """POST /documents without folder_id Form field yields HTTP 422 (FastAPI validation)."""
    files = {"file": ("doc.txt", b"content", "text/plain")}
    resp = await client.post(
        "/api/company-rag/documents",
        files=files,
        cookies=admin_cookies,
    )
    assert resp.status_code == 422


# -- move document -----------------------------------------------------------


@pytest.mark.asyncio
async def test_move_document_happy_path(client, admin_cookies, db_session, test_company, test_admin_user):
    """Admin can move a company-RAG document to a different folder."""
    src_folder = _make_folder(db_session, test_company.id, "Source")
    dst_folder = _make_folder(db_session, test_company.id, "Destination")
    doc = _make_company_doc(db_session, test_admin_user.id, test_company.id, src_folder.id)

    resp = await client.put(
        f"/api/company-rag/documents/{doc.id}/folder",
        json={"folder_id": dst_folder.id},
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "moved"
    assert body["folder_id"] == dst_folder.id


@pytest.mark.asyncio
async def test_move_document_wrong_doc_404(client, admin_cookies, db_session, test_company):
    """Moving a non-existent document returns 404."""
    folder = _make_folder(db_session, test_company.id, "SomeFolder")

    resp = await client.put(
        "/api/company-rag/documents/999999/folder",
        json={"folder_id": folder.id},
        cookies=admin_cookies,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_move_document_missing_folder_id_400(client, admin_cookies, db_session, test_company, test_admin_user):
    """Calling move-doc without folder_id in body returns 400."""
    folder = _make_folder(db_session, test_company.id, "AFolder")
    doc = _make_company_doc(db_session, test_admin_user.id, test_company.id, folder.id)

    resp = await client.put(
        f"/api/company-rag/documents/{doc.id}/folder",
        json={},
        cookies=admin_cookies,
    )
    assert resp.status_code == 400


# -- member cannot create ----------------------------------------------------


@pytest.mark.asyncio
async def test_member_cannot_create_folder(client, member_cookies):
    """A plain member (not admin) gets 403 when trying to create a folder."""
    resp = await client.post(
        "/api/company-rag/folders",
        json={"name": "ShouldFail"},
        cookies=member_cookies,
    )
    assert resp.status_code == 403


# -- tenant isolation --------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation_rename_404(client, db_session, test_company):
    """An admin from another company gets 404 when renaming a folder they don't own."""
    from tests.factories import CompanyFactory, UserFactory, CompanyMembershipFactory
    from auth import create_access_token

    # Create a folder in the main test_company.
    folder = _make_folder(db_session, test_company.id, "MainCompanyFolder")

    # Create a completely different company with its own admin.
    other_company = CompanyFactory.build()
    db_session.add(other_company)
    db_session.flush()

    other_admin = UserFactory.build(company_id=other_company.id)
    db_session.add(other_admin)
    db_session.flush()

    membership = CompanyMembershipFactory.build(user_id=other_admin.id, company_id=other_company.id, role="admin")
    db_session.add(membership)
    db_session.flush()

    other_token = create_access_token(data={"sub": str(other_admin.id)})
    other_cookies = {"token": other_token}

    resp = await client.put(
        f"/api/company-rag/folders/{folder.id}",
        json={"name": "Hijacked"},
        cookies=other_cookies,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_tenant_isolation_delete_404(client, db_session, test_company):
    """An admin from another company gets 404 when deleting a folder they don't own."""
    from tests.factories import CompanyFactory, UserFactory, CompanyMembershipFactory
    from auth import create_access_token

    folder = _make_folder(db_session, test_company.id, "ProtectedFolder")

    other_company = CompanyFactory.build()
    db_session.add(other_company)
    db_session.flush()

    other_admin = UserFactory.build(company_id=other_company.id)
    db_session.add(other_admin)
    db_session.flush()

    membership = CompanyMembershipFactory.build(user_id=other_admin.id, company_id=other_company.id, role="admin")
    db_session.add(membership)
    db_session.flush()

    other_token = create_access_token(data={"sub": str(other_admin.id)})
    other_cookies = {"token": other_token}

    resp = await client.delete(
        f"/api/company-rag/folders/{folder.id}",
        cookies=other_cookies,
    )
    assert resp.status_code == 404
