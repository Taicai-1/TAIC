"""Admin LLM-usage endpoint: reserved for the platform support account.

The admin area is support-only. Ordinary company admins/owners and members
get 403. The support account passes the access gate (its company-scoped data
view depends on the tenant middleware, which cannot see uncommitted fixtures in
this harness — see test_support_account.py — so it is verified by smoke test).
"""

import pytest

import tests.conftest as conftest
from auth import create_access_token


@pytest.fixture
def pg(db_session):
    if not conftest._db_available:
        pytest.skip("PostgreSQL not available")
    return db_session


def _support_user(db):
    from tests.factories import UserFactory

    u = UserFactory.build(is_support=True, company_id=None)
    db.add(u)
    db.flush()
    return u


@pytest.mark.asyncio
async def test_company_admin_forbidden(pg, client, admin_cookies):
    # A company admin is NOT the support account → no access to the admin area.
    resp = await client.get("/api/admin/llm-usage", cookies=admin_cookies)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Support access required"


@pytest.mark.asyncio
async def test_member_forbidden(pg, client, member_cookies):
    resp = await client.get("/api/admin/llm-usage", cookies=member_cookies)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_rejected(pg, client):
    resp = await client.get("/api/admin/llm-usage")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_support_account_passes_gate(pg, client):
    # The support account clears the is_support gate (it does not get the
    # "Support access required" rejection). Without an active company resolved
    # by the tenant middleware it stops at the membership check instead.
    sup = _support_user(pg)
    resp = await client.get("/api/admin/llm-usage", cookies={"token": create_access_token(data={"sub": str(sup.id)})})
    assert resp.status_code == 403
    assert resp.json()["detail"] != "Support access required"
