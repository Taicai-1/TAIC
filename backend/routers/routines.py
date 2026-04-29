"""Admin routine endpoints — run, list, and read monitoring routine reports."""

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth import verify_token
from database import RoutineReport, get_db
from permissions import require_role
from routines.runner import ROUTINE_TYPES, run_all, run_one

logger = logging.getLogger(__name__)

router = APIRouter()

# Cloud Scheduler sends OIDC tokens. We verify via a shared secret as fallback.
_SCHEDULER_SECRET = os.getenv("ROUTINE_SCHEDULER_SECRET", "")


def _verify_admin_or_scheduler(request: Request, db: Session) -> bool:
    """Allow access if user is admin OR request has a valid scheduler secret."""
    # Check scheduler secret header first (Cloud Scheduler)
    scheduler_header = request.headers.get("X-Scheduler-Secret", "")
    if _SCHEDULER_SECRET and scheduler_header == _SCHEDULER_SECRET:
        return True

    # Fall back to normal admin auth
    from auth import verify_token as _verify

    try:
        user_id = _verify(request)
        require_role(int(user_id), db, "admin")
        return True
    except Exception:
        raise HTTPException(status_code=403, detail="Admin access or valid scheduler secret required")


def _store_report(db: Session, result: dict) -> RoutineReport:
    """Store a routine result in the database."""
    report = RoutineReport(
        type=result["type"],
        status=result["status"],
        data=result["data"],
        summary=result["summary"],
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def _serialize_report(report: RoutineReport) -> dict:
    """Serialize a RoutineReport to a JSON-safe dict."""
    return {
        "id": report.id,
        "type": report.type,
        "status": report.status,
        "data": json.loads(report.data) if report.data else {},
        "summary": report.summary,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.post("/api/admin/routine/run-all")
async def routine_run_all(
    request: Request,
    db: Session = Depends(get_db),
):
    """Execute all 4 routines, store results, return summary."""
    _verify_admin_or_scheduler(request, db)

    results = run_all(db)
    stored = []
    for result in results:
        report = _store_report(db, result)
        stored.append(_serialize_report(report))

    return {"reports": stored}


@router.post("/api/admin/routine/run/{routine_type}")
async def routine_run_one(
    routine_type: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Execute a single routine by type."""
    _verify_admin_or_scheduler(request, db)

    if routine_type not in ROUTINE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type. Must be one of: {', '.join(sorted(ROUTINE_TYPES))}")

    result = run_one(routine_type, db)
    report = _store_report(db, result)
    return _serialize_report(report)


@router.get("/api/admin/routine/latest")
async def routine_latest(
    request: Request,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Latest report for each routine type (up to 4 items)."""
    require_role(int(user_id), db, "admin")

    results = []
    for rtype in sorted(ROUTINE_TYPES):
        report = (
            db.query(RoutineReport)
            .filter(RoutineReport.type == rtype)
            .order_by(desc(RoutineReport.created_at))
            .first()
        )
        if report:
            results.append(_serialize_report(report))
    return {"reports": results}


@router.get("/api/admin/routine/reports")
async def routine_reports(
    request: Request,
    type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Paginated list of routine reports, filterable by type."""
    require_role(int(user_id), db, "admin")

    query = db.query(RoutineReport)
    if type:
        if type not in ROUTINE_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid type. Must be one of: {', '.join(sorted(ROUTINE_TYPES))}")
        query = query.filter(RoutineReport.type == type)

    total = query.count()
    reports = (
        query.order_by(desc(RoutineReport.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "reports": [_serialize_report(r) for r in reports],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/api/admin/routine/reports/{report_id}")
async def routine_report_detail(
    report_id: int,
    request: Request,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Full detail of one routine report."""
    require_role(int(user_id), db, "admin")

    report = db.query(RoutineReport).filter(RoutineReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return _serialize_report(report)
