"""Support account: cross-company access. Task 1 covers the model + contextvars;
endpoint/behavior tests are added in Task 9 (PG-backed)."""

import database


def test_is_support_defaults_falsey():
    from tests.factories import UserFactory

    u = UserFactory.build()
    # Column default applies at INSERT; on a built (un-flushed) instance it's False/None.
    assert getattr(u, "is_support", None) in (False, None)


def test_support_session_contextvar_roundtrip():
    database.set_support_session(True)
    assert database.is_support_session() is True
    database.set_support_session(False)
    assert database.is_support_session() is False


def test_get_current_company_id_reads_contextvar():
    database.set_current_company_id(4242)
    assert database.get_current_company_id() == 4242
    database.set_current_company_id(None)


def test_synthetic_owner_membership_in_support_session():
    """In a support session, get_user_membership returns a synthetic owner in the active company."""
    from permissions import get_user_membership

    database.set_support_session(True)
    database.set_current_company_id(777)
    try:
        m = get_user_membership(999, None)  # no real membership; support path returns synthetic before any query
        assert m is not None
        assert m.role == "owner"
        assert m.company_id == 777
    finally:
        database.set_support_session(False)
        database.set_current_company_id(None)


# ---- PG-backed endpoint tests (skip without Postgres; run in CI) ----
#
# NOTE: cross-company DATA scoping is driven by the tenant middleware, whose user
# lookup uses a separate DB connection that cannot see this harness's uncommitted
# fixtures — so it is verified by the manual smoke test, not here. These tests
# cover the support endpoints (which use the request db_session) + gating + audit.

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


def _company(db, name):
    from tests.factories import CompanyFactory

    c = CompanyFactory.build(name=name)
    db.add(c)
    db.flush()
    return c


def _cookie(user_id, active_company_id=None):
    data = {"sub": str(user_id)}
    if active_company_id is not None:
        data["active_company_id"] = active_company_id
    return {"token": create_access_token(data=data)}


@pytest.mark.asyncio
async def test_support_lists_companies_member_forbidden(pg, client, member_cookies):
    sup = _support_user(pg)
    _company(pg, "Company A (support test)")
    _company(pg, "Company B (support test)")

    # A normal member is forbidden.
    r_member = await client.get("/api/support/companies", cookies=member_cookies)
    assert r_member.status_code == 403

    # The support account lists all companies.
    r_sup = await client.get("/api/support/companies", cookies=_cookie(sup.id))
    assert r_sup.status_code == 200
    names = [c["name"] for c in r_sup.json()["companies"]]
    assert "Company A (support test)" in names
    assert "Company B (support test)" in names


@pytest.mark.asyncio
async def test_support_switch_writes_audit(pg, client):
    from database import SupportAuditLog

    sup = _support_user(pg)
    a = _company(pg, "Company Switch (support test)")

    r = await client.post("/api/support/active-company", json={"company_id": a.id}, cookies=_cookie(sup.id))
    assert r.status_code == 200
    assert r.json()["active_company_id"] == a.id

    rows = (
        pg.query(SupportAuditLog)
        .filter(SupportAuditLog.support_user_id == sup.id, SupportAuditLog.target_company_id == a.id)
        .count()
    )
    assert rows >= 1


@pytest.mark.asyncio
async def test_support_switch_unknown_company_404(pg, client):
    sup = _support_user(pg)
    r = await client.post("/api/support/active-company", json={"company_id": 999999}, cookies=_cookie(sup.id))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_non_support_cannot_switch(pg, client, member_cookies):
    r = await client.post("/api/support/active-company", json={"company_id": 1}, cookies=member_cookies)
    assert r.status_code == 403
