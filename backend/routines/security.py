"""Security static analysis routine — scans source files in the container."""

import glob
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Base directory: where the backend source lives (same dir as this file's parent)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_file(rel_path: str) -> str:
    """Read a file relative to backend dir. Returns empty string on failure."""
    try:
        with open(os.path.join(_BACKEND_DIR, rel_path), encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _check_cors() -> dict[str, Any]:
    content = _read_file("main.py")
    has_wildcard = '"*"' in content and "allowed_origins" in content
    # Check that localhost is only in development block
    dev_gated = 'if ENVIRONMENT == "development"' in content or "if ENVIRONMENT == 'development'" in content
    # Extract just the initial list assignment (up to the closing bracket)
    list_match = re.search(r'allowed_origins\s*=\s*\[([^\]]*)\]', content, re.DOTALL)
    localhost_in_main_list = list_match and "localhost" in list_match.group(1) if list_match else False

    if has_wildcard:
        return {"name": "cors", "status": "fail", "detail": "Wildcard * in allowed origins"}
    if localhost_in_main_list:
        return {"name": "cors", "status": "fail", "detail": "Localhost in base allowed_origins list"}
    if dev_gated:
        return {"name": "cors", "status": "pass", "detail": "Localhost only in development mode"}
    return {"name": "cors", "status": "warn", "detail": "Could not verify CORS configuration"}


def _check_security_headers() -> dict[str, Any]:
    content = _read_file("main.py")
    required = [
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "X-XSS-Protection",
        "Referrer-Policy",
        "Permissions-Policy",
    ]
    found = sum(1 for h in required if h in content)
    if found == 7:
        return {"name": "security_headers", "status": "pass", "detail": "7/7"}
    return {"name": "security_headers", "status": "warn", "detail": f"{found}/7"}


def _check_hardcoded_secrets() -> dict[str, Any]:
    patterns = [
        r'sk-[a-zA-Z0-9]{20,}',
        r'AKIA[0-9A-Z]{16}',
    ]
    findings = []
    for py_file in glob.glob(os.path.join(_BACKEND_DIR, "**", "*.py"), recursive=True):
        if "tests" in py_file or "__pycache__" in py_file:
            continue
        try:
            with open(py_file, encoding="utf-8") as f:
                content = f.read()
            for pattern in patterns:
                if re.search(pattern, content):
                    rel = os.path.relpath(py_file, _BACKEND_DIR)
                    findings.append(rel)
        except Exception:
            continue

    if findings:
        return {"name": "hardcoded_secrets", "status": "fail", "detail": f"Found in: {', '.join(findings)}"}
    return {"name": "hardcoded_secrets", "status": "pass", "detail": "None found"}


def _check_admin_protection() -> dict[str, Any]:
    routers_dir = os.path.join(_BACKEND_DIR, "routers")
    unprotected = []
    for py_file in glob.glob(os.path.join(routers_dir, "*.py")):
        try:
            with open(py_file, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        # Find all route functions with /api/admin/ paths
        route_pattern = r'@router\.(get|post|put|delete|patch)\(["\'](/api/admin/[^"\']+)'
        for match in re.finditer(route_pattern, content):
            path = match.group(2)
            # Find the function body after this decorator
            func_start = match.end()
            # Look for require_role in the next ~500 chars (function body)
            func_body = content[func_start:func_start + 500]
            # Token-based auth routes (org request) are intentionally unprotected
            if "/companies/request/" in path:
                continue
            if "require_role" not in func_body and "_verify_admin_or_scheduler" not in func_body:
                rel = os.path.relpath(py_file, _BACKEND_DIR)
                unprotected.append(f"{rel}:{path}")

    if unprotected:
        return {"name": "admin_protection", "status": "fail", "detail": f"Unprotected: {', '.join(unprotected)}"}
    return {"name": "admin_protection", "status": "pass", "detail": "All admin routes protected"}


def _check_rate_limiting() -> dict[str, Any]:
    content = _read_file("helpers/rate_limiting.py")
    categories = {
        "auth": "_check_auth_rate_limit",
        "api": "_check_api_rate_limit",
        "public_chat": "_check_rate_limit",
        "org_request": "_check_org_request_rate_limit",
        "2fa": "_check_2fa_rate_limit",
        "password_change": "_check_password_change_rate_limit",
    }
    found = {name for name, func in categories.items() if func in content}
    missing = set(categories.keys()) - found
    if not missing:
        return {"name": "rate_limiting", "status": "pass", "detail": f"{len(found)}/6 categories"}
    return {"name": "rate_limiting", "status": "warn", "detail": f"{len(found)}/6 (missing: {', '.join(missing)})"}


def _check_jwt_validation() -> dict[str, Any]:
    content = _read_file("auth.py")
    if "raise RuntimeError" in content and "JWT" in content:
        return {"name": "jwt_validation", "status": "pass", "detail": "Raises RuntimeError on missing secret"}
    return {"name": "jwt_validation", "status": "fail", "detail": "No RuntimeError on missing JWT secret"}


def _check_sql_injection() -> dict[str, Any]:
    pattern = r'text\(f["\']'
    findings = []
    for py_file in glob.glob(os.path.join(_BACKEND_DIR, "**", "*.py"), recursive=True):
        if "tests" in py_file or "__pycache__" in py_file:
            continue
        try:
            with open(py_file, encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if re.search(pattern, line):
                        rel = os.path.relpath(py_file, _BACKEND_DIR)
                        findings.append(f"{rel}:{i}")
        except Exception:
            continue

    if findings:
        return {"name": "sql_injection", "status": "warn", "detail": f"{len(findings)} f-string SQL patterns: {', '.join(findings)}"}
    return {"name": "sql_injection", "status": "pass", "detail": "No unsafe SQL patterns"}


def _check_dependency_pinning() -> dict[str, Any]:
    content = _read_file("requirements.txt")
    lines = [l.strip() for l in content.strip().splitlines() if l.strip() and not l.startswith("#")]
    total = len(lines)
    pinned = sum(1 for l in lines if "==" in l)

    if total == 0:
        return {"name": "dependency_pinning", "status": "warn", "detail": "No dependencies found"}
    ratio = pinned / total
    if ratio >= 0.5:
        return {"name": "dependency_pinning", "status": "pass", "detail": f"{pinned}/{total} pinned"}
    return {"name": "dependency_pinning", "status": "warn", "detail": f"{pinned}/{total} pinned"}


def run_security_check() -> dict[str, Any]:
    """Run all security checks and return structured report."""
    checks = [
        _check_cors(),
        _check_security_headers(),
        _check_hardcoded_secrets(),
        _check_admin_protection(),
        _check_rate_limiting(),
        _check_jwt_validation(),
        _check_sql_injection(),
        _check_dependency_pinning(),
    ]

    statuses = [c["status"] for c in checks]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "pass"

    return {"status": overall, "checks": checks}
