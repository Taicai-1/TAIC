"""WS2: the /ask endpoint must 429 when the caller's company is over its monthly cap."""

import pytest

import tests.conftest as conftest


@pytest.fixture
def pg(db_session):
    if not conftest._db_available:
        pytest.skip("PostgreSQL not available")
    return db_session


@pytest.mark.asyncio
async def test_ask_blocked_when_company_over_cap(pg, client, test_company, test_member_user, member_cookies):
    from database import LLMUsageLog

    # Tight cap + usage already over it.
    test_company.llm_monthly_cap_usd = 1.0
    pg.add(
        LLMUsageLog(
            company_id=test_company.id,
            user_id=test_member_user.id,
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=2.0,
        )
    )
    pg.flush()

    resp = await client.post("/ask", json={"question": "Bonjour, peux-tu m'aider ?"}, cookies=member_cookies)
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_ask_not_blocked_when_under_cap(pg, client, test_company, test_member_user, member_cookies, mock_openai):
    # No usage rows + generous default cap -> the cap must NOT block (status != 429).
    resp = await client.post("/ask", json={"question": "Bonjour"}, cookies=member_cookies)
    assert resp.status_code != 429
