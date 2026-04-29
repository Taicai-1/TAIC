"""Async HTTP client for the TAIC backend APIs."""

import os
from typing import Any, Optional

import httpx

_BACKEND_URL = os.getenv("TAIC_BACKEND_URL", "http://localhost:8080")
_SCHEDULER_SECRET = os.getenv("ROUTINE_SCHEDULER_SECRET", "")


def _headers() -> dict[str, str]:
    return {"X-Scheduler-Secret": _SCHEDULER_SECRET}


async def _get(path: str, params: Optional[dict] = None) -> Any:
    async with httpx.AsyncClient(base_url=_BACKEND_URL, timeout=60) as client:
        resp = await client.get(path, headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def _post(path: str, json_body: Optional[dict] = None) -> Any:
    async with httpx.AsyncClient(base_url=_BACKEND_URL, timeout=120) as client:
        resp = await client.post(path, headers=_headers(), json=json_body)
        resp.raise_for_status()
        return resp.json()


# ── Routine endpoints ──────────────────────────────────────────────────────


async def run_routine(routine_type: str) -> dict:
    """Run a single routine (health, ci_cd, security, billing)."""
    return await _post(f"/api/admin/routine/run/{routine_type}")


async def run_all_routines() -> dict:
    """Run all 4 routines at once."""
    return await _post("/api/admin/routine/run-all")


async def get_latest_reports() -> dict:
    """Get the latest report for each routine type."""
    return await _get("/api/admin/routine/latest")


async def get_report_history(
    routine_type: Optional[str] = None, page: int = 1, page_size: int = 20
) -> dict:
    """Get paginated routine report history, optionally filtered by type."""
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if routine_type:
        params["type"] = routine_type
    return await _get("/api/admin/routine/reports", params=params)


async def get_report_detail(report_id: int) -> dict:
    """Get full detail of a specific routine report."""
    return await _get(f"/api/admin/routine/reports/{report_id}")


# ── Monitoring endpoints ───────────────────────────────────────────────────


async def get_system_metrics() -> dict:
    """Get system-level metrics (memory, uptime, DB pool, Redis, latency)."""
    return await _get("/api/admin/monitoring/metrics")


async def get_app_stats() -> dict:
    """Get application statistics (entity counts, 24h/7d activity)."""
    return await _get("/api/admin/monitoring/app-stats")


async def get_recent_errors(limit: int = 50) -> dict:
    """Get recent errors from the ring buffer."""
    return await _get("/api/admin/monitoring/errors", params={"limit": limit})


async def get_full_monitoring_report() -> dict:
    """Get aggregated monitoring report (metrics + app-stats + errors)."""
    return await _get("/api/admin/monitoring/full-report")
