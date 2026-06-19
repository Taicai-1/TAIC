# WS4 — Auth & Secrets Hardening Implementation Plan

> Execute task-by-task (superpowers:executing-plans).

**Goal:** Close the highest-value auth gaps before the client launch: guarantee secrets are encrypted in prod, stop password brute-force per-account, give 2FA users a recovery path (backup codes), and shorten the session-token lifetime.

**Verified state (2026-06-18):** `encryption._get_fernet()` raises in prod but only LAZILY (auth.py:25-29). JWT default expiry `timedelta(hours=8)` (auth.py:44); cookies `max_age=28800`; no refresh. Login (`routers/auth.py:114-213`) has per-IP rate-limit only (`_check_auth_rate_limit`/`_record_auth_failure`), NO per-user lockout. `User.totp_backup_codes` column exists but is NEVER generated or verified — the `confirm_2fa_setup` docstring even claims it generates them. `hash_password`/`verify_password` = bcrypt (auth.py:28-35).

---

## Task 1: ENCRYPTION_KEY fail-fast at startup

**Files:** `backend/main.py` (startup event, after `ensure_llm_usage_table()`).

**Why:** Today a prod boot without `ENCRYPTION_KEY` only fails on the FIRST encrypt/decrypt (could be much later, after plaintext was nearly written). Validate up-front.

- [ ] **Step 1:** In `main.py` startup, right after the `with migration_lock():` block (after `logger.info("Database initialization completed successfully...")`), add:

```python
        # WS4: in production, refuse to start if secrets can't be encrypted.
        if os.getenv("GOOGLE_CLOUD_PROJECT"):
            from encryption import _get_fernet

            _get_fernet()  # raises RuntimeError if ENCRYPTION_KEY missing
            logger.info("ENCRYPTION_KEY validation passed")
```

- [ ] **Step 2:** Verify import (`import main` with dummy env, no GOOGLE_CLOUD_PROJECT → no raise). Run full suite.
- [ ] **Step 3:** Commit `fix(security): fail-fast at startup if ENCRYPTION_KEY missing in production`.

---

## Task 2: Per-user login lockout

**Files:** `backend/helpers/rate_limiting.py` (2 new fns), `backend/routers/auth.py` (wire into login), tests.

**Why:** IP rate-limit alone is bypassable (rotating IPs) and doesn't protect a targeted account. Add a per-user lockout in Redis (in-memory fallback), mirroring `_check_auth_rate_limit`/`_record_auth_failure`.

- [ ] **Step 1:** Add to `rate_limiting.py` (mirror the existing auth-rate-limit fns; reuse the same Redis client + fallback dict pattern):

```python
_LOGIN_LOCKOUT_LIMIT = 5          # failures before lockout
_LOGIN_LOCKOUT_WINDOW = 600       # seconds (10 min)


def _check_login_lockout(user_id: str) -> bool:
    """Return True if the account is NOT locked (login may proceed)."""
    key = f"rate_limit:login:{user_id}"
    r = get_redis()
    if r is not None:
        try:
            count = int(r.get(key) or 0)
            return count < _LOGIN_LOCKOUT_LIMIT
        except Exception:
            pass
    return _fallback_count(key) < _LOGIN_LOCKOUT_LIMIT


def _record_login_failure(user_id: str) -> None:
    """Record a failed login for an account; lock after _LOGIN_LOCKOUT_LIMIT in the window."""
    key = f"rate_limit:login:{user_id}"
    r = get_redis()
    if r is not None:
        try:
            new = r.incr(key)
            if new == 1:
                r.expire(key, _LOGIN_LOCKOUT_WINDOW)
            return
        except Exception:
            pass
    _fallback_incr(key, _LOGIN_LOCKOUT_WINDOW)
```

> Confirm the exact names of the existing fallback helpers in `rate_limiting.py` (the IP path uses an in-memory dict + a count/incr helper). Reuse them; if they are inlined rather than named `_fallback_count`/`_fallback_incr`, replicate that inline pattern instead. Keep the implementation identical in spirit to `_check_auth_rate_limit`/`_record_auth_failure`.

- [ ] **Step 2:** Wire into `login` (`routers/auth.py`). Import the two fns. After resolving `db_user` (line ~125, before/after password check), enforce + record per-user:
  - Right after `db_user` is found (and is a password user), before `verify_password`, add:
    ```python
        if not _check_login_lockout(str(db_user.id)):
            raise HTTPException(status_code=429, detail="Account temporarily locked after too many failed attempts. Try again later.")
    ```
  - In the `if not verify_password(...)` block (line 136-138), add `_record_login_failure(str(db_user.id))` alongside the existing `_record_auth_failure(ip)`.
  - On the successful-login path (before issuing the full access token, line ~197), clear the counter: add a `_clear_login_failures(str(db_user.id))` helper (delete the Redis key / fallback entry) and call it. Add that helper in step 1 too.

