"""Integration tests for document management endpoints."""

import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.mark.asyncio
async def test_list_documents_empty(client, auth_cookies, test_user):
    """User with no documents should get empty list."""
    resp = await client.get("/user/documents", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "documents" in data
    assert len(data["documents"]) == 0


@pytest.mark.asyncio
async def test_list_documents_with_document(client, auth_cookies, test_document):
    """User should see their own documents."""
    resp = await client.get("/user/documents", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "documents" in data
    assert len(data["documents"]) == 1
    doc = data["documents"][0]
    assert doc["id"] == test_document.id
    assert doc["filename"] == test_document.filename
    assert doc["agent_id"] == test_document.agent_id


@pytest.mark.asyncio
async def test_list_documents_filter_by_agent(client, auth_cookies, test_document, test_agent):
    """User should be able to filter documents by agent_id."""
    resp = await client.get(f"/user/documents?agent_id={test_agent.id}", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "documents" in data
    assert len(data["documents"]) == 1
    doc = data["documents"][0]
    assert doc["agent_id"] == test_agent.id


@pytest.mark.asyncio
async def test_delete_document_owner(client, auth_cookies, test_document):
    """Owner should be able to delete their document."""
    resp = await client.delete(f"/documents/{test_document.id}", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert data["message"] == "Document deleted successfully"

    # Verify document is gone
    resp = await client.get("/user/documents", cookies=auth_cookies)
    data = resp.json()
    assert len(data["documents"]) == 0


@pytest.mark.asyncio
async def test_delete_document_not_found(client, auth_cookies):
    """Deleting nonexistent document should return 404."""
    resp = await client.delete("/documents/99999", cookies=auth_cookies)
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_upload_txt_file(client, auth_cookies, test_user, mock_event_tracker):
    """Uploading a TXT file should succeed."""
    # Mock the process_document_for_user function to avoid actual processing
    with patch("routers.documents.process_document_for_user", return_value=123) as mock_process:
        fixture_path = Path(__file__).parent / "fixtures" / "sample.txt"
        with open(fixture_path, "rb") as f:
            files = {"file": ("test.txt", f, "text/plain")}
            resp = await client.post("/upload", files=files, cookies=auth_cookies)

        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.txt"
        assert data["document_id"] == 123
        assert data["status"] == "uploaded"

        # Verify process_document_for_user was called
        mock_process.assert_called_once()
        call_args = mock_process.call_args
        assert call_args[0][0] == "test.txt"  # filename
        assert call_args[0][2] == int(test_user.id)  # user_id


@pytest.mark.asyncio
async def test_upload_unsupported_file_type(client, auth_cookies):
    """Uploading unsupported file type should return 400."""
    files = {"file": ("test.exe", b"fake content", "application/x-msdownload")}
    resp = await client.post("/upload", files=files, cookies=auth_cookies)

    assert resp.status_code == 400
    data = resp.json()
    assert "detail" in data
    assert "not allowed" in data["detail"].lower()


@pytest.mark.asyncio
async def test_upload_unauthenticated(client):
    """Uploading without authentication should return 401."""
    files = {"file": ("test.txt", b"content", "text/plain")}
    resp = await client.post("/upload", files=files)

    assert resp.status_code == 401
