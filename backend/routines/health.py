"""Health monitoring routine — evaluates DB, Redis, latency, errors, app stats."""

import logging
from typing import Any

from sqlalchemy.orm import Session

from routers.monitoring import _collect_app_stats, _collect_errors, _collect_metrics

logger = logging.getLogger(__name__)


def run_health_check(db: Session) -> dict[str, Any]:
    """Run health checks and return structured report with status and checks list."""
    metrics = _collect_metrics()
    app_stats = _collect_app_stats(db)
    errors = _collect_errors(limit=50)

    checks: list[dict[str, Any]] = []

    # DB pool utilization
    pool = metrics["db_pool"]
    total_capacity = pool["size"] + max(pool["overflow"], 0)
    utilization = pool["checked_out"] / total_capacity if total_capacity > 0 else 0
    if utilization > 0.7:
        checks.append({"name": "db_pool", "status": "warn", "detail": f"{utilization:.0%} utilization"})
    else:
        checks.append({"name": "db_pool", "status": "pass", "detail": f"{utilization:.0%} utilization"})

    # Redis
    redis_status = metrics["redis"].get("status", "unavailable")
    if redis_status in ("down", "error", "unavailable"):
        checks.append({"name": "redis", "status": "warn", "detail": redis_status})
    else:
        checks.append({"name": "redis", "status": "pass", "detail": redis_status})

    # Latency percentiles
    latency = metrics.get("request_latency", {})
    percentiles = latency.get("latency_percentiles", {})
    p95 = percentiles.get("p95", 0)
    p99 = percentiles.get("p99", 0)

    if p95 > 500:
        checks.append({"name": "latency_p95", "status": "warn", "detail": f"{p95}ms"})
    else:
        checks.append({"name": "latency_p95", "status": "pass", "detail": f"{p95}ms"})

    if p99 > 2000:
        checks.append({"name": "latency_p99", "status": "fail", "detail": f"{p99}ms"})
    else:
        checks.append({"name": "latency_p99", "status": "pass", "detail": f"{p99}ms"})

    # Recent errors
    error_count = len(errors)
    if error_count > 10:
        checks.append({"name": "recent_errors", "status": "warn", "detail": f"{error_count} errors"})
    else:
        checks.append({"name": "recent_errors", "status": "pass", "detail": f"{error_count} errors"})

    # Overall status
    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return {
        "status": overall,
        "checks": checks,
        "db": {
            "status": "up",
            "pool_utilization": round(utilization, 2),
        },
        "redis": metrics["redis"],
        "latency": percentiles,
        "errors": {"count": error_count, "recent": errors[:5]},
        "app_stats": app_stats.get("totals", {}),
    }
