"""WS4: per-account login lockout helpers (in-memory fallback path, no DB/Redis)."""

import helpers.rate_limiting as rl


def test_lockout_triggers_after_limit():
    rl._login_lockout_fallback.clear()
    uid = "test-user-1"
    for _ in range(rl._LOGIN_LOCKOUT_LIMIT):
        assert rl._check_login_lockout(uid) is True  # not locked yet
        rl._record_login_failure(uid)
    assert rl._check_login_lockout(uid) is False  # locked after the limit


def test_lockout_clears_on_success():
    rl._login_lockout_fallback.clear()
    uid = "test-user-2"
    for _ in range(rl._LOGIN_LOCKOUT_LIMIT):
        rl._record_login_failure(uid)
    assert rl._check_login_lockout(uid) is False
    rl._clear_login_failures(uid)
    assert rl._check_login_lockout(uid) is True  # reset


def test_lockout_is_per_account():
    rl._login_lockout_fallback.clear()
    for _ in range(rl._LOGIN_LOCKOUT_LIMIT):
        rl._record_login_failure("victim")
    assert rl._check_login_lockout("victim") is False
    assert rl._check_login_lockout("other") is True  # a different account is unaffected
