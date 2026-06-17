"""Proof that ensure_rls_policies() enforces RLS on every tenant table.

PG-backed: skips when PostgreSQL is unavailable (e.g. local without Docker);
runs in CI against the pgvector service.
"""

import pytest
from sqlalchemy import text

# Import the conftest MODULE (not the names) so we read `_db_available` live —
# it is flipped to True by the session-scoped setup_database fixture AFTER import.
import tests.conftest as conftest
from database import TENANT_TABLES, ensure_rls_policies


@pytest.fixture(scope="module")
def rls_applied():
    if not conftest._db_available:
        pytest.skip("PostgreSQL not available")
    # ensure_rls_policies uses the module-level `engine`; point it at the test engine.
    import database

    original = database.engine
    database.engine = conftest._test_engine
    try:
        ensure_rls_policies()
        yield
    finally:
        database.engine = original


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_rls_enabled_and_forced(rls_applied, table):
    with conftest._test_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = :t"
            ),
            {"t": table},
        ).first()
    assert row is not None, f"table {table} missing"
    assert row[0] is True, f"RLS not enabled on {table}"
    assert row[1] is True, f"RLS not forced on {table}"


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_both_policies_present(rls_applied, table):
    with conftest._test_engine.connect() as conn:
        names = {
            r[0]
            for r in conn.execute(
                text("SELECT polname FROM pg_policy WHERE polrelid = CAST(:t AS regclass)"),
                {"t": table},
            ).fetchall()
        }
    assert "service_bypass" in names, f"service_bypass missing on {table}"
    assert "tenant_isolation" in names, f"tenant_isolation missing on {table}"
