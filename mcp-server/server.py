"""TAIC MCP Server — exposes monitoring, routine, and GCP tools via MCP protocol."""

import json
import logging
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

import gcp_tools
import taic_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("TAIC Monitoring")


# ── Routine tools ──────────────────────────────────────────────────────────


@mcp.tool()
async def run_routine(routine_type: str) -> str:
    """Run a single monitoring routine. Types: health, ci_cd, security, billing."""
    result = await taic_client.run_routine(routine_type)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def run_all_routines() -> str:
    """Run all 4 monitoring routines (health, ci_cd, security, billing) at once."""
    result = await taic_client.run_all_routines()
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_latest_reports() -> str:
    """Get the latest report for each routine type (up to 4 items)."""
    result = await taic_client.get_latest_reports()
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_report_history(
    routine_type: Optional[str] = None, page: int = 1, page_size: int = 20
) -> str:
    """Get paginated routine report history. Optionally filter by type (health, ci_cd, security, billing)."""
    result = await taic_client.get_report_history(routine_type, page, page_size)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_report_detail(report_id: int) -> str:
    """Get full detail of a specific routine report by its ID."""
    result = await taic_client.get_report_detail(report_id)
    return json.dumps(result, indent=2, default=str)


# ── Monitoring tools ───────────────────────────────────────────────────────


@mcp.tool()
async def get_system_metrics() -> str:
    """Get system-level metrics: memory RSS, uptime, Python version, DB pool stats, Redis info, request latency."""
    result = await taic_client.get_system_metrics()
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_app_stats() -> str:
    """Get application statistics: total counts of users, agents, documents, chunks, conversations, messages + 24h/7d activity."""
    result = await taic_client.get_app_stats()
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_recent_errors(limit: int = 50) -> str:
    """Get recent errors from the application error ring buffer."""
    result = await taic_client.get_recent_errors(limit)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_full_monitoring_report() -> str:
    """Get aggregated monitoring report combining metrics, app stats, and recent errors."""
    result = await taic_client.get_full_monitoring_report()
    return json.dumps(result, indent=2, default=str)


# ── GCP tools ──────────────────────────────────────────────────────────────


@mcp.tool()
async def get_cloud_run_status() -> str:
    """Get status of all Cloud Run services in the TAIC GCP project (name, URI, conditions)."""
    result = await gcp_tools.get_cloud_run_services()
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_cloud_build_status(limit: int = 10) -> str:
    """Get recent Cloud Build history (build ID, status, source, timing)."""
    result = await gcp_tools.get_cloud_build_history(limit)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_billing_summary() -> str:
    """Get GCP billing summary: billing account, status, and budget information."""
    result = await gcp_tools.get_gcp_billing_summary()
    return json.dumps(result, indent=2, default=str)


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    logger.info(f"Starting TAIC MCP server on port {port}")

    # Import and add auth middleware
    from auth_middleware import BearerAuthMiddleware

    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware)

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port)
