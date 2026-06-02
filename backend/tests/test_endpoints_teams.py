"""Integration tests for team CRUD endpoints with orchestration."""

import json
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_create_team_v2(client, test_user, auth_cookies, db_session):
    """POST /teams with members array format."""
    from tests.factories import AgentFactory

    leader = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    member = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    db_session.add_all([leader, member])
    db_session.flush()

    res = await client.post("/teams", json={
        "name": "Test Team V2",
        "contexte": "Team context",
        "members": [
            {"agent_id": leader.id, "role": "leader", "specialization": "Coordination"},
            {"agent_id": member.id, "role": "member", "specialization": "Expert finance"},
        ]
    }, cookies=auth_cookies)
    assert res.status_code == 200
    data = res.json()["team"]
    assert data["name"] == "Test Team V2"
    assert len(data["members"]) == 2
    assert any(m["role"] == "leader" for m in data["members"])
    assert any(m["role"] == "member" for m in data["members"])
    # Legacy compat fields should also be present
    assert data["leader_agent_id"] == leader.id
    assert data["leader_name"] == leader.name


@pytest.mark.asyncio
async def test_create_team_legacy_format(client, test_user, auth_cookies, db_session):
    """POST /teams with old leader_agent_id format still works."""
    from tests.factories import AgentFactory

    leader = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    member = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    db_session.add_all([leader, member])
    db_session.flush()

    res = await client.post("/teams", json={
        "name": "Legacy Team",
        "leader_agent_id": leader.id,
        "action_agent_ids": [member.id],
    }, cookies=auth_cookies)
    assert res.status_code == 200
    data = res.json()["team"]
    assert data["name"] == "Legacy Team"
    assert data["leader_agent_id"] == leader.id


@pytest.mark.asyncio
async def test_create_team_no_leader_fails(client, test_user, auth_cookies, db_session):
    """POST /teams without a leader should fail validation."""
    from tests.factories import AgentFactory

    member = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    db_session.add(member)
    db_session.flush()

    res = await client.post("/teams", json={
        "name": "Bad Team",
        "members": [
            {"agent_id": member.id, "role": "member", "specialization": "test"},
        ]
    }, cookies=auth_cookies)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_team_duplicate_agents_fails(client, test_user, auth_cookies, db_session):
    """POST /teams with duplicate agent IDs should fail."""
    from tests.factories import AgentFactory

    agent = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    db_session.add(agent)
    db_session.flush()

    res = await client.post("/teams", json={
        "name": "Dup Team",
        "members": [
            {"agent_id": agent.id, "role": "leader"},
            {"agent_id": agent.id, "role": "member"},
        ]
    }, cookies=auth_cookies)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_list_teams_includes_members(client, test_user, auth_cookies, test_team_with_members):
    """GET /teams returns members array."""
    res = await client.get("/teams", cookies=auth_cookies)
    assert res.status_code == 200
    teams = res.json()["teams"]
    assert len(teams) >= 1
    team = next(t for t in teams if t["id"] == test_team_with_members["team"].id)
    assert "members" in team
    assert len(team["members"]) == 3


@pytest.mark.asyncio
async def test_list_teams_empty(client, test_user, auth_cookies):
    """GET /teams with no teams returns empty list."""
    res = await client.get("/teams", cookies=auth_cookies)
    assert res.status_code == 200
    assert res.json()["teams"] == []


@pytest.mark.asyncio
async def test_get_team_includes_members(client, test_user, auth_cookies, test_team_with_members):
    """GET /teams/{id} returns members."""
    team_id = test_team_with_members["team"].id
    res = await client.get(f"/teams/{team_id}", cookies=auth_cookies)
    assert res.status_code == 200
    data = res.json()["team"]
    assert "members" in data
    assert len(data["members"]) == 3
    leader = next(m for m in data["members"] if m["role"] == "leader")
    assert leader["name"] == "Leader"


@pytest.mark.asyncio
async def test_get_team_not_found(client, test_user, auth_cookies):
    """GET /teams/{id} with invalid ID returns 404."""
    res = await client.get("/teams/999999", cookies=auth_cookies)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_suggest_specialization(client, test_user, auth_cookies, test_agent):
    """POST /teams/suggest-specialization returns a specialization string."""
    with patch("orchestrator.suggest_specialization", return_value="Expert en tests unitaires"):
        res = await client.post("/teams/suggest-specialization", json={
            "agent_id": test_agent.id,
        }, cookies=auth_cookies)
    assert res.status_code == 200
    assert "specialization" in res.json()
    assert len(res.json()["specialization"]) > 0


@pytest.mark.asyncio
async def test_suggest_specialization_agent_not_found(client, test_user, auth_cookies):
    """POST /teams/suggest-specialization with unknown agent returns 404."""
    res = await client.post("/teams/suggest-specialization", json={
        "agent_id": 999999,
    }, cookies=auth_cookies)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_update_team_members(client, test_user, auth_cookies, test_team_with_members, db_session):
    """PUT /teams/{id}/members replaces team composition."""
    from tests.factories import AgentFactory

    team_id = test_team_with_members["team"].id
    leader = test_team_with_members["leader"]

    new_member = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    db_session.add(new_member)
    db_session.flush()

    res = await client.put(f"/teams/{team_id}/members", json={
        "members": [
            {"agent_id": leader.id, "role": "leader", "specialization": "Chef"},
            {"agent_id": new_member.id, "role": "member", "specialization": "Nouveau"},
        ]
    }, cookies=auth_cookies)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Verify the team now has the new composition
    res2 = await client.get(f"/teams/{team_id}", cookies=auth_cookies)
    members = res2.json()["team"]["members"]
    assert len(members) == 2
    member_ids = {m["agent_id"] for m in members}
    assert new_member.id in member_ids


@pytest.mark.asyncio
async def test_update_team_members_no_leader_fails(client, test_user, auth_cookies, test_team_with_members):
    """PUT /teams/{id}/members without a leader should fail."""
    team_id = test_team_with_members["team"].id
    member = test_team_with_members["members"][0]

    res = await client.put(f"/teams/{team_id}/members", json={
        "members": [
            {"agent_id": member.id, "role": "member"},
        ]
    }, cookies=auth_cookies)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_patch_team_member(client, test_user, auth_cookies, test_team_with_members):
    """PATCH /teams/{id}/members/{agent_id} updates specialization."""
    team_id = test_team_with_members["team"].id
    member = test_team_with_members["members"][0]

    res = await client.patch(f"/teams/{team_id}/members/{member.id}", json={
        "specialization": "Expert mise a jour",
    }, cookies=auth_cookies)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Verify the specialization was updated
    res2 = await client.get(f"/teams/{team_id}", cookies=auth_cookies)
    updated_member = next(m for m in res2.json()["team"]["members"] if m["agent_id"] == member.id)
    assert updated_member["specialization"] == "Expert mise a jour"


@pytest.mark.asyncio
async def test_patch_team_member_not_found(client, test_user, auth_cookies, test_team_with_members):
    """PATCH /teams/{id}/members/{agent_id} with unknown member returns 404."""
    team_id = test_team_with_members["team"].id

    res = await client.patch(f"/teams/{team_id}/members/999999", json={
        "specialization": "whatever",
    }, cookies=auth_cookies)
    assert res.status_code == 404
