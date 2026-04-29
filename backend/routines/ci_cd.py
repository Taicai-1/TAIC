"""CI/CD monitoring routine — checks GitHub Actions and Cloud Build status."""

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")


def _fetch_github_runs() -> Optional[dict[str, Any]]:
    """Fetch last 5 GitHub Actions runs. Returns None on failure."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        logger.warning("GITHUB_TOKEN or GITHUB_REPO not set, skipping GitHub check")
        return None

    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs",
            params={"per_page": 5},
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"},
            timeout=15,
        )
        resp.raise_for_status()
        runs = resp.json().get("workflow_runs", [])
        if not runs:
            return {"last_run": None, "recent_runs": []}

        def _format_run(r):
            return {
                "name": r.get("name"),
                "conclusion": r.get("conclusion"),
                "status": r.get("status"),
                "created_at": r.get("created_at"),
                "url": r.get("html_url"),
            }

        return {
            "last_run": _format_run(runs[0]),
            "recent_runs": [_format_run(r) for r in runs[:5]],
        }
    except Exception as e:
        logger.error(f"GitHub Actions fetch failed: {e}")
        return None


def _fetch_cloud_builds() -> Optional[dict[str, Any]]:
    """Fetch last 5 Cloud Build builds. Returns None on failure."""
    if not GCP_PROJECT_ID:
        logger.warning("GCP_PROJECT_ID not set, skipping Cloud Build check")
        return None

    try:
        from google.cloud.devtools import cloudbuild_v1

        client = cloudbuild_v1.CloudBuildClient()
        request = cloudbuild_v1.ListBuildsRequest(project_id=GCP_PROJECT_ID, page_size=5)
        response = client.list_builds(request=request)

        builds = list(response.builds) if hasattr(response, "builds") else list(response)
        if not builds:
            return {"last_build": None, "recent_builds": []}

        def _format_build(b):
            status_name = b.status.name if hasattr(b.status, "name") else str(b.status)
            duration_s = ""
            if b.finish_time and b.start_time:
                duration_s = f"{(b.finish_time - b.start_time).total_seconds():.0f}s"
            return {
                "status": status_name,
                "duration": duration_s,
                "trigger": getattr(b.build_trigger_id, "", "manual"),
                "id": b.id,
            }

        return {
            "last_build": _format_build(builds[0]),
            "recent_builds": [_format_build(b) for b in builds[:5]],
        }
    except Exception as e:
        logger.error(f"Cloud Build fetch failed: {e}")
        return None


def run_ci_cd_check() -> dict[str, Any]:
    """Run CI/CD checks and return structured report."""
    checks: list[dict[str, Any]] = []
    github_data = _fetch_github_runs()
    cloud_build_data = _fetch_cloud_builds()

    # GitHub Actions check
    if github_data is None:
        checks.append({"name": "github_ci", "status": "warn", "detail": "GitHub API unavailable"})
    elif github_data["last_run"] is None:
        checks.append({"name": "github_ci", "status": "warn", "detail": "No runs found"})
    else:
        run = github_data["last_run"]
        conclusion = run.get("conclusion")
        status = run.get("status")
        if conclusion == "success":
            checks.append({"name": "github_ci", "status": "pass", "detail": f"CI: success ({run['created_at']})"})
        elif conclusion == "failure":
            checks.append({"name": "github_ci", "status": "fail", "detail": f"CI: failure ({run['created_at']})"})
        elif status == "in_progress" or conclusion is None:
            checks.append({"name": "github_ci", "status": "warn", "detail": f"CI: in progress ({run['created_at']})"})
        else:
            checks.append({"name": "github_ci", "status": "warn", "detail": f"CI: {conclusion}"})

    # Cloud Build check
    if cloud_build_data is None:
        checks.append({"name": "cloud_build", "status": "warn", "detail": "Cloud Build API unavailable"})
    elif cloud_build_data["last_build"] is None:
        checks.append({"name": "cloud_build", "status": "warn", "detail": "No builds found"})
    else:
        build = cloud_build_data["last_build"]
        build_status = build["status"]
        if build_status == "SUCCESS":
            checks.append({"name": "cloud_build", "status": "pass", "detail": f"Last build succeeded ({build['duration']})"})
        elif build_status in ("FAILURE", "INTERNAL_ERROR", "TIMEOUT"):
            checks.append({"name": "cloud_build", "status": "fail", "detail": f"Last build: {build_status}"})
        elif build_status == "WORKING":
            checks.append({"name": "cloud_build", "status": "warn", "detail": "Build in progress"})
        else:
            checks.append({"name": "cloud_build", "status": "warn", "detail": f"Build status: {build_status}"})

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
        "github_actions": github_data,
        "cloud_build": cloud_build_data,
    }
