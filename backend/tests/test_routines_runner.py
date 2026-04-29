"""Tests for routines.runner — orchestration logic."""

import pytest
from unittest.mock import MagicMock, patch

from routines.runner import run_one, run_all, ROUTINE_TYPES


def _mock_runner(status="pass"):
    """Return a mock runner function that produces a JSON-serializable result."""
    def runner(db):
        return {"status": status, "checks": []}
    return runner


class TestRunOne:
    @patch.dict("routines.runner._RUNNERS", {"health": _mock_runner("pass")})
    def test_run_one_health(self):
        db = MagicMock()

        result = run_one("health", db)

        assert result["type"] == "health"
        assert result["status"] == "pass"
        assert "data" in result

    def test_run_one_invalid_type_raises(self):
        db = MagicMock()
        with pytest.raises(ValueError, match="Unknown routine type"):
            run_one("invalid", db)


class TestRunAll:
    @patch.dict("routines.runner._RUNNERS", {
        "billing": _mock_runner("pass"),
        "ci_cd": _mock_runner("pass"),
        "health": _mock_runner("pass"),
        "security": _mock_runner("warn"),
    })
    def test_run_all_returns_4_results(self):
        db = MagicMock()

        results = run_all(db)

        assert len(results) == 4
        types = [r["type"] for r in results]
        assert set(types) == {"health", "ci_cd", "security", "billing"}


class TestRoutineTypes:
    def test_all_4_types_registered(self):
        assert set(ROUTINE_TYPES) == {"health", "ci_cd", "security", "billing"}
