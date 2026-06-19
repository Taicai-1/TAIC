# Support account — cross-company access design

**Date:** 2026-06-19
**Status:** Approved (design) — pending spec review
**Author:** Jeremy + Claude

## Context

TAIC is a multi-tenant SaaS where **1 user = 1 company**: the request's `company_id`
comes from `user.company_id`, which drives both Postgres RLS (what data is visible)
and `require_role`/`CompanyMembership` (what the user may do).

We need a **support account** (`contact@taic.co`) that, after login, can **choose any
company to operate in** and then act with **owner-equivalent rights** in that company —
to investigate and fix client issues. This is a deliberate, tightly-controlled
cross-tenant capability (the opposite of the isolation the rest of the system enforces),
so it must be locked down and audited.

### Decisions (from brainstorming)
- **Identification:** a `User.is_support` boolean flag, set manually in the DB (never via API).
- **Rights:** owner-equivalent within the *chosen* company.
- **Switching:** a persistent company selector; the support user can switch at any time.
- **Security:** 2FA mandatory; full audit log; visible "support mode" banner; account creation locked down.
- **Architecture:** Approach A — `active_company_id` JWT claim + request-time contextvar override + synthetic owner membership + ownership-check bypass, all bounded by RLS to the single active company.

### Out of scope (v1)
- User impersonation ("act as a specific user"). Support acts as a generic owner of the company.
- An admin UI to browse the support audit log (the rows are persisted; a viewer can come later).
- Multiple simultaneous active companies (exactly one at a time).

## Core principle

At any moment a support session has **exactly one active company**. The RLS GUC is set to
that company, so the support user sees and writes **only** that company's data. Ownership
checks are bypassed for support **within** the active company (safe — RLS already restricts
the row set to that company). Switching company is explicit and audited.

---

## 1. Data model

- **`User.is_support`** — `Column(Boolean, default=False, nullable=False)`. Added via the
  existing `ensure_columns` startup mechanism (ADD COLUMN IF NOT EXISTS) and SQLAlchemy model.
  Set to `true` for `contact@taic.co` by a one-off SQL `UPDATE` (documented, manual).
