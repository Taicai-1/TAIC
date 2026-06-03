"""Plugin listing endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from auth import verify_token
from plugins import plugin_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["plugins"])


@router.get("/plugins")
async def list_plugins(user_id: str = Depends(verify_token)):
    """List all available plugins with metadata."""
    plugins = plugin_manager.list_plugins()
    return {
        "plugins": [
            {
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "icon": p.icon,
                "required_scopes": p.required_scopes,
                "actions": [
                    {"name": a.name, "display_name": a.display_name, "description": a.description, "icon": a.icon}
                    for a in p.get_actions().values()
                ],
            }
            for p in plugins
        ]
    }


@router.get("/plugins/{plugin_name}/actions")
async def list_plugin_actions(plugin_name: str, user_id: str = Depends(verify_token)):
    """List actions for a specific plugin."""
    plugin = plugin_manager.get_plugin(plugin_name)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")
    actions = plugin.get_actions()
    return {
        "plugin": plugin_name,
        "actions": [
            {
                "name": a.name,
                "display_name": a.display_name,
                "description": a.description,
                "icon": a.icon,
                "parameters_schema": a.parameters_schema,
            }
            for a in actions.values()
        ],
    }
