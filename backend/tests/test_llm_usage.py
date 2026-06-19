import pytest

import llm_usage
from llm_usage import count_tokens, set_llm_context, get_llm_context

import tests.conftest as conftest


def test_count_tokens_nonzero():
    assert count_tokens("hello world, this is a test") > 0
    assert count_tokens("") == 0


def test_context_roundtrip():
    set_llm_context(company_id=5, user_id=7, agent_id=9)
    assert get_llm_context() == {"company_id": 5, "user_id": 7, "agent_id": 9}


def test_record_usage_never_raises(monkeypatch):
    # Force the DB session factory to blow up: record_usage must swallow it.
    set_llm_context(company_id=None, user_id=None, agent_id=None)

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(llm_usage, "SessionLocal", _boom)
    llm_usage.record_usage("openai", "gpt-4o-mini", 10, 20)  # must not raise


# ---- PG-backed cap tests (skip without Postgres; run in CI) ----


@pytest.fixture
def pg(db_session):
    if not conftest._db_available:
        pytest.skip("PostgreSQL not available")
    return db_session


def _seed(db, company_id, cost):
    from database import LLMUsageLog

    db.add(
        LLMUsageLog(
            company_id=company_id,
            user_id=1,
            agent_id=1,
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=cost,
        )
    )
    db.flush()


def test_company_cap_blocks_when_over(pg, test_company, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(llm_usage, "DEFAULT_MONTHLY_CAP", 10.0)
    _seed(pg, test_company.id, 7.0)
    _seed(pg, test_company.id, 4.0)  # total 11.0 > 10.0 cap
    with pytest.raises(HTTPException) as exc:
        llm_usage.check_company_monthly_cap(test_company.id, pg)
    assert exc.value.status_code == 429


def test_company_cap_allows_when_under(pg, test_company, monkeypatch):
    monkeypatch.setattr(llm_usage, "DEFAULT_MONTHLY_CAP", 10.0)
    _seed(pg, test_company.id, 3.0)
    llm_usage.check_company_monthly_cap(test_company.id, pg)  # no raise


def test_company_cap_noop_when_company_none(pg):
    llm_usage.check_company_monthly_cap(None, pg)  # no raise
