"""Integration tests for conversation endpoints."""

import pytest
from database import Conversation, Message


@pytest.mark.asyncio
async def test_create_conversation(client, auth_cookies, test_agent):
    """Test POST /conversations - create conversation."""
    response = await client.post(
        "/conversations",
        json={"agent_id": test_agent.id, "title": "Test Conversation"},
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    data = response.json()
    assert "conversation_id" in data
    assert isinstance(data["conversation_id"], int)


@pytest.mark.asyncio
async def test_create_conversation_missing_id(client, auth_cookies):
    """Test POST /conversations - should fail without agent_id or team_id."""
    response = await client.post(
        "/conversations",
        json={"title": "Test Conversation"},
        cookies=auth_cookies,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_conversations(client, auth_cookies, test_agent, test_conversation):
    """Test GET /conversations?agent_id=X - list conversations."""
    response = await client.get(
        f"/conversations?agent_id={test_agent.id}",
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Verify the test_conversation is in the list
    conv_ids = [c["id"] for c in data]
    assert test_conversation.id in conv_ids


@pytest.mark.asyncio
async def test_list_conversations_no_params(client, auth_cookies):
    """Test GET /conversations without agent_id - should require agent_id or team_id."""
    response = await client.get(
        "/conversations",
        cookies=auth_cookies,
    )
    assert response.status_code == 422
    data = response.json()
    assert "agent_id ou team_id doit être fourni" in data["detail"]


@pytest.mark.asyncio
async def test_add_message(client, auth_cookies, test_conversation):
    """Test POST /conversations/{id}/messages - add a message."""
    response = await client.post(
        f"/conversations/{test_conversation.id}/messages",
        json={"conversation_id": test_conversation.id, "role": "user", "content": "Test message content"},
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    data = response.json()
    assert "message_id" in data
    assert isinstance(data["message_id"], int)


@pytest.mark.asyncio
async def test_get_messages(client, auth_cookies, test_conversation, db_session):
    """Test GET /conversations/{id}/messages - list messages."""
    # Add a message first
    msg = Message(conversation_id=test_conversation.id, role="user", content="Test message content")
    db_session.add(msg)
    db_session.commit()

    response = await client.get(
        f"/conversations/{test_conversation.id}/messages",
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Verify message structure
    assert "id" in data[0]
    assert "role" in data[0]
    assert "content" in data[0]
    assert "timestamp" in data[0]


@pytest.mark.asyncio
async def test_update_conversation_title(client, auth_cookies, test_conversation):
    """Test PUT /conversations/{id}/title - update title."""
    new_title = "Updated Title"
    response = await client.put(
        f"/conversations/{test_conversation.id}/title",
        json={"title": new_title},
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == test_conversation.id
    assert data["title"] == new_title


@pytest.mark.asyncio
async def test_delete_conversation(client, auth_cookies, test_conversation, db_session):
    """Test DELETE /conversations/{id} - delete conversation."""
    conv_id = test_conversation.id
    response = await client.delete(
        f"/conversations/{conv_id}",
        cookies=auth_cookies,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Conversation deleted"

    # Verify the conversation is deleted
    db_session.expire_all()
    deleted_conv = db_session.query(Conversation).filter(Conversation.id == conv_id).first()
    assert deleted_conv is None


@pytest.mark.asyncio
async def test_get_messages_nonexistent_conversation(client, auth_cookies):
    """Test GET /conversations/99999/messages - 404 for nonexistent conversation."""
    response = await client.get(
        "/conversations/99999/messages",
        cookies=auth_cookies,
    )
    assert response.status_code == 404
    data = response.json()
    assert "Conversation not found" in data["detail"]


@pytest.mark.asyncio
async def test_unauthenticated_access(client, test_conversation):
    """Test that unauthenticated requests are rejected."""
    response = await client.get(f"/conversations/{test_conversation.id}/messages")
    assert response.status_code == 401
