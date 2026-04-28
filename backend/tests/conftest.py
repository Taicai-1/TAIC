"""Test infrastructure: DB engine, session fixtures, auth helpers, mock fixtures."""

import os

# Set required env vars BEFORE any backend imports.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/taic_test")
os.environ.setdefault("ENVIRONMENT", "test")
# Prevent real API calls - use dummy keys to satisfy module-level checks
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key-for-unit-tests")
os.environ.setdefault("MISTRAL_API_KEY", "test-mistral-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import Base, get_db, User
from auth import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

_TEST_DATABASE_URL = os.environ["DATABASE_URL"]

# Use a separate engine for tests so we don't pollute the module-level engine.
_test_engine = create_engine(_TEST_DATABASE_URL, pool_pre_ping=True)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


_db_available = False


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create all tables once for the entire test session."""
    global _db_available
    # Only run if DATABASE_URL points to a real PG (not sqlite)
    if "postgresql" in _TEST_DATABASE_URL:
        # Install pgvector extension if available (ignore failure for CI without it)
        try:
            with _test_engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
        except Exception:
            pass
        try:
            Base.metadata.create_all(bind=_test_engine)
            _db_available = True
        except Exception:
            # DB not reachable — unit tests that don't need DB will still work
            _db_available = False
            yield
            return
        yield
        Base.metadata.drop_all(bind=_test_engine)
    else:
        yield


@pytest.fixture
def db_session(setup_database):
    """Yield a DB session that rolls back after each test."""
    if not _db_available:
        pytest.skip("PostgreSQL not available")
    connection = _test_engine.connect()
    transaction = connection.begin()
    session = TestSession(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(db_session):
    """Async test client with DB dependency override."""
    from httpx import AsyncClient, ASGITransport
    from main import app

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def test_user(db_session):
    """Create a verified test user in the DB."""
    from tests.factories import UserFactory

    user = UserFactory.build()
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def test_user_token(test_user):
    """Return a valid JWT token string for test_user."""
    return create_access_token(data={"sub": str(test_user.id)})


@pytest.fixture
def auth_cookies(test_user_token):
    """Return cookies dict for authenticated requests."""
    return {"token": test_user_token}


@pytest.fixture
def test_agent(db_session, test_user):
    """Create a test agent owned by test_user."""
    from tests.factories import AgentFactory

    agent = AgentFactory.build(user_id=test_user.id)
    db_session.add(agent)
    db_session.flush()
    return agent


@pytest.fixture
def test_document(db_session, test_user, test_agent):
    """Create a test document attached to test_agent."""
    from tests.factories import DocumentFactory

    doc = DocumentFactory.build(user_id=test_user.id, agent_id=test_agent.id)
    db_session.add(doc)
    db_session.flush()
    return doc


@pytest.fixture
def test_conversation(db_session, test_user, test_agent):
    """Create a test conversation for test_agent."""
    from tests.factories import ConversationFactory

    conv = ConversationFactory.build(
        agent_id=test_agent.id,
        user_id=test_user.id,
    )
    db_session.add(conv)
    db_session.flush()
    return conv


# ---------------------------------------------------------------------------
# Mock fixtures for external services
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_redis():
    """Patch redis_client.get_redis to return a fakeredis instance."""
    import fakeredis

    fake = fakeredis.FakeRedis(decode_responses=True)
    with patch("redis_client.get_redis", return_value=fake):
        yield fake


@pytest.fixture
def mock_redis_none():
    """Patch redis_client.get_redis to return None (Redis unavailable)."""
    with patch("redis_client.get_redis", return_value=None):
        yield


@pytest.fixture
def mock_openai():
    """Patch openai_client.get_chat_response to return a deterministic response."""
    with patch("openai_client.get_chat_response", return_value="Mocked LLM response.") as m:
        yield m


@pytest.fixture
def mock_mistral_embedding():
    """Patch mistral_embeddings.get_embedding to return a zero vector."""
    zero_vec = [0.0] * 1024
    with patch("mistral_embeddings.get_embedding", return_value=zero_vec) as m:
        yield m


@pytest.fixture
def mock_mistral_embedding_fast():
    """Patch mistral_embeddings.get_embedding_fast to return a zero vector."""
    zero_vec = [0.0] * 1024
    with patch("mistral_embeddings.get_embedding_fast", return_value=zero_vec) as m:
        yield m


@pytest.fixture
def mock_gcs():
    """Patch google.cloud.storage.Client to prevent real GCS calls."""
    mock_blob = MagicMock()
    mock_blob.public_url = "https://storage.googleapis.com/test-bucket/test-file"
    mock_blob.download_as_bytes.return_value = b"fake file content"
    mock_blob.content_type = "application/pdf"

    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob

    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    with patch("google.cloud.storage.Client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def mock_email_service():
    """Patch email_service functions to prevent real email sending."""
    with patch("email_service.send_password_reset_email") as m1, \
         patch("email_service.send_verification_email") as m2, \
         patch("email_service.send_feedback_email") as m3:
        yield {"reset": m1, "verify": m2, "feedback": m3}


@pytest.fixture
def mock_event_tracker():
    """Patch utils.event_tracker to prevent real tracking calls."""
    mock_tracker = MagicMock()
    with patch("utils.event_tracker", mock_tracker):
        yield mock_tracker
