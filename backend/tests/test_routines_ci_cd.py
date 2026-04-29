"""Tests for routines.ci_cd — all external calls mocked."""

from unittest.mock import patch

from routines.ci_cd import run_ci_cd_check


class TestGitHubActions:
    @patch("routines.ci_cd._fetch_cloud_builds")
    @patch("routines.ci_cd._fetch_github_runs")
    def test_success_run_returns_pass(self, mock_gh, mock_cb):
        mock_gh.return_value = {
            "last_run": {"name": "CI", "conclusion": "success", "created_at": "2026-04-29T07:00:00Z", "url": "https://github.com/test/repo/actions/runs/1"},
            "recent_runs": [],
        }
        mock_cb.return_value = {
            "last_build": {"status": "SUCCESS", "duration": "120s", "trigger": "push", "id": "build-1"},
            "recent_builds": [],
        }

        result = run_ci_cd_check()

        assert result["status"] == "pass"
        gh_check = next(c for c in result["checks"] if c["name"] == "github_ci")
        assert gh_check["status"] == "pass"

    @patch("routines.ci_cd._fetch_cloud_builds")
    @patch("routines.ci_cd._fetch_github_runs")
    def test_failed_run_returns_fail(self, mock_gh, mock_cb):
        mock_gh.return_value = {
            "last_run": {"name": "CI", "conclusion": "failure", "created_at": "2026-04-29T07:00:00Z", "url": "https://github.com/test/repo/actions/runs/1"},
            "recent_runs": [],
        }
        mock_cb.return_value = {
            "last_build": {"status": "SUCCESS", "duration": "120s", "trigger": "push", "id": "build-1"},
            "recent_builds": [],
        }

        result = run_ci_cd_check()

        assert result["status"] == "fail"

    @patch("routines.ci_cd._fetch_cloud_builds")
    @patch("routines.ci_cd._fetch_github_runs")
    def test_in_progress_returns_warn(self, mock_gh, mock_cb):
        mock_gh.return_value = {
            "last_run": {"name": "CI", "conclusion": None, "status": "in_progress", "created_at": "2026-04-29T07:00:00Z", "url": "https://github.com/test/repo/actions/runs/1"},
            "recent_runs": [],
        }
        mock_cb.return_value = {
            "last_build": {"status": "SUCCESS", "duration": "120s", "trigger": "push", "id": "build-1"},
            "recent_builds": [],
        }

        result = run_ci_cd_check()

        assert result["status"] == "warn"

    @patch("routines.ci_cd._fetch_cloud_builds")
    @patch("routines.ci_cd._fetch_github_runs")
    def test_github_unavailable_returns_warn(self, mock_gh, mock_cb):
        mock_gh.return_value = None
        mock_cb.return_value = {
            "last_build": {"status": "SUCCESS", "duration": "120s", "trigger": "push", "id": "build-1"},
            "recent_builds": [],
        }

        result = run_ci_cd_check()

        gh_check = next(c for c in result["checks"] if c["name"] == "github_ci")
        assert gh_check["status"] == "warn"
        assert "unavailable" in gh_check["detail"]
