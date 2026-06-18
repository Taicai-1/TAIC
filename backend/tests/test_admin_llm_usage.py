"""Admin LLM-usage endpoint: tenant-scoped cost visibility."""

import pytest

import tests.conftest as conftest


@pytest.fixture
def pg(db_session):
    if not conftest._db_available:
        pytest.skip("PostgreSQL not available")
    return db_session


def _seed(db, company_id, user_id, provider, model, cost):
    from database import LLMUsageLog

    db.add(
        LLMUsageLog(
            company_id=company_id,
            user_id=user_id,
            provider=provider,
            model=model,
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=cost,
        )
    )


@pytest.mark.asyncio
async def test_company_admin_sees_own_usage(pg, client, test_company, test_admin_user, admin_cookies):
    _seed(pg, test_company.id, test_admin_user.id, "openai", "gpt-4o-mini", 1.5)
    _seed(pg, test_company.id, test_admin_user.id, "mistral", "mistral-small-latest", 0.5)
    pg.flush()

    resp = await client.get("/api/admin/llm-usage", cookies=admin_cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "company"
    assert body["company_id"] == test_company.id
    assert round(body["total_cost_usd"], 2) == 2.0
    assert body["total_calls"] == 2
    assert len(body["by_model"]) == 2
    # Company scope must NOT expose other companies.
    assert "by_company" not in body


@pytest.mark.asyncio
async def test_member_forbidden(pg, client, member_cookies):
    resp = await client.get("/api/admin/llm-usage", cookies=member_cookies)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_rejected(pg, client):
    resp = await client.get("/api/admin/llm-usage")
    assert resp.status_code in (401, 403)
