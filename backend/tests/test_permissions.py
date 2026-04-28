"""Permission and multi-tenant isolation tests."""

import pytest
from auth import create_access_token
from tests.factories import UserFactory, AgentFactory, AgentShareFactory, ConversationFactory, DocumentFactory


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_agent(client, db_session, test_user, test_agent, test_user_token):
    """User A cannot GET User B's agent (should be 403)."""
    # Create another user with an agent
    other_user = UserFactory.build()
    db_session.add(other_user)
    db_session.flush()

    other_agent = AgentFactory.build(user_id=other_user.id)
    db_session.add(other_agent)
    db_session.flush()

    # test_user tries to access other_user's agent
    response = await client.get(
        f"/agents/{other_agent.id}",
        cookies={"token": test_user_token}
    )

    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_shared_agent_accessible(client, db_session, test_user, test_user_token):
    """Agent shared via AgentShare is accessible by recipient."""
    # Create another user who owns an agent
    owner = UserFactory.build()
    db_session.add(owner)
    db_session.flush()

    shared_agent = AgentFactory.build(user_id=owner.id)
    db_session.add(shared_agent)
    db_session.flush()

    # Share the agent with test_user
    share = AgentShareFactory.build(
        agent_id=shared_agent.id,
        user_id=test_user.id,
        can_edit=False
    )
    db_session.add(share)
    db_session.flush()

    # test_user should be able to access the shared agent
    response = await client.get(
        f"/agents/{shared_agent.id}",
        cookies={"token": test_user_token}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent"]["id"] == shared_agent.id
    assert data["agent"]["shared"] is True
    assert data["agent"]["can_edit"] is False


@pytest.mark.asyncio
async def test_conversation_owner_isolation(client, db_session, test_user, test_agent, test_user_token):
    """User cannot access another user's conversation messages."""
    # Create another user with their own agent and conversation
    other_user = UserFactory.build()
    db_session.add(other_user)
    db_session.flush()

    other_agent = AgentFactory.build(user_id=other_user.id)
    db_session.add(other_agent)
    db_session.flush()

    other_conversation = ConversationFactory.build(
        agent_id=other_agent.id,
        user_id=other_user.id
    )
    db_session.add(other_conversation)
    db_session.flush()

    # test_user tries to access other_user's conversation messages
    response = await client.get(
        f"/conversations/{other_conversation.id}/messages",
        cookies={"token": test_user_token}
    )

    # Should return 404 (not 403) because _verify_conversation_owner returns 404
    assert response.status_code == 404
    assert "Conversation not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_document_delete_owner_only(client, db_session, test_user, test_agent, test_user_token):
    """Non-owner cannot delete a document."""
    # Create another user with a document
    other_user = UserFactory.build()
    db_session.add(other_user)
    db_session.flush()

    other_agent = AgentFactory.build(user_id=other_user.id)
    db_session.add(other_agent)
    db_session.flush()

    other_document = DocumentFactory.build(
        user_id=other_user.id,
        agent_id=other_agent.id
    )
    db_session.add(other_document)
    db_session.flush()

    # test_user tries to delete other_user's document
    response = await client.delete(
        f"/documents/{other_document.id}",
        cookies={"token": test_user_token}
    )

    # Should return 404 because document doesn't belong to test_user
    assert response.status_code == 404
    assert "Document not found" in response.json()["detail"]

    # Verify document still exists
    db_session.expire_all()
    from database import Document
    still_exists = db_session.query(Document).filter(Document.id == other_document.id).first()
    assert still_exists is not None


@pytest.mark.asyncio
async def test_unauthenticated_access_blocked(client, db_session, test_agent):
    """Protected endpoints return 401 without auth."""
    # Try to access agents without auth
    response = await client.get("/agents")
    assert response.status_code == 401

    # Try to access specific agent without auth
    response = await client.get(f"/agents/{test_agent.id}")
    assert response.status_code == 401

    # Try to create agent without auth
    response = await client.post(
        "/agents",
        data={"name": "Unauthorized Agent", "type": "conversationnel"}
    )
    assert response.status_code == 401

    # Try to list conversations without auth
    response = await client.get(f"/conversations?agent_id={test_agent.id}")
    assert response.status_code == 401

    # Try to delete document without auth
    response = await client.delete("/documents/999")
    assert response.status_code == 401
