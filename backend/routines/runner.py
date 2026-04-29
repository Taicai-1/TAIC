"""Routine orchestrator — runs one or all monitoring routines."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ROUTINE_TYPES = {"health", "ci_cd", "security", "billing"}


def _run_health(db: Session) -> dict[str, Any]:
    from routines.health import run_health_check
    return run_health_check(db)


def _run_ci_cd(db: Session) -> dict[str, Any]:
    from routines.ci_cd import run_ci_cd_check
    return run_ci_cd_check()


def _run_security(db: Session) -> dict[str, Any]:
    from routines.security import run_security_check
    return run_security_check()


def _run_billing(db: Session) -> dict[str, Any]:
    from routines.billing import run_billing_check
    return run_billing_check()


_RUNNERS = {
    "health": _run_health,
    "ci_cd": _run_ci_cd,
    "security": _run_security,
    "billing": _run_billing,
}


def _build_summary(routine_type: str, result: dict[str, Any]) -> str:
    """Build a one-line summary from routine result."""
    status = result.get("status", "unknown")
    checks = result.get("checks", [])
    pass_count = sum(1 for c in checks if c["status"] == "pass")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    fail_count = sum(1 for c in checks if c["status"] == "fail")
    return f"{routine_type}: {status.upper()} ({pass_count} pass, {warn_count} warn, {fail_count} fail)"


def run_one(routine_type: str, db: Session) -> dict[str, Any]:
    """Run a single routine and return a dict ready to store in DB."""
    if routine_type not in ROUTINE_TYPES:
        raise ValueError(f"Unknown routine type: {routine_type}. Must be one of {ROUTINE_TYPES}")

    runner = _RUNNERS[routine_type]
    try:
        result = runner(db)
    except Exception as e:
        logger.error(f"Routine {routine_type} failed: {e}", exc_info=True)
        result = {
            "status": "fail",
            "checks": [{"name": "execution", "status": "fail", "detail": str(e)}],
        }

    return {
        "type": routine_type,
        "status": result["status"],
        "data": json.dumps(result),
        "summary": _build_summary(routine_type, result),
        "created_at": datetime.now(tz=timezone.utc),
    }


def run_all(db: Session) -> list[dict[str, Any]]:
    """Run all 4 routines and return list of results."""
    results = []
    for routine_type in sorted(ROUTINE_TYPES):
        results.append(run_one(routine_type, db))
    return results
