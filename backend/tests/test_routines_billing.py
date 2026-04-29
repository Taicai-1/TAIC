"""Tests for routines.billing — all GCP calls mocked."""

from unittest.mock import patch

from routines.billing import run_billing_check


class TestRunBillingCheck:
    @patch("routines.billing._fetch_billing_data")
    def test_normal_costs_returns_pass(self, mock_fetch):
        mock_fetch.return_value = {
            "cost_7d": {"total": 10.0, "currency": "EUR", "top_services": []},
            "cost_30d": {"total": 40.0, "currency": "EUR", "top_services": []},
            "prev_7d_total": 9.5,
            "prev_30d_total": 38.0,
        }

        result = run_billing_check()

        assert result["status"] == "pass"

    @patch("routines.billing._fetch_billing_data")
    def test_30d_increase_over_20pct_returns_warn(self, mock_fetch):
        mock_fetch.return_value = {
            "cost_7d": {"total": 10.0, "currency": "EUR", "top_services": []},
            "cost_30d": {"total": 50.0, "currency": "EUR", "top_services": []},
            "prev_7d_total": 9.5,
            "prev_30d_total": 35.0,  # 50/35 = 42% increase
        }

        result = run_billing_check()

        assert result["status"] == "warn"
        trend_check = next(c for c in result["checks"] if c["name"] == "cost_trend_30d")
        assert trend_check["status"] == "warn"

    @patch("routines.billing._fetch_billing_data")
    def test_7d_spike_over_50pct_returns_fail(self, mock_fetch):
        mock_fetch.return_value = {
            "cost_7d": {"total": 20.0, "currency": "EUR", "top_services": []},
            "cost_30d": {"total": 50.0, "currency": "EUR", "top_services": []},
            "prev_7d_total": 10.0,  # 20/10 = 100% increase
            "prev_30d_total": 45.0,
        }

        result = run_billing_check()

        assert result["status"] == "fail"

    @patch("routines.billing._fetch_billing_data")
    def test_unavailable_returns_warn(self, mock_fetch):
        mock_fetch.return_value = None

        result = run_billing_check()

        assert result["status"] == "warn"
        assert any("unavailable" in c["detail"] for c in result["checks"])
