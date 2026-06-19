"""Admin monitoring endpoints — system metrics, app stats, errors, full report."""

import platform
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import (
    Agent,
    Conversation,
    Document,
    DocumentChunk,
    Message,
    User,
    engine,
    get_db,
)
from helpers.admin_auth import verify_admin_or_scheduler
from monitoring import _get_memory_rss_kb, error_handler, request_metrics
from redis_client import get_redis

router = APIRouter()

# App boot timestamp (set once at import time)
_boot_time = time.time()


# ---------------------------------------------------------------------------
# Helpers (DRY: reused by individual endpoints and full-report)
# ---------------------------------------------------------------------------
def _collect_metrics() -> dict[str, Any]:
    """System-level metrics: memory, uptime, Python, DB pool, Redis, latency."""
    pool = engine.pool

    # DB pool stats
    db_pool = {
        "size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
    }

    # Redis info (best-effort)
    redis_info: dict[str, Any] = {"status": "unavailable"}
    try:
        r = get_redis()
        if r is not None:
            mem = r.info("memory")
            clients = r.info("clients")
            redis_info = {
                "status": "up",
                "used_memory_human": mem.get("used_memory_human"),
                "used_memory_peak_human": mem.get("used_memory_peak_human"),
                "connected_clients": clients.get("connected_clients"),
                "total_keys": r.dbsize(),
            }
    except Exception as exc:
        redis_info = {"status": "error", "error": str(exc)}

    uptime_s = round(time.time() - _boot_time, 1)

    return {
        "uptime_seconds": uptime_s,
        "python_version": sys.version,
        "platform": platform.platform(),
        "memory_rss_kb": _get_memory_rss_kb(),
        "db_pool": db_pool,
        "redis": redis_info,
        "request_latency": request_metrics.get_summary(seconds=3600),
    }


def _collect_app_stats(db: Session) -> dict[str, Any]:
    """Application-level counts (scoped to tenant via RLS)."""
    now = datetime.now(tz=timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    def _count(model, date_col=None, since=None):
        q = db.query(func.count(model.id))
        if date_col is not None and since is not None:
            q = q.filter(date_col >= since)
        return q.scalar() or 0

    return {
        "totals": {
            "users": _count(User),
            "agents": _count(Agent),
            "documents": _count(Document),
            "chunks": _count(DocumentChunk),
            "conversations": _count(Conversation),
            "messages": _count(Message),
        },
        "last_24h": {
            "users": _count(User, User.created_at, day_ago),
            "agents": _count(Agent, Agent.created_at, day_ago),
            "documents": _count(Document, Document.created_at, day_ago),
            "conversations": _count(Conversation, Conversation.created_at, day_ago),
            "messages": _count(Message, Message.timestamp, day_ago),
        },
        "last_7d": {
            "users": _count(User, User.created_at, week_ago),
            "agents": _count(Agent, Agent.created_at, week_ago),
            "documents": _count(Document, Document.created_at, week_ago),
            "conversations": _count(Conversation, Conversation.created_at, week_ago),
            "messages": _count(Message, Message.timestamp, week_ago),
        },
    }


def _collect_errors(limit: int = 50) -> list[dict[str, Any]]:
    return error_handler.get_errors(limit=limit)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/api/admin/monitoring/metrics")
async def admin_metrics(
    request: Request,
    db: Session = Depends(get_db),
):
    """System metrics: memory, uptime, DB pool, Redis info, request latency."""
    verify_admin_or_scheduler(request, db)
    return _collect_metrics()


@router.get("/api/admin/monitoring/app-stats")
async def admin_app_stats(
    request: Request,
    db: Session = Depends(get_db),
):
    """Application statistics: entity counts, 24h/7d activity."""
    verify_admin_or_scheduler(request, db)
    return _collect_app_stats(db)


@router.get("/api/admin/monitoring/errors")
async def admin_errors(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Recent captured errors from the ring buffer."""
    verify_admin_or_scheduler(request, db)
    return {"errors": _collect_errors(limit=limit), "count": len(error_handler)}


@router.get("/api/admin/monitoring/full-report")
async def admin_full_report(
    request: Request,
    db: Session = Depends(get_db),
):
    """Aggregated monitoring report: health + metrics + app-stats + errors."""
    verify_admin_or_scheduler(request, db)

    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "metrics": _collect_metrics(),
        "app_stats": _collect_app_stats(db),
        "recent_errors": _collect_errors(limit=50),
    }


@router.get("/api/admin/llm-usage")
async def admin_llm_usage(
    request: Request,
    db: Session = Depends(get_db),
):
    """Current-month LLM token/cost usage.

    Scope is tenant-respecting:
    - Platform operator (valid X-Scheduler-Secret header) → ALL companies.
    - Company admin (admin JWT) → ONLY their own company (no cross-tenant cost leak).
    """
    import os

    from auth import verify_token
    from permissions import require_role, get_user_membership
    from database import LLMUsageLog

    scheduler_secret = os.getenv("ROUTINE_SCHEDULER_SECRET", "").strip()
    is_platform = bool(scheduler_secret) and request.headers.get("X-Scheduler-Secret", "") == scheduler_secret

    company_id = None
    if not is_platform:
        user_id = verify_token(request)  # 401 if missing/invalid
        require_role(int(user_id), db, "admin")  # 403 if not admin
        membership = get_user_membership(int(user_id), db)
        if not membership:
            raise HTTPException(status_code=403, detail="Not part of an organization")
        company_id = membership.company_id

    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)

    base = db.query(LLMUsageLog).filter(LLMUsageLog.created_at >= month_start)
    if company_id is not None:
        base = base.filter(LLMUsageLog.company_id == company_id)

    totals = base.with_entities(
        func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0),
        func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0),
        func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0),
        func.count(LLMUsageLog.id),
    ).first()

    by_model = (
        base.with_entities(
            LLMUsageLog.provider,
            LLMUsageLog.model,
            func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0),
            func.count(LLMUsageLog.id),
        )
        .group_by(LLMUsageLog.provider, LLMUsageLog.model)
        .order_by(func.sum(LLMUsageLog.cost_usd).desc())
        .all()
    )

    result = {
        "scope": "platform" if is_platform else "company",
        "company_id": company_id,
        "month": month_start.strftime("%Y-%m"),
        "total_cost_usd": round(float(totals[0]), 4),
        "total_prompt_tokens": int(totals[1]),
        "total_completion_tokens": int(totals[2]),
        "total_calls": int(totals[3]),
        "by_model": [
            {"provider": p, "model": m, "cost_usd": round(float(c), 4), "calls": int(n)} for p, m, c, n in by_model
        ],
    }

    if is_platform:
        by_company = (
            base.with_entities(
                LLMUsageLog.company_id,
                func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0),
                func.count(LLMUsageLog.id),
            )
            .group_by(LLMUsageLog.company_id)
            .order_by(func.sum(LLMUsageLog.cost_usd).desc())
            .all()
        )
        result["by_company"] = [
            {"company_id": cid, "cost_usd": round(float(c), 4), "calls": int(n)} for cid, c, n in by_company
        ]

    return result
