"""Integration tests for agent CRUD endpoints."""

import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_list_agents_empty(client, auth_cookies, test_user):
    """New user with no agents should get empty list."""
    resp = await client.get("/agents", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert len(data["agents"]) == 0


@pytest.mark.asyncio
async def test_list_agents_with_agent(client, auth_cookies, test_agent):
    """User should see their own agents."""
    resp = await client.get("/agents", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert len(data["agents"]) == 1
    agent = data["agents"][0]
    assert agent["id"] == test_agent.id
    assert agent["name"] == test_agent.name
    assert agent["type"] == test_agent.type
    assert agent["shared"] is False


@pytest.mark.asyncio
async def test_create_agent(client, auth_cookies, test_user, mock_gcs):
    """POST /agents should create a new agent using Form data."""
    with patch("helpers.agent_helpers.update_agent_embedding") as mock_embed:
        form_data = {
            "name": "New Test Agent",
            "contexte": "Test context",
            "biographie": "Test bio",
            "type": "conversationnel",
        }
        resp = await client.post("/agents", data=form_data, cookies=auth_cookies)

        assert resp.status_code == 200
        data = resp.json()
        assert "agent" in data
        agent = data["agent"]
        assert agent["name"] == "New Test Agent"
        assert agent["contexte"] == "Test context"
        assert agent["biographie"] == "Test bio"
        assert agent["type"] == "conversationnel"
        assert agent["user_id"] == test_user.id
        assert agent["statut"] == "privé"
        assert agent["llm_provider"] == "mistral"

        # Verify embedding was called
        mock_embed.assert_called_once()


@pytest.mark.asyncio
async def test_create_agent_no_context(client, auth_cookies, test_user, mock_gcs):
    """Creating agent without contexte should not call update_agent_embedding."""
    with patch("helpers.agent_helpers.update_agent_embedding") as mock_embed:
        form_data = {
            "name": "Agent No Context",
            "type": "conversationnel",
        }
        resp = await client.post("/agents", data=form_data, cookies=auth_cookies)

        assert resp.status_code == 200
        data = resp.json()
        assert data["agent"]["name"] == "Agent No Context"

        # Embedding should NOT be called when contexte is empty
        mock_embed.assert_not_called()


@pytest.mark.asyncio
async def test_get_agent(client, auth_cookies, test_agent):
    """GET /agents/{id} should return agent details for owner."""
    resp = await client.get(f"/agents/{test_agent.id}", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "agent" in data
    agent = data["agent"]
    assert agent["id"] == test_agent.id
    assert agent["name"] == test_agent.name
    assert agent["shared"] is False
    # Owner should see editable fields
    assert "contexte" in agent
    assert "biographie" in agent


@pytest.mark.asyncio
async def test_get_agent_not_found(client, auth_cookies):
    """GET /agents/{id} with nonexistent ID should return 404."""
    resp = await client.get("/agents/99999", cookies=auth_cookies)
    assert resp.status_code == 404
    data = resp.json()
    assert "detail" in data
    assert data["detail"] == "Agent not found"


@pytest.mark.asyncio
async def test_delete_agent(client, auth_cookies, test_agent, db_session):
    """DELETE /agents/{id} should delete agent and return success."""
    from database import Agent

    agent_id = test_agent.id
    resp = await client.delete(f"/agents/{agent_id}", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "Agent deleted successfully"

    # Verify agent is deleted from DB
    db_session.expire_all()
    deleted_agent = db_session.query(Agent).filter(Agent.id == agent_id).first()
    assert deleted_agent is None


@pytest.mark.asyncio
async def test_delete_agent_not_owner(client, auth_cookies, test_agent, db_session):
    """Non-owner cannot delete an agent."""
    from tests.factories import UserFactory
    from auth import create_access_token

    # Create another user
    other_user = UserFactory.build()
    db_session.add(other_user)
    db_session.flush()

    other_token = create_access_token(data={"sub": str(other_user.id)})
    other_cookies = {"token": other_token}

    resp = await client.delete(f"/agents/{test_agent.id}", cookies=other_cookies)
    assert resp.status_code == 404  # Agent not found (filtered by user_id)

    # Verify agent still exists
    from database import Agent

    db_session.expire_all()
    agent = db_session.query(Agent).filter(Agent.id == test_agent.id).first()
    assert agent is not None


@pytest.mark.asyncio
async def test_agent_isolation(client, auth_cookies, test_agent, db_session):
    """User cannot see or access another user's agents."""
    from tests.factories import UserFactory, AgentFactory
    from auth import create_access_token

    # Create another user with their own agent
    other_user = UserFactory.build()
    db_session.add(other_user)
    db_session.flush()

    other_agent = AgentFactory.build(user_id=other_user.id)
    db_session.add(other_agent)
    db_session.flush()

    # Test user should not see other_agent in their list
    resp = await client.get("/agents", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    agent_ids = [a["id"] for a in data["agents"]]
    assert test_agent.id in agent_ids
    assert other_agent.id not in agent_ids

    # Test user should get 403 when trying to access other_agent
    resp = await client.get(f"/agents/{other_agent.id}", cookies=auth_cookies)
    assert resp.status_code == 403
    data = resp.json()
    assert "detail" in data
    assert "Access denied" in data["detail"]
