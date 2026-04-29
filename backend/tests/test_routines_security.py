"""Tests for routines.security — reads real source files from the backend directory."""

from routines.security import run_security_check


class TestRunSecurityCheck:
    def test_returns_all_8_checks(self):
        result = run_security_check()
        check_names = [c["name"] for c in result["checks"]]
        expected = [
            "cors", "security_headers", "hardcoded_secrets",
            "admin_protection", "rate_limiting", "jwt_validation",
            "sql_injection", "dependency_pinning",
        ]
        assert check_names == expected

    def test_status_is_string(self):
        result = run_security_check()
        assert result["status"] in ("pass", "warn", "fail")

    def test_cors_check_passes(self):
        """CORS should pass because localhost is gated behind ENVIRONMENT==development."""
        result = run_security_check()
        cors = next(c for c in result["checks"] if c["name"] == "cors")
        assert cors["status"] == "pass"

    def test_security_headers_passes(self):
        """All 7 security headers are present in main.py middleware."""
        result = run_security_check()
        headers = next(c for c in result["checks"] if c["name"] == "security_headers")
        assert headers["status"] == "pass"
        assert "7/7" in headers["detail"]

    def test_hardcoded_secrets_passes(self):
        """No hardcoded API keys in the codebase."""
        result = run_security_check()
        secrets = next(c for c in result["checks"] if c["name"] == "hardcoded_secrets")
        assert secrets["status"] == "pass"

    def test_dependency_pinning_warns_or_fails(self):
        """Current requirements.txt has 0 pinned deps — should be warn or fail."""
        result = run_security_check()
        deps = next(c for c in result["checks"] if c["name"] == "dependency_pinning")
        assert deps["status"] in ("warn", "fail")
