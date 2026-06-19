"""forgot-password must not reveal whether an account exists (no enumeration)."""

import pytest

import tests.conftest as conftest


@pytest.fixture
def pg(db_session):
    if not conftest._db_available:
        pytest.skip("PostgreSQL not available")
    return db_session


@pytest.mark.asyncio
async def test_no_account_enumeration(pg, client, test_user, mock_email_service):
    from database import PasswordResetToken

    r_existing = await client.post("/forgot-password", json={"email": test_user.email})
    r_missing = await client.post("/forgot-password", json={"email": "no-such-user-xyz@example.com"})

    # Identical generic response in both cases → an attacker can't tell which emails exist.
    assert r_existing.status_code == 200
    assert r_missing.status_code == 200
    assert r_existing.json() == r_missing.json()

    # A reset token is created ONLY for the real account.
    assert pg.query(PasswordResetToken).filter(PasswordResetToken.user_id == test_user.id).count() >= 1
