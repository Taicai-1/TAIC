# Support Account (cross-company) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development) to implement task-by-task. Steps use `- [ ]` checkboxes.

**Goal:** Let `contact@taic.co` (a `User.is_support` account) pick any company after login and act with owner-equivalent rights inside that single company, with 2FA, audit, a visible banner, and locked-down account creation.

**Architecture:** Approach A — the support user's chosen company is an `active_company_id` JWT claim set by a switch endpoint. The tenant middleware resolves the *effective* company (support → claim, normal user → `user.company_id`), sets the existing RLS GUC contextvar to it, and flags a `support_session`. Permissions return a synthetic owner membership and ownership checks defer to `is_support_session()` — all bounded by RLS to the one active company.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Postgres RLS, PyJWT, Next.js.

**Key existing mechanics (reuse, don't reinvent):**
- `database._current_company_id` contextvar + `set_current_company_id()`; `get_db` / `after_begin` event do `SET LOCAL app.company_id` from it (database.py:913-939).
- `create_access_token(data: dict, expires_delta=None)` encodes arbitrary claims (auth.py).
- Tenant middleware decodes the JWT and loads the user (main.py:218-253).
- `permissions.get_user_membership` / `require_role` (permissions.py:19-37).
- `helpers/tenant._get_caller_company_id` reads `user.company_id` (helpers/tenant.py).

---

## Task 1: Data model + contextvars

**Files:** Modify `backend/database.py`; Test `backend/tests/test_support_account.py`.

- [ ] **Step 1:** Add the `is_support` column to the `User` model (near the other User columns):
```python
    is_support = Column(Boolean, default=False, nullable=False)  # platform support account (cross-company)
```

- [ ] **Step 2:** Add the audit model (after the `Company` class, like `LLMUsageLog`):
```python
class SupportAuditLog(Base):
    """Audit trail of support-account actions (platform-level, no tenant RLS)."""

    __tablename__ = "support_audit_logs"
    __table_args__ = (Index("ix_support_audit_created", "created_at"),)

    id = Column(Integer, primary_key=True, index=True)
    support_user_id = Column(Integer, nullable=False, index=True)
    target_company_id = Column(Integer, nullable=True)
    method = Column(String(10), nullable=False)
    path = Column(String(300), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
```

- [ ] **Step 3:** Add contextvars + helpers near `_current_company_id` (top of database.py, ~line 16) and `set_current_company_id` (~line 920):
```python
# (top, with the other contextvar)
_support_session: contextvars.ContextVar[bool] = contextvars.ContextVar("support_session", default=False)
```
```python
# (near set_current_company_id)
def get_current_company_id():
    """Effective company_id for the current request context (set by middleware)."""
    return _current_company_id.get()


def set_support_session(value: bool):
    _support_session.set(bool(value))


def is_support_session() -> bool:
    """True when the current request is a support account operating in a chosen company."""
    return _support_session.get()
```

- [ ] **Step 4:** Add `ensure_support_tables()` (mirror `ensure_llm_usage_table`):
```python
def ensure_support_tables():
    """Add User.is_support + support_audit_logs on existing DBs (idempotent)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SET lock_timeout = '5s'"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_support BOOLEAN NOT NULL DEFAULT FALSE"))
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS support_audit_logs ("
                    "id SERIAL PRIMARY KEY, support_user_id INTEGER NOT NULL, target_company_id INTEGER, "
                    "method VARCHAR(10) NOT NULL, path VARCHAR(300) NOT NULL, created_at TIMESTAMP DEFAULT NOW())"
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_support_audit_created ON support_audit_logs (created_at)"))
            conn.commit()
        print("ensure_support_tables completed", flush=True)
    except Exception as e:
        print(f"ensure_support_tables failed: {e}", flush=True)
```
Call it in `main.py` startup inside the `with migration_lock():` block, right after `ensure_llm_usage_table()`, and import it.

- [ ] **Step 5: Test** (`tests/test_support_account.py`):
```python
def test_is_support_defaults_false():
    from tests.factories import UserFactory

    u = UserFactory.build()
    assert getattr(u, "is_support", False) in (False, None)
```
Run `cd backend && python -m pytest tests/test_support_account.py -q` (skips/passes). Confirm `import database` ok (dummy env).

- [ ] **Step 6: Commit** `feat(support): is_support column, SupportAuditLog, support-session contextvars`.

---

## Task 2: Effective-company resolution in the tenant middleware

**Files:** Modify `backend/main.py` (`tenant_isolation_middleware`), `backend/helpers/tenant.py`.

- [ ] **Step 1:** In `tenant_isolation_middleware` (main.py), replace the body that resolves the user/company so it honors a support `active_company_id` claim. The current block sets company only from `user.company_id`; change to:
```python
            if user_id and token_type not in ("pre_2fa", "needs_2fa_setup"):
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.id == int(user_id)).first()
                    if user:
                        effective = user.company_id
                        support_active = False
                        if getattr(user, "is_support", False):
                            claim = payload.get("active_company_id")
                            if claim is not None:
                                from database import Company

                                exists = db.query(Company.id).filter(Company.id == int(claim)).first()
                                effective = int(claim) if exists else None
                            else:
                                effective = None
                            support_active = effective is not None
                        if effective is not None:
                            set_current_company_id(effective)
                        set_support_session(support_active)
                finally:
                    db.close()
```
Import `set_support_session` from `database` at the top of main.py (with `set_current_company_id`).

- [ ] **Step 2:** In `helpers/tenant.py`, make `_get_caller_company_id` honor the effective contextvar:
```python
def _get_caller_company_id(user_id, db: Session) -> Optional[int]:
    """Resolve the company_id for the current caller. Honors a support account's
    active company (set by the tenant middleware); falls back to the user's own
    company for non-request contexts (e.g. background jobs)."""
    from database import get_current_company_id

    active = get_current_company_id()
    if active is not None:
        return active
    user = get_cached_user(user_id, db)
    return user.company_id if user else None
```

- [ ] **Step 3:** Smoke-import `main`; run the full suite (no regression — for normal users `active == user.company_id`). Commit `feat(support): resolve active company from JWT claim in tenant middleware`.

---

## Task 3: Synthetic owner membership for support

**Files:** Modify `backend/permissions.py`; Test in `tests/test_support_account.py`.

- [ ] **Step 1: Test** (PG not required — pure logic with a fake db is awkward; use a PG-backed test in Task 9 instead). Here add a unit check that the synthetic path triggers via `is_support_session`. Skip a dedicated test; covered by Task 9 endpoint tests.

- [ ] **Step 2:** Update `permissions.py`:
```python
from database import CompanyMembership, is_support_session, get_current_company_id


def get_user_membership(user_id: int, db: Session) -> Optional[CompanyMembership]:
    """Return the user's CompanyMembership, or a synthetic owner membership in the
    active company when this is a support session."""
    if is_support_session():
        active = get_current_company_id()
        if active is not None:
            return CompanyMembership(user_id=user_id, company_id=active, role="owner")
    return db.query(CompanyMembership).filter(CompanyMembership.user_id == user_id).first()
```
`require_role` is unchanged: with a synthetic `role="owner"` it passes for any `min_role`. A support user with NO active company has `is_support_session()` False → falls through to the real (likely None) membership → `require_role` raises 404/403, which is the desired "select a company first" behavior (message refinement optional).

- [ ] **Step 3:** Smoke-import; run suite. Commit `feat(support): synthetic owner membership in the active company`.

---

## Task 4: Ownership-check bypass (bounded by RLS)

**Files:** Modify `backend/helpers/agent_helpers.py`, `backend/helpers/conversation_helpers.py`, `backend/routers/agents.py`.

For each ownership gate, allow access when `is_support_session()` is true (RLS already restricts rows to the active company).

- [ ] **Step 1:** `helpers/agent_helpers.py` — in `_user_can_access_agent` and `_user_can_edit_agent`, at the point where access is otherwise denied, add an early allow. Read each function and insert, right after the agent is fetched and confirmed to exist:
```python
    from database import is_support_session

    if is_support_session():
        return agent  # support acts as owner within the RLS-bounded active company
```
(Place it after the `agent` is loaded / existence-checked, before the owner/share checks.)

- [ ] **Step 2:** `helpers/conversation_helpers.py` — in `verify_conversation_owner`, after `conv` is loaded and confirmed non-null:
```python
    from database import is_support_session

    if is_support_session():
        return conv
```

- [ ] **Step 3:** `routers/agents.py` — `delete_agent` checks `agent.user_id == uid`; `update_team_members` / the team patch endpoint query `Team.id == team_id, Team.user_id == int(user_id)`. For these, fetch the row without the `user_id` filter (RLS already scopes to company) when support, OR add `or is_support_session()`. Concretely, in `delete_agent` change the ownership guard to:
```python
    from database import is_support_session

    if agent.user_id != uid and not is_support_session():
        raise HTTPException(status_code=403, detail="Not allowed")
```
For team endpoints that do `db.query(Team).filter(Team.id == team_id, Team.user_id == int(user_id)).first()`: when `is_support_session()`, drop the `Team.user_id` filter (RLS still scopes to the active company). Read each and apply the minimal change.

- [ ] **Step 4:** Run agent/team/conversation endpoint tests; full suite. Commit `feat(support): bypass ownership checks within the active company`.

---

## Task 5: Support router (list companies + switch active company)

**Files:** Create `backend/routers/support.py`; register in `backend/main.py`; Test in Task 9.

- [ ] **Step 1:** Create `backend/routers/support.py`:
```python
"""Support-account endpoints: list companies + switch the active company.

Gated on User.is_support. The active company is carried as a JWT claim re-issued
by the switch endpoint; the tenant middleware enforces it.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from auth import verify_token, create_access_token, ACCESS_TOKEN_MAX_AGE
from database import get_db, User, Company, SupportAuditLog

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_support(user_id: str, db: Session) -> User:
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not getattr(user, "is_support", False):
        raise HTTPException(status_code=403, detail="Support access required")
    return user


@router.get("/api/support/companies")
async def list_companies(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    _require_support(user_id, db)
    rows = db.query(Company.id, Company.name).order_by(Company.name.asc()).all()
    return {"companies": [{"id": cid, "name": name} for cid, name in rows]}


@router.post("/api/support/active-company")
async def set_active_company(
    request: Request, response: Response, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    _require_support(user_id, db)
    body = await request.json()
    company_id = body.get("company_id")
    company = db.query(Company).filter(Company.id == company_id).first() if company_id is not None else None
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Re-issue the access-token cookie carrying the active company claim.
    token = create_access_token(data={"sub": str(user_id), "active_company_id": int(company.id)})
    response.set_cookie(
        key="token", value=token, httponly=True, secure=True, samesite="lax", max_age=ACCESS_TOKEN_MAX_AGE, path="/"
    )

    db.add(
        SupportAuditLog(
            support_user_id=int(user_id), target_company_id=int(company.id), method="SWITCH", path="/api/support/active-company"
        )
    )
    db.commit()
    logger.info(f"Support user {user_id} switched to company {company.id}")
    return {"active_company_id": company.id, "company_name": company.name}
```

> Note: `SupportAuditLog` is not RLS-protected, so the insert works regardless of the active company GUC.

- [ ] **Step 2:** Register in `main.py` (with the other `include_router` calls):
```python
from routers.support import router as support_router  # noqa: E402

app.include_router(support_router)
```

- [ ] **Step 3:** Smoke-import; commit `feat(support): /api/support/companies + /active-company switch endpoints`.

---

## Task 6: Audit middleware for state-changing support actions

**Files:** Modify `backend/main.py`.

- [ ] **Step 1:** Add a middleware AFTER the tenant middleware (so `is_support_session()` / company are set). It logs POST/PUT/PATCH/DELETE made during a support session:
```python
@app.middleware("http")
async def support_audit_middleware(request: Request, call_next):
    response = await call_next(request)
    try:
        from database import is_support_session, get_current_company_id, SessionLocal, SupportAuditLog

        if is_support_session() and request.method in ("POST", "PUT", "PATCH", "DELETE"):
            # Skip the switch endpoint (it logs its own entry).
            if request.url.path != "/api/support/active-company":
                _id = None
                token = request.cookies.get("token")
                if token:
                    import jwt as pyjwt

                    try:
                        _id = pyjwt.decode(token, os.getenv("JWT_SECRET_KEY", "").strip(), algorithms=["HS256"]).get("sub")
                    except Exception:
                        _id = None
                if _id:
                    db = SessionLocal()
                    try:
                        db.add(
                            SupportAuditLog(
                                support_user_id=int(_id),
                                target_company_id=get_current_company_id(),
                                method=request.method,
                                path=request.url.path[:300],
                            )
                        )
                        db.commit()
                    finally:
                        db.close()
    except Exception as exc:
        logger.warning("support_audit_middleware failed (non-fatal): %s", exc)
    return response
```
> Middleware ordering: FastAPI runs `@app.middleware` in reverse registration order; ensure the tenant middleware has already run when this executes. Verify by placing this registration ABOVE the tenant middleware in the file (so it wraps outermost and the tenant one runs first on the request path), or confirm contextvars are still set at response time. If contextvars are cleared, fall back to decoding `active_company_id` from the token here instead of `get_current_company_id()`.

- [ ] **Step 2:** Smoke-import; full suite. Commit `feat(support): audit log for state-changing support actions`.

---

## Task 7: Auth — 2FA mandatory + reserved email + verify fields

**Files:** Modify `backend/routers/auth.py`.

- [ ] **Step 1: 2FA mandatory for support.** In `login`, on the full-access-token path (after email + before issuing the final token), refuse for a support user without 2FA:
```python
        if getattr(db_user, "totp_enabled", False) is False and getattr(db_user, "is_support", False):
            # Support accounts MUST use 2FA; route them to setup.
            setup_token = create_access_token(
                data={"sub": str(db_user.id), "type": "needs_2fa_setup"}, expires_delta=timedelta(minutes=30)
            )
            response.set_cookie(key="setup_token", value=setup_token, httponly=True, secure=True, samesite="lax", max_age=1800, path="/")
            return {"requires_2fa_setup": True}
```
(Place before the existing `totp_enabled` branch; the existing flow already covers most cases, this closes any gap.)

- [ ] **Step 2: Reserved email at signup.** In `register`, near the duplicate-email check:
```python
        if user.email.strip().lower() == "contact@taic.co":
            raise HTTPException(status_code=400, detail="This email is reserved.")
```

- [ ] **Step 3: `/auth/verify` fields.** In `verify_auth`, include support info in the response. After resolving `db_user`, add `is_support` and `active_company`:
```python
    from database import get_current_company_id

    active_company = None
    if getattr(db_user, "is_support", False):
        acid = get_current_company_id()
        if acid is not None:
            from database import Company

            c = db.query(Company).filter(Company.id == acid).first()
            if c:
                active_company = {"id": c.id, "name": c.name}
    # ... merge into the existing returned dict:
    #   "is_support": bool(getattr(db_user, "is_support", False)),
    #   "active_company": active_company,
```
Read `verify_auth` and merge these two keys into its existing return payload (don't break existing fields).

- [ ] **Step 4:** Run auth tests; full suite. Commit `feat(support): mandatory 2FA, reserved email, verify exposes support state`.

---

## Task 8: Frontend — banner + company selector

**Files:** Modify `frontend/hooks/useAuth.js`, `frontend/components/Layout.js`, `frontend/components/Sidebar.js`.

- [ ] **Step 1:** Ensure `useAuth` exposes `user.is_support` and `user.active_company` (they come through from `/auth/verify` if `useAuth` returns the whole user object — verify; if it maps fields explicitly, add these two).

- [ ] **Step 2:** `Layout.js` — render a support banner when `user?.is_support`:
```jsx
{user?.is_support && (
  <div className="bg-red-600 text-white text-sm font-semibold px-6 py-2 text-center">
    Mode support — {user.active_company ? `entreprise : ${user.active_company.name}` : 'aucune entreprise sélectionnée'}
  </div>
)}
```
(Place at the top of the main area, above the existing no-org warning.)

- [ ] **Step 3:** `Sidebar.js` — for support users, render a company `<select>` above the nav that loads `/api/support/companies` and POSTs `/api/support/active-company` on change, then `window.location.reload()`:
```jsx
// inside the component, support-only block
{user?.is_support && (
  <SupportCompanyPicker current={user.active_company?.id} />
)}
```
Implement `SupportCompanyPicker` (same file or a small new component) using `api.get('/api/support/companies')` and `api.post('/api/support/active-company', { company_id })` then `window.location.reload()`. Use `api` from `lib/api`.

- [ ] **Step 4:** `npm run lint`; commit `feat(support): support-mode banner + company selector (frontend)`.

---

## Task 9: Integration tests (PG-backed)

**Files:** `backend/tests/test_support_account.py`.

- [ ] **Step 1:** Add tests (mirror the `tests.conftest` PG-skip pattern + `client`/`db_session`). A support fixture: a `User(is_support=True)` with a CompanyMembership-less account, in 2 separate companies A and B with data. Cover:
  - `GET /api/support/companies` as support → lists A and B; as a normal member → 403.
  - `POST /api/support/active-company {A}` → 200, sets cookie; a follow-up authenticated request sees A's agents; switching to B → sees B, not A.
  - Support with no selection → a protected list endpoint returns empty / `require_role` path 403.
  - A forged token carrying `active_company_id` for a NON-support user is ignored (the user sees only their own company).
  - Switching writes a `SupportAuditLog` row; a state-changing action writes one.
  - Regression: a normal user's company resolution unchanged.
  Use `create_access_token(data={"sub": str(support_user.id), "active_company_id": A.id})` to build the support cookie directly in tests where simpler than calling the switch endpoint.

- [ ] **Step 2:** Run full suite. Commit `test(support): cross-company support access + regression`.

---

## Task 10: Manual / ops

- [ ] After deploy, set the flag once: `UPDATE users SET is_support = true WHERE email = 'contact@taic.co';` (the account must exist; if not, create it via signup first — but signup now blocks that email, so create it, set the flag, or insert directly). Document this. Ensure the account has 2FA set up on first login.

---

## Definition of Done
- `contact@taic.co` (is_support, 2FA) logs in, sees the company selector + banner, picks a company, and has owner-level access to exactly that company's data; switching changes the company; never two at once.
- Non-support users completely unaffected (regression tests green).
- Every switch + state-changing support action is in `support_audit_logs`.
- Full suite green in CI.

## Self-review
- **Spec coverage:** is_support + audit table + claim (T1), middleware resolution + `_get_caller_company_id` (T2), synthetic owner (T3), ownership bypass (T4), endpoints (T5), audit (T6), 2FA/reserved-email/verify (T7), frontend banner+selector (T8), tests (T9), manual flag (T10). All spec sections mapped.
- **Placeholders:** the few "read X and apply the minimal change" steps (ownership inline checks, verify_auth merge, useAuth field mapping) point at exact functions with the exact snippet to insert — acceptable since they adapt to existing code shape; all new units have complete code.
- **Type consistency:** `is_support_session`, `get_current_company_id`, `set_support_session`, `SupportAuditLog`, `active_company_id` claim, `ACCESS_TOKEN_MAX_AGE` used consistently.
- **Security:** every cross-company power is gated on the server-rechecked `is_support` flag + bounded by the single-active-company RLS GUC; revocation = flip the flag.
