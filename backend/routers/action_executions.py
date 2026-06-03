"""Action execution endpoints: confirm, cancel, status."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, ActionExecution
from google_credentials import get_google_credentials
from plugins import plugin_manager
from plugins.base import ActionResult

logger = logging.getLogger(__name__)
router = APIRouter(tags=["actions"])


def _execute_action(plugin_name: str, action_name: str, params: dict, credentials) -> ActionResult:
    """Execute a plugin action. Separated for testability."""
    plugin = plugin_manager.get_plugin(plugin_name)
    if not plugin:
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Plugin '{plugin_name}' not found"
        )
    return plugin.execute(action_name, params, credentials)


@router.post("/actions/{execution_id}/confirm")
async def confirm_action(
    execution_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Confirm and execute a pending action."""
    ae = db.query(ActionExecution).filter(
        ActionExecution.id == execution_id,
        ActionExecution.user_id == int(user_id),
    ).first()
    if not ae:
        raise HTTPException(status_code=404, detail="Action execution not found")
    if ae.status != "pending_confirmation":
        raise HTTPException(status_code=400, detail=f"Action is not pending confirmation (status: {ae.status})")

    ae.status = "confirmed"
    ae.confirmed_at = datetime.utcnow()
    db.flush()

    # Get user credentials
    credentials = get_google_credentials(int(user_id), db)
    if not credentials:
        ae.status = "failed"
        ae.error_message = "Google account not connected. Please connect your Google account first."
        db.commit()
        raise HTTPException(status_code=400, detail="Google account not connected")

    # Execute
    ae.status = "executing"
    db.flush()

    params = json.loads(ae.action_params)
    result = _execute_action(ae.plugin_name, ae.action_name, params, credentials)

    if result.success:
        ae.status = "completed"
        ae.result = json.dumps(result.data)
        ae.executed_at = datetime.utcnow()
    else:
        ae.status = "failed"
        ae.error_message = result.error_message
        ae.executed_at = datetime.utcnow()

    db.commit()

    return {
        "status": ae.status,
        "display_message": result.display_message,
        "resource_url": result.resource_url,
        "data": result.data,
        "error_message": result.error_message,
    }


@router.post("/actions/{execution_id}/cancel")
async def cancel_action(
    execution_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Cancel a pending action."""
    ae = db.query(ActionExecution).filter(
        ActionExecution.id == execution_id,
        ActionExecution.user_id == int(user_id),
    ).first()
    if not ae:
        raise HTTPException(status_code=404, detail="Action execution not found")
    if ae.status != "pending_confirmation":
        raise HTTPException(status_code=400, detail=f"Cannot cancel action with status: {ae.status}")

    ae.status = "cancelled"
    db.commit()
    return {"status": "cancelled"}


@router.get("/actions/{execution_id}")
async def get_action_status(
    execution_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get the status and result of an action execution."""
    ae = db.query(ActionExecution).filter(
        ActionExecution.id == execution_id,
        ActionExecution.user_id == int(user_id),
    ).first()
    if not ae:
        raise HTTPException(status_code=404, detail="Action execution not found")

    return {
        "id": ae.id,
        "plugin_name": ae.plugin_name,
        "action_name": ae.action_name,
        "action_params": json.loads(ae.action_params),
        "status": ae.status,
        "result": json.loads(ae.result) if ae.result else None,
        "error_message": ae.error_message,
        "confirmed_at": ae.confirmed_at.isoformat() if ae.confirmed_at else None,
        "executed_at": ae.executed_at.isoformat() if ae.executed_at else None,
        "created_at": ae.created_at.isoformat() if ae.created_at else None,
    }
