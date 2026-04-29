"""Integration tests for auth endpoints (register, login, verify, logout)."""

import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_register_success(client, db_session, mock_email_service, mock_event_tracker):
    """Test successful user registration."""
    payload = {
        "username": "newuser",
        "email": "newuser@test.com",
        "password": "SecurePass123",
    }

    response = await client.post("/register", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "created successfully" in data["message"]


@pytest.mark.asyncio
async def test_register_duplicate_username(client, db_session, test_user, mock_email_service, mock_event_tracker):
    """Test registration with duplicate username."""
    payload = {
        "username": test_user.username,
        "email": "different@test.com",
        "password": "SecurePass123",
    }

    response = await client.post("/register", json=payload)

    assert response.status_code == 400
    assert "Username already registered" in response.json()["message"]


@pytest.mark.asyncio
async def test_register_duplicate_email(client, db_session, test_user, mock_email_service, mock_event_tracker):
    """Test registration with duplicate email."""
    payload = {
        "username": "differentuser",
        "email": test_user.email,
        "password": "SecurePass123",
    }

    response = await client.post("/register", json=payload)

    assert response.status_code == 400
    assert "Email already registered" in response.json()["message"]


@pytest.mark.asyncio
async def test_register_weak_password(client, db_session, mock_email_service, mock_event_tracker):
    """Test registration with password that doesn't meet requirements."""
    payload = {
        "username": "newuser",
        "email": "newuser@test.com",
        "password": "weak",  # No uppercase, too short
    }

    response = await client.post("/register", json=payload)

    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_login_success(client, db_session, test_user, mock_event_tracker):
    """Test successful login with username."""
    # test_user has email_verified=True and totp_setup_completed_at=None initially
    # Need to set totp_setup_completed_at to bypass 2FA setup requirement
    from datetime import datetime

    test_user.totp_setup_completed_at = datetime.utcnow()
    db_session.commit()

    payload = {
        "username": test_user.username,
        "password": "Test1234",  # Default password from UserFactory
    }

    response = await client.post("/login", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # Verify cookie was set
    assert "token" in response.cookies


@pytest.mark.asyncio
async def test_login_with_email(client, db_session, test_user, mock_event_tracker):
    """Test login using email instead of username."""
    from datetime import datetime

    test_user.totp_setup_completed_at = datetime.utcnow()
    db_session.commit()

    payload = {
        "username": test_user.email,  # Login accepts email in username field
        "password": "Test1234",
    }

    response = await client.post("/login", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client, db_session, test_user, mock_event_tracker):
    """Test login with incorrect password."""
    payload = {
        "username": test_user.username,
        "password": "WrongPassword123",
    }

    response = await client.post("/login", json=payload)

    assert response.status_code == 401
    assert "Invalid credentials" in response.json()["message"]


@pytest.mark.asyncio
async def test_login_nonexistent_user(client, db_session, mock_event_tracker):
    """Test login with username that doesn't exist."""
    payload = {
        "username": "nonexistent",
        "password": "SomePassword123",
    }

    response = await client.post("/login", json=payload)

    assert response.status_code == 401
    assert "Invalid credentials" in response.json()["message"]


@pytest.mark.asyncio
async def test_verify_auth_with_valid_token(client, db_session, test_user, auth_cookies):
    """Test /auth/verify with valid authentication cookie."""
    response = await client.get("/auth/verify", cookies=auth_cookies)

    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert "user" in data
    assert data["user"]["id"] == test_user.id
    assert data["user"]["username"] == test_user.username
    assert data["user"]["email"] == test_user.email


@pytest.mark.asyncio
async def test_verify_auth_no_token(client, db_session):
    """Test /auth/verify without authentication cookie."""
    response = await client.get("/auth/verify")

    assert response.status_code == 401
    assert "Not authenticated" in response.json()["message"]


@pytest.mark.asyncio
async def test_logout(client, db_session):
    """Test logout endpoint clears cookie."""
    response = await client.post("/logout")

    assert response.status_code == 200
    data = response.json()
    assert "Logged out successfully" in data["message"]

    # Verify cookie deletion header is present
    # The cookie should have max_age=0 or expires in the past
    assert "token" in response.cookies or "Set-Cookie" in response.headers
