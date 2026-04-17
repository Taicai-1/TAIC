"""Unit tests for company creation request helpers."""

import pytest


class TestEmailRendering:
    def test_admin_notification_renders(self):
        from email_service import render_admin_org_request_email

        html = render_admin_org_request_email(
            requester_email="alice@example.com",
            requested_name="Ma Boîte",
            approve_url="https://api.taic.co/api/admin/companies/request/abc?action=approve",
            reject_url="https://api.taic.co/api/admin/companies/request/abc?action=reject",
        )
        assert "alice@example.com" in html
        assert "Ma Boîte" in html
        assert "Approuver" in html
        assert "Refuser" in html
        assert "https://api.taic.co/api/admin/companies/request/abc?action=approve" in html

    def test_user_approved_renders(self):
        from email_service import render_user_org_approved_email

        html = render_user_org_approved_email(
            requested_name="Ma Boîte",
            app_url="https://app.taic.co/organization",
        )
        assert "Ma Boîte" in html
        assert "approuvée" in html.lower()
        assert "https://app.taic.co/organization" in html

    def test_user_rejected_renders_with_reason(self):
        from email_service import render_user_org_rejected_email

        html = render_user_org_rejected_email(
            requested_name="Ma Boîte",
            reason="Nom non conforme",
            app_url="https://app.taic.co/organization",
        )
        assert "Ma Boîte" in html
        assert "Nom non conforme" in html

    def test_user_rejected_renders_without_reason(self):
        from email_service import render_user_org_rejected_email

        html = render_user_org_rejected_email(
            requested_name="Ma Boîte",
            reason=None,
            app_url="https://app.taic.co/organization",
        )
        assert "Ma Boîte" in html


class TestIpRateLimit:
    """In-memory fallback behavior (Redis path tested manually in staging)."""

    @pytest.fixture(autouse=True)
    def _main_module(self):
        try:
            import importlib
            import main

            importlib.reload(main)
            self.main = main
        except Exception:
            pytest.skip("main.py import requires full DB config")

    def test_allows_first_five_requests(self):
        ip = "10.0.0.1"
        for _ in range(5):
            assert self.main._check_org_request_rate_limit(ip) is True

    def test_blocks_sixth_request_within_window(self):
        ip = "10.0.0.2"
        for _ in range(5):
            self.main._check_org_request_rate_limit(ip)
        assert self.main._check_org_request_rate_limit(ip) is False

    def test_different_ips_isolated(self):
        for _ in range(5):
            self.main._check_org_request_rate_limit("10.0.0.3")
        assert self.main._check_org_request_rate_limit("10.0.0.4") is True
