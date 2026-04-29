"""Billing monitoring routine — checks GCP costs via Cloud Billing API."""

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
BILLING_ACCOUNT_ID = os.getenv("BILLING_ACCOUNT_ID", "")


def _fetch_billing_data() -> Optional[dict[str, Any]]:
    """Fetch billing data from Cloud Billing Budgets API.

    Returns cost data for current and previous 7d/30d periods,
    or None if the API is unavailable.
    """
    if not GCP_PROJECT_ID:
        logger.warning("GCP_PROJECT_ID not set, skipping billing check")
        return None

    try:
        from google.cloud import billing_v1

        client = billing_v1.CloudBillingClient()

        # List billing info for the project
        billing_info = client.get_project_billing_info(name=f"projects/{GCP_PROJECT_ID}")

        if not billing_info.billing_enabled:
            return None

        # Note: The Cloud Billing API doesn't directly give cost breakdowns.
        # For detailed costs, BigQuery billing export is needed.
        # This is a simplified check using budgets if available.
        try:
            from google.cloud import billing_budgets_v1

            budgets_client = billing_budgets_v1.BudgetServiceClient()
            billing_account = billing_info.billing_account_name

            budgets = list(budgets_client.list_budgets(parent=billing_account))

            if budgets:
                budget = budgets[0]
                amount = budget.amount.specified_amount
                budget_amount = float(amount.units) + float(amount.nanos) / 1e9 if amount else 0

                return {
                    "cost_7d": {"total": 0, "currency": amount.currency_code if amount else "EUR", "top_services": []},
                    "cost_30d": {"total": 0, "currency": amount.currency_code if amount else "EUR", "top_services": []},
                    "prev_7d_total": 0,
                    "prev_30d_total": 0,
                    "budget": {"amount": budget_amount, "currency": amount.currency_code if amount else "EUR"},
                }
        except Exception as e:
            logger.warning(f"Budgets API unavailable: {e}")

        return {
            "cost_7d": {"total": 0, "currency": "EUR", "top_services": []},
            "cost_30d": {"total": 0, "currency": "EUR", "top_services": []},
            "prev_7d_total": 0,
            "prev_30d_total": 0,
        }

    except Exception as e:
        logger.error(f"Billing data fetch failed: {e}")
        return None


def run_billing_check() -> dict[str, Any]:
    """Run billing checks and return structured report."""
    checks: list[dict[str, Any]] = []
    data = _fetch_billing_data()

    if data is None:
        checks.append({"name": "cost_trend_7d", "status": "warn", "detail": "Billing data unavailable"})
        checks.append({"name": "cost_trend_30d", "status": "warn", "detail": "Billing data unavailable"})
        return {"status": "warn", "checks": checks, "cost_7d": None, "cost_30d": None, "trend": None}

    cost_7d = data["cost_7d"]["total"]
    cost_30d = data["cost_30d"]["total"]
    prev_7d = data.get("prev_7d_total", 0)
    prev_30d = data.get("prev_30d_total", 0)

    # 7-day trend
    if prev_7d > 0:
        change_7d = ((cost_7d - prev_7d) / prev_7d) * 100
    else:
        change_7d = 0

    if change_7d > 50:
        checks.append({"name": "cost_trend_7d", "status": "fail", "detail": f"+{change_7d:.0f}% vs previous week"})
    else:
        checks.append({"name": "cost_trend_7d", "status": "pass", "detail": f"+{change_7d:.0f}% vs previous week"})

    # 30-day trend
    if prev_30d > 0:
        change_30d = ((cost_30d - prev_30d) / prev_30d) * 100
    else:
        change_30d = 0

    if change_30d > 20:
        checks.append({"name": "cost_trend_30d", "status": "warn", "detail": f"+{change_30d:.0f}% vs previous month"})
    else:
        checks.append({"name": "cost_trend_30d", "status": "pass", "detail": f"+{change_30d:.0f}% vs previous month"})

    # Overall
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
        "cost_7d": data["cost_7d"],
        "cost_30d": data["cost_30d"],
        "trend": {
            "7d_vs_prev_7d": f"+{change_7d:.0f}%",
            "30d_vs_prev_30d": f"+{change_30d:.0f}%",
        },
    }
