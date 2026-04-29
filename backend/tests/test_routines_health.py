"""Tests for routines.health — no DB required, all functions are mocked."""

from unittest.mock import MagicMock, patch

from routines.health import run_health_check


class TestRunHealthCheck:
    def _mock_metrics(self, pool_util=0.3, redis_status="up", p95=200, p99=800):
        return {
            "uptime_seconds": 3600,
            "db_pool": {
                "size": 3,
                "checked_in": 2,
                "checked_out": 1,
                "overflow": 0,
            },
            "redis": {"status": redis_status},
            "request_latency": {
                "total_requests": 100,
                "latency_percentiles": {
                    "p50": 50,
                    "p90": 100,
                    "p95": p95,
                    "p99": p99,
                },
            },
        }

    def _mock_app_stats(self):
        return {
            "totals": {"users": 10, "agents": 5, "documents": 20, "conversations": 30, "messages": 100, "chunks": 200},
            "last_24h": {"users": 1, "agents": 0, "documents": 2, "conversations": 5, "messages": 15},
            "last_7d": {"users": 3, "agents": 1, "documents": 8, "conversations": 12, "messages": 50},
        }

    @patch("routines.health._collect_errors", return_value=[])
    @patch("routines.health._collect_app_stats")
    @patch("routines.health._collect_metrics")
    def test_all_healthy_returns_pass(self, mock_metrics, mock_stats, mock_errors):
        mock_metrics.return_value = self._mock_metrics()
        mock_stats.return_value = self._mock_app_stats()
        db = MagicMock()

        result = run_health_check(db)

        assert result["status"] == "pass"
        assert all(c["status"] == "pass" for c in result["checks"])

    @patch("routines.health._collect_errors", return_value=[{"msg": "err"}] * 15)
    @patch("routines.health._collect_app_stats")
    @patch("routines.health._collect_metrics")
    def test_many_errors_returns_warn(self, mock_metrics, mock_stats, mock_errors):
        mock_metrics.return_value = self._mock_metrics()
        mock_stats.return_value = self._mock_app_stats()
        db = MagicMock()

        result = run_health_check(db)

        assert result["status"] == "warn"
        error_check = next(c for c in result["checks"] if c["name"] == "recent_errors")
        assert error_check["status"] == "warn"

    @patch("routines.health._collect_errors", return_value=[])
    @patch("routines.health._collect_app_stats")
    @patch("routines.health._collect_metrics")
    def test_redis_down_returns_warn(self, mock_metrics, mock_stats, mock_errors):
        mock_metrics.return_value = self._mock_metrics(redis_status="down")
        mock_stats.return_value = self._mock_app_stats()
        db = MagicMock()

        result = run_health_check(db)

        assert result["status"] == "warn"
        redis_check = next(c for c in result["checks"] if c["name"] == "redis")
        assert redis_check["status"] == "warn"

    @patch("routines.health._collect_errors", return_value=[])
    @patch("routines.health._collect_app_stats")
    @patch("routines.health._collect_metrics")
    def test_high_p99_returns_fail(self, mock_metrics, mock_stats, mock_errors):
        mock_metrics.return_value = self._mock_metrics(p99=2500)
        mock_stats.return_value = self._mock_app_stats()
        db = MagicMock()

        result = run_health_check(db)

        assert result["status"] == "fail"
        latency_check = next(c for c in result["checks"] if c["name"] == "latency_p99")
        assert latency_check["status"] == "fail"
