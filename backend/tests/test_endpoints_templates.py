"""Integration tests for template CRUD endpoints."""

import pytest
from tests.factories import AgentTemplateFactory, DocumentFactory


@pytest.mark.asyncio
async def test_list_templates_empty(client, admin_cookies, test_company):
    """New org with no templates should return empty list."""
    resp = await client.get("/api/templates", cookies=admin_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "templates" in data
    assert len(data["templates"]) == 0


@pytest.mark.asyncio
async def test_create_template(client, admin_cookies, test_company):
    """Admin can create a template."""
    body = {
        "name": "CTO Template",
        "description": "Expert technique",
        "category": "Tech",
        "icon": "Monitor",
        "default_contexte": "Tu es un CTO expert.",
        "default_biographie": "CTO assistant",
        "default_type": "conversationnel",
    }
    resp = await client.post("/api/templates", json=body, cookies=admin_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["template"]["name"] == "CTO Template"
    assert data["template"]["category"] == "Tech"
    assert data["template"]["document_count"] == 0


@pytest.mark.asyncio
async def test_create_template_member_forbidden(client, member_cookies, test_company):
    """Member cannot create a template."""
    body = {"name": "Forbidden Template"}
    resp = await client.post("/api/templates", json=body, cookies=member_cookies)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_template_detail(client, db_session, admin_cookies, test_company, test_admin_user):
    """GET template detail returns documents."""
    template = AgentTemplateFactory.build(company_id=test_company.id, created_by_user_id=test_admin_user.id)
    db_session.add(template)
    db_session.flush()

    resp = await client.get(f"/api/templates/{template.id}", cookies=admin_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["template"]["name"] == template.name
    assert "documents" in data["template"]


@pytest.mark.asyncio
async def test_update_template(client, db_session, admin_cookies, test_company, test_admin_user):
    """Admin can update a template."""
    template = AgentTemplateFactory.build(company_id=test_company.id, created_by_user_id=test_admin_user.id)
    db_session.add(template)
    db_session.flush()

    resp = await client.put(
        f"/api/templates/{template.id}",
        json={"name": "Updated Name", "category": "RH"},
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["template"]["name"] == "Updated Name"
    assert resp.json()["template"]["category"] == "RH"


@pytest.mark.asyncio
async def test_delete_template(client, db_session, admin_cookies, test_company, test_admin_user):
    """Admin can delete a template."""
    template = AgentTemplateFactory.build(company_id=test_company.id, created_by_user_id=test_admin_user.id)
    db_session.add(template)
    db_session.flush()
    tid = template.id

    resp = await client.delete(f"/api/templates/{tid}", cookies=admin_cookies)
    assert resp.status_code == 200

    resp2 = await client.get(f"/api/templates/{tid}", cookies=admin_cookies)
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_member_can_list_templates(client, db_session, member_cookies, test_company, test_admin_user):
    """Member can list org templates."""
    template = AgentTemplateFactory.build(company_id=test_company.id, created_by_user_id=test_admin_user.id)
    db_session.add(template)
    db_session.flush()

    resp = await client.get("/api/templates", cookies=member_cookies)
    assert resp.status_code == 200
    assert len(resp.json()["templates"]) == 1
