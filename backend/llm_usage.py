"""Per-tenant LLM usage recording + monthly spend-cap enforcement (WS2).

Source of truth is the llm_usage_logs table. The cap check SUMs cost over the
current month (indexed query) — correct without Redis. record_usage is
best-effort and must NEVER break the user's request.
"""

import logging
import os
from contextvars import ContextVar
from datetime import datetime

from fastapi import HTTPException

from database import SessionLocal, LLMUsageLog, Company
from llm_pricing import estimate_cost

logger = logging.getLogger(__name__)

_llm_ctx: ContextVar[dict] = ContextVar("llm_ctx", default={})

DEFAULT_MONTHLY_CAP = float(os.getenv("LLM_MONTHLY_CAP_USD_DEFAULT", "300"))


def set_llm_context(company_id=None, user_id=None, agent_id=None) -> None:
    _llm_ctx.set({"company_id": company_id, "user_id": user_id, "agent_id": agent_id})


def get_llm_context() -> dict:
    return _llm_ctx.get({}) or {}


def count_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        # Fallback heuristic: ~4 chars/token.
        return max(1, len(text) // 4)


def record_usage(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Best-effort: write one usage row. Never raises into the caller."""
    ctx = get_llm_context()
    db = None
    try:
        cost = estimate_cost(model, prompt_tokens, completion_tokens)
        db = SessionLocal()
        db.add(
            LLMUsageLog(
                company_id=ctx.get("company_id"),
                user_id=ctx.get("user_id"),
                agent_id=ctx.get("agent_id"),
                provider=provider,
                model=model or "unknown",
                prompt_tokens=int(prompt_tokens or 0),
                completion_tokens=int(completion_tokens or 0),
                cost_usd=cost,
            )
        )
        db.commit()
    except Exception as e:
        logger.warning("record_usage failed (non-fatal): %s", e)
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def _month_start() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)


def _sum_cost(db, *, company_id, since: datetime) -> float:
    from sqlalchemy import func

    total = (
        db.query(func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0))
        .filter(LLMUsageLog.company_id == company_id, LLMUsageLog.created_at >= since)
        .scalar()
    )
    return float(total or 0.0)


def check_company_monthly_cap(company_id, db) -> None:
    """Raise 429 if the company is at/over its monthly cap. No-op if company_id is None."""
    if company_id is None:
        return
    cap = DEFAULT_MONTHLY_CAP
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is not None and company.llm_monthly_cap_usd is not None:
        cap = float(company.llm_monthly_cap_usd)
    spent = _sum_cost(db, company_id=company_id, since=_month_start())
    if spent >= cap:
        raise HTTPException(
            status_code=429,
            detail="Monthly AI usage limit reached for your organization. Contact your administrator.",
        )