- **`SupportAuditLog`** — new table:
  - `id` (PK), `support_user_id` (int, index), `target_company_id` (int, nullable),
    `method` (str), `path` (str, len 300), `created_at` (DateTime, default utcnow, index).
  - NOT in `TENANT_TABLES` (it's a platform-level audit table, no `company_id` tenant semantics).
  - Created via `ensure_columns`-style raw `CREATE TABLE IF NOT EXISTS` + `Base.metadata.create_all`.
- **JWT claim `active_company_id`** — optional int, present only in support sessions; set by the switch endpoint.

## 2. Contextvars & resolution (the core)

In `database.py`, alongside the existing `_current_company_id` GUC contextvar, add:
- `_active_company_id: ContextVar[Optional[int]]` + `set_active_company_id()` / read helper.
- `_support_session: ContextVar[bool]` (default False) + `set_support_session()` / `is_support_session()`.

`tenant_isolation_middleware` (main.py), after decoding the JWT and loading the user, computes
the **effective company**:
- normal user → `user.company_id`.
- `user.is_support` AND token `active_company_id` set AND that company exists → `active_company_id`.
- `user.is_support` AND no selection → `None`.
Then sets: `set_current_company_id(effective)` (RLS GUC), `set_active_company_id(effective)`,
and `set_support_session(bool(user.is_support and effective is not None))`.

`helpers/tenant._get_caller_company_id(user_id, db)` returns the active contextvar value when set,
falling back to `user.company_id` (for non-request contexts such as background jobs). For normal
users the active value equals their own company, so behavior is unchanged.

> Revocation: the middleware re-checks `user.is_support` on every request, so flipping the flag
> to False immediately makes the `active_company_id` claim inert.

## 3. Permissions & ownership override

- `permissions.get_user_membership(user_id, db)`: if `is_support_session()` is true, return a
  **synthetic** `CompanyMembership(user_id=user_id, company_id=<active>, role="owner")` (not persisted).
- `permissions.require_role(...)`: with a synthetic owner membership it passes for any `min_role`.
  If a support user has **no** active company, `require_role` raises 403 "Select a company first".
- **`helpers.is_support_session()`** is consulted by the ownership-gated checks to grant access:
  `helpers/agent_helpers._user_can_access_agent`, `_user_can_edit_agent`;
  `helpers/conversation_helpers.verify_conversation_owner`;
  inline owner checks in `routers/agents.py` (`delete_agent`: `agent.user_id == uid`;
  `update_team_members` / team patch: `Team.user_id == uid`).
  Each becomes "allowed if the existing owner/share check passes **or** `is_support_session()`".
  This is bounded by RLS to the active company.

## 4. Endpoints (support-only; gated on `user.is_support`)

- **`GET /api/support/companies`** → `[{id, name}]` of all companies. 403 if not support.
- **`POST /api/support/active-company`** body `{company_id}` → validates the company exists (404 if not),
  re-issues the `token` cookie with the same expiry plus the `active_company_id` claim, writes a
  `SupportAuditLog` row ("switch"), returns `{active_company_id, company_name}`. 403 if not support.
- `/auth/verify` response is extended with `is_support` and `active_company` (`{id, name}` or null)
  so the frontend can render the banner + selector.

## 5. Auth / 2FA

- A support user must complete 2FA. The existing login flow already issues a `needs_2fa_setup`
  token when `totp_setup_completed_at` is null and a `pre_2fa` token when `totp_enabled`. We add an
  explicit guard: a support user is never issued a full access token unless `totp_enabled` is true.
- Signup (`routers/auth.py register`): reject registration of the reserved email `contact@taic.co`
  (and `is_support` is never settable via any request payload — the column simply defaults False).

## 6. Audit middleware

A middleware (after auth resolution) writes a `SupportAuditLog` row for every **state-changing**
request (`POST`/`PUT`/`PATCH`/`DELETE`) made during a support session: `support_user_id`,
`target_company_id` (the active company), `method`, `path`. Best-effort (never breaks the request).
`GET`s are not logged (volume). The switch endpoint logs its own entry.

## 7. Frontend

- **Banner**: a fixed amber/red bar "Mode support — entreprise : *Nom*" shown in `Layout` when
  `user.is_support` and an active company is set. If support but no company selected: "Mode support —
  aucune entreprise sélectionnée".
- **Company selector**: a dropdown (in the sidebar, support-only) populated from `/api/support/companies`;
  selecting one calls `/api/support/active-company` then reloads. Current selection highlighted.
- `useAuth` / `/auth/verify` expose `is_support` and `active_company`.

## 8. Security model

- `/api/support/*` and the `active_company_id` claim are honored **only** when `user.is_support` is true
  (re-checked server-side each request; claim is signed in the JWT).
- Exactly one active company at a time → RLS guarantees the support user can never see two companies'
  data simultaneously.
- 2FA mandatory; account creation cannot grant support; reserved email blocked at signup.
- Every switch and every state-changing action is audited.
- Ownership bypass is strictly bounded by the RLS active-company filter.

## 9. Testing (PG-backed where needed)

- **Regression**: a normal user's company resolution, RLS, and role checks are unchanged.
- Support with no active company: data endpoints return empty (RLS), `require_role` → 403.
- Support switches to company A: sees A's agents/docs/conversations; `require_role(owner)` passes;
  can edit/delete A's agents (ownership bypass); `/api/support/active-company` to B → sees B only, never A+B.
- Non-support user: `GET /api/support/companies` → 403; a forged token with `active_company_id` is
  ignored because `user.is_support` is false.
- Switching writes a `SupportAuditLog` row; a state-changing action writes one.
- `is_support` defaults False on new users; signup with `contact@taic.co` rejected.

## 10. Edge cases

- Support logged in, no company chosen → frontend shows the selector; protected data is empty; `require_role` → 403 "select a company".
- `active_company_id` points to a deleted company → switch validation 404; middleware treats a stale claim as no selection.
- `is_support` flipped to False mid-session → next request ignores the claim (acts as a normal — likely org-less — user).

## File touch-list (for the plan)
- `backend/database.py` (User.is_support, SupportAuditLog, contextvars + helpers, ensure_columns/table)
- `backend/main.py` (middleware resolution + audit middleware)
- `backend/helpers/tenant.py` (`_get_caller_company_id` honors active contextvar)
- `backend/permissions.py` (synthetic owner membership)
- `backend/helpers/agent_helpers.py`, `backend/helpers/conversation_helpers.py`, `backend/routers/agents.py` (ownership bypass)
- `backend/routers/support.py` (NEW: companies + active-company endpoints), registered in `main.py`
- `backend/routers/auth.py` (2FA-mandatory guard for support, reserved-email signup block, `/auth/verify` fields)
- `backend/auth.py` (helper to mint token with `active_company_id` claim)
- `frontend/components/Layout.js` + `Sidebar.js` (banner + selector), `hooks/useAuth.js` (expose fields)
- Tests: `backend/tests/test_support_account.py` (+ regression touches)