- [ ] **Step 3:** Tests (`tests/test_endpoints_auth.py` or new `test_login_lockout.py`, using `mock_redis`): 5 wrong-password attempts → 6th returns 429 even with the correct password; a successful login resets the counter. (Use the `mock_redis` fixture so it's deterministic and runs without a live Redis.)
- [ ] **Step 4:** Run full suite. Commit `feat(security): per-account login lockout after repeated failures`.

---

## Task 3: 2FA backup codes (generation + verification)

**Files:** `backend/auth.py` (2 helpers), `backend/routers/auth.py` (`confirm_2fa_setup`, `verify_2fa`), tests.

**Why:** A user who loses their TOTP device is permanently locked out today. The column exists; wire it up.

- [ ] **Step 1:** Add helpers to `auth.py`:

```python
import json
import secrets as _secrets


def generate_backup_codes(n: int = 10) -> tuple[list[str], str]:
    """Return (plaintext_codes, json_of_bcrypt_hashes). Show plaintext to the user ONCE."""
    codes = [f"{_secrets.token_hex(4)}-{_secrets.token_hex(4)}" for _ in range(n)]
    hashes = [hash_password(c) for c in codes]
    return codes, json.dumps(hashes)


def verify_and_consume_backup_code(code: str, backup_codes_json: str | None) -> tuple[bool, str | None]:
    """Check `code` against the stored hashes. On match, return (True, new_json_without_used_code).
    On no match, return (False, None)."""
    if not backup_codes_json:
        return False, None
    try:
        hashes = json.loads(backup_codes_json)
    except Exception:
        return False, None
    for h in hashes:
        if verify_password(code.strip(), h):
            remaining = [x for x in hashes if x != h]
            return True, json.dumps(remaining)
    return False, None
```

- [ ] **Step 2:** In `confirm_2fa_setup` (`routers/auth.py:524-542`), after `db_user.totp_enabled = True` and before `db.commit()`, generate + store codes and return them ONCE:

```python
    from auth import generate_backup_codes

    plaintext_codes, hashed_json = generate_backup_codes()
    db_user.totp_backup_codes = hashed_json
    # ... existing db.commit(), token, cookies ...
    return {"access_token": access_token, "token_type": "bearer", "backup_codes": plaintext_codes}
```

- [ ] **Step 3:** In `verify_2fa` (`routers/auth.py:565-569`), when the TOTP check fails, fall back to a backup code before raising:

```python
    if not totp.verify(body.code.strip(), valid_window=1):
        from auth import verify_and_consume_backup_code

        ok, new_json = verify_and_consume_backup_code(body.code, db_user.totp_backup_codes)
        if not ok:
            raise HTTPException(status_code=400, detail="Invalid verification code")
        db_user.totp_backup_codes = new_json
        db.commit()
        invalidate_user_cache(db_user.id)
```

> Note: `verify_2fa` loads `db_user` via `get_cached_user`; ensure the mutated `totp_backup_codes` is committed on the session and the cache invalidated (as above).

- [ ] **Step 4:** Tests (`tests/test_endpoints_auth.py`/new): confirm-setup returns a non-empty `backup_codes` list of 10; a backup code works at `verify_2fa` when TOTP is wrong; the SAME backup code fails the second time (consumed). Mock TOTP as needed.
- [ ] **Step 5:** Run full suite. Commit `feat(security): generate + verify single-use 2FA backup codes`.

---

## Task 4: Configurable, shorter JWT expiry

**Files:** `backend/auth.py`, `backend/routers/auth.py` (cookie max_age alignment).

- [ ] **Step 1:** In `auth.py`, make expiry env-driven (default 4h, down from 8h) and export the seconds for cookies:

```python
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "4"))
ACCESS_TOKEN_MAX_AGE = ACCESS_TOKEN_EXPIRE_HOURS * 3600
```

and in `create_access_token`, replace `timedelta(hours=8)` with `timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)`.

- [ ] **Step 2:** In `routers/auth.py`, replace the hardcoded `max_age=28800` on the THREE full-access-token cookies (login line ~202, confirm-setup ~534, verify ~575) with `max_age=ACCESS_TOKEN_MAX_AGE` (import it from `auth`). Do NOT touch the pre_2fa (300) / setup (1800) cookie max-ages.
- [ ] **Step 3:** Run full suite (the JWT unit tests in `test_auth.py` should still pass — they pass explicit `expires_delta`). Commit `chore(security): make JWT expiry configurable, default 4h (was 8h); refresh tokens = backlog`.

---

## Task 5 (OPS): Rotate the leaked GitHub PAT

- [ ] A GitHub PAT was previously committed into the auto-memory file and has been removed there. **The owner must revoke/rotate it in GitHub → Settings → Developer settings → Personal access tokens.** Removing it from the file does not invalidate it. (No repo change.)

---

## Definition of Done
- Prod startup logs `ENCRYPTION_KEY validation passed` (T1).
- 6th wrong password → 429 even if correct; success resets (T2, tested).
- confirm-setup returns 10 backup codes; one works once at verify, then is consumed (T3, tested).
- JWT expiry = `JWT_EXPIRE_HOURS` (default 4h); cookies aligned (T4).
- PAT revoked by owner (T5).

## Self-review
- T1-T4 are code with tests; lockout + backup-code tests use `mock_redis`/mocked TOTP so they run in CI without external services.
- Refresh tokens explicitly deferred (documented) to avoid a half-built refresh flow under deadline; 4h is a usable middle without refresh.
- Backup codes reuse bcrypt (`hash_password`/`verify_password`) — same primitive as passwords; codes shown once, single-use (consumed on use).
