"""Billing monitoring routine — checks GCP costs via BigQuery billing export."""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
BILLING_ACCOUNT_ID = os.getenv("BILLING_ACCOUNT_ID", "")
BILLING_BQ_DATASET = os.getenv("BILLING_BQ_DATASET", "")


def _fetch_costs_from_bigquery() -> Optional[dict[str, Any]]:
    """Fetch cost data from BigQuery billing export table.

    Requires BILLING_BQ_DATASET env var pointing to the billing export table
    (e.g. 'project.dataset.gcp_billing_export_v1_XXXXXX').
    """
    if not BILLING_BQ_DATASET:
        return None

    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=GCP_PROJECT_ID)
        now = datetime.now(timezone.utc)

        # Current 7-day costs
        start_7d = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        # Previous 7-day costs (for comparison)
        start_prev_7d = (now - timedelta(days=14)).strftime("%Y-%m-%d")
        # Current 30-day costs
        start_30d = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        # Previous 30-day costs (for comparison)
        start_prev_30d = (now - timedelta(days=60)).strftime("%Y-%m-%d")
        today = now.strftime("%Y-%m-%d")

        query = f"""
        SELECT
            CASE
                WHEN usage_start_time >= TIMESTAMP('{start_7d}') THEN 'current_7d'
                WHEN usage_start_time >= TIMESTAMP('{start_prev_7d}') AND usage_start_time < TIMESTAMP('{start_7d}') THEN 'prev_7d'
                WHEN usage_start_time >= TIMESTAMP('{start_30d}') THEN 'current_30d'
                WHEN usage_start_time >= TIMESTAMP('{start_prev_30d}') AND usage_start_time < TIMESTAMP('{start_30d}') THEN 'prev_30d'
            END AS period,
            service.description AS service_name,
            SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS net_cost,
            currency
        FROM `{BILLING_BQ_DATASET}`
        WHERE usage_start_time >= TIMESTAMP('{start_prev_30d}')
            AND usage_start_time < TIMESTAMP('{today}')
            AND project.id = @project_id
        GROUP BY period, service_name, currency
        HAVING net_cost > 0.01
        ORDER BY period, net_cost DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("project_id", "STRING", GCP_PROJECT_ID),
            ]
        )

        results = client.query(query, job_config=job_config).result()

        periods: dict[str, dict] = {
            "current_7d": {"total": 0.0, "services": {}, "currency": "USD"},
            "prev_7d": {"total": 0.0, "services": {}, "currency": "USD"},
            "current_30d": {"total": 0.0, "services": {}, "currency": "USD"},
            "prev_30d": {"total": 0.0, "services": {}, "currency": "USD"},
        }

        for row in results:
            period = row.period
            if period and period in periods:
                cost = float(row.net_cost)
                periods[period]["total"] += cost
                periods[period]["currency"] = row.currency or "USD"
                periods[period]["services"][row.service_name] = (
                    periods[period]["services"].get(row.service_name, 0) + cost
                )

        def _top_services(services: dict, limit: int = 5) -> list[dict]:
            sorted_s = sorted(services.items(), key=lambda x: x[1], reverse=True)[:limit]
            return [{"name": name, "cost": round(cost, 2)} for name, cost in sorted_s]

        currency = periods["current_7d"]["currency"]

        return {
            "cost_7d": {
                "total": round(periods["current_7d"]["total"], 2),
                "currency": currency,
                "top_services": _top_services(periods["current_7d"]["services"]),
            },
            "cost_30d": {
                "total": round(periods["current_30d"]["total"], 2),
                "currency": currency,
                "top_services": _top_services(periods["current_30d"]["services"]),
            },
            "prev_7d_total": round(periods["prev_7d"]["total"], 2),
            "prev_30d_total": round(periods["prev_30d"]["total"], 2),
        }
    except Exception as e:
        logger.error(f"BigQuery billing fetch failed: {e}")
        return None


def _fetch_billing_from_budgets() -> Optional[dict[str, Any]]:
    """Fallback: fetch billing data from Cloud Billing Budgets API.

    Returns budget info but not actual cost breakdowns.
    """
    if not GCP_PROJECT_ID:
        return None

    try:
        from google.cloud import billing_v1

        client = billing_v1.CloudBillingClient()
        billing_info = client.get_project_billing_info(name=f"projects/{GCP_PROJECT_ID}")

        if not billing_info.billing_enabled:
            return None

        try:
            from google.cloud import billing_budgets_v1

            budgets_client = billing_budgets_v1.BudgetServiceClient()
            billing_account = billing_info.billing_account_name

            budgets = list(budgets_client.list_budgets(parent=billing_account))

            if budgets:
                budget = budgets[0]
                amount = budget.amount.specified_amount
                budget_amount = float(amount.units) + float(amount.nanos) / 1e9 if amount else 0
                currency = amount.currency_code if amount else "EUR"

                return {
                    "cost_7d": {"total": 0, "currency": currency, "top_services": []},
                    "cost_30d": {"total": 0, "currency": currency, "top_services": []},
                    "prev_7d_total": 0,
                    "prev_30d_total": 0,
                    "budget": {"amount": budget_amount, "currency": currency},
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
        logger.error(f"Billing API fetch failed: {e}")
        return None


def run_billing_check() -> dict[str, Any]:
    """Run billing checks and return structured report."""
    checks: list[dict[str, Any]] = []

    # Try BigQuery first (gives real cost data), fall back to Budgets API
    data = _fetch_costs_from_bigquery()
    source = "bigquery"
    if data is None:
        data = _fetch_billing_from_budgets()
        source = "budgets_api"

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
    elif change_7d > 20:
        checks.append({"name": "cost_trend_7d", "status": "warn", "detail": f"+{change_7d:.0f}% vs previous week"})
    else:
        checks.append({"name": "cost_trend_7d", "status": "pass", "detail": f"{change_7d:+.0f}% vs previous week"})

    # 30-day trend
    if prev_30d > 0:
        change_30d = ((cost_30d - prev_30d) / prev_30d) * 100
    else:
        change_30d = 0

    if change_30d > 50:
        checks.append({"name": "cost_trend_30d", "status": "fail", "detail": f"+{change_30d:.0f}% vs previous month"})
    elif change_30d > 20:
        checks.append({"name": "cost_trend_30d", "status": "warn", "detail": f"+{change_30d:.0f}% vs previous month"})
    else:
        checks.append({"name": "cost_trend_30d", "status": "pass", "detail": f"{change_30d:+.0f}% vs previous month"})

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
            "7d_vs_prev_7d": f"{change_7d:+.0f}%",
            "30d_vs_prev_30d": f"{change_30d:+.0f}%",
        },
        "source": source,
        "budget": data.get("budget"),
    }
