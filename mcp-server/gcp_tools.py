"""Direct GCP API calls for Cloud Run, Cloud Build, and Billing."""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "applydi")
_REGION = os.getenv("GCP_REGION", "europe-west1")


async def get_cloud_run_services() -> dict[str, Any]:
    """List Cloud Run services with their status."""
    try:
        from google.cloud.run_v2 import ServicesClient

        client = ServicesClient()
        parent = f"projects/{_PROJECT_ID}/locations/{_REGION}"
        services = []
        for svc in client.list_services(parent=parent):
            conditions = []
            if svc.conditions:
                conditions = [
                    {"type": c.type_, "state": str(c.state), "message": c.message}
                    for c in svc.conditions
                ]
            services.append(
                {
                    "name": svc.name.split("/")[-1],
                    "uri": svc.uri,
                    "create_time": svc.create_time.isoformat() if svc.create_time else None,
                    "update_time": svc.update_time.isoformat() if svc.update_time else None,
                    "conditions": conditions,
                }
            )
        return {"services": services, "count": len(services)}
    except Exception as exc:
        logger.exception("Failed to list Cloud Run services")
        return {"error": str(exc), "services": []}


async def get_cloud_build_history(limit: int = 10) -> dict[str, Any]:
    """Get recent Cloud Build history."""
    try:
        from google.cloud.devtools.cloudbuild_v1 import CloudBuildClient

        client = CloudBuildClient()
        builds_list = []
        for build in client.list_builds(
            project_id=_PROJECT_ID, page_size=limit
        ):
            builds_list.append(
                {
                    "id": build.id,
                    "status": str(build.status),
                    "source": (
                        build.source.repo_source.repo_name
                        if build.source and build.source.repo_source
                        else None
                    ),
                    "create_time": build.create_time.isoformat() if build.create_time else None,
                    "finish_time": build.finish_time.isoformat() if build.finish_time else None,
                    "duration": str(build.duration) if build.duration else None,
                }
            )
            if len(builds_list) >= limit:
                break
        return {"builds": builds_list, "count": len(builds_list)}
    except Exception as exc:
        logger.exception("Failed to list Cloud Build history")
        return {"error": str(exc), "builds": []}


async def get_gcp_billing_summary() -> dict[str, Any]:
    """Get GCP billing summary from Cloud Billing API."""
    try:
        from google.cloud.billing_v1 import CloudBillingClient

        client = CloudBillingClient()
        project_name = f"projects/{_PROJECT_ID}"
        billing_info = client.get_project_billing_info(name=project_name)

        result: dict[str, Any] = {
            "project_id": _PROJECT_ID,
            "billing_enabled": billing_info.billing_enabled,
            "billing_account": billing_info.billing_account_name,
        }

        # Try to get budget info
        try:
            from google.cloud.billing.budgets_v1 import BudgetServiceClient

            budget_client = BudgetServiceClient()
            budgets = []
            for budget in budget_client.list_budgets(
                parent=billing_info.billing_account_name
            ):
                budget_info: dict[str, Any] = {
                    "name": budget.display_name,
                    "amount": None,
                }
                if budget.amount and budget.amount.specified_amount:
                    amt = budget.amount.specified_amount
                    budget_info["amount"] = {
                        "currency": amt.currency_code,
                        "units": str(amt.units) if amt.units else "0",
                    }
                budgets.append(budget_info)
            result["budgets"] = budgets
        except Exception as exc:
            result["budgets_error"] = str(exc)

        return result
    except Exception as exc:
        logger.exception("Failed to get billing summary")
        return {"error": str(exc)}
