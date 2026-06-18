# Launch smoke-test checklist

Run end-to-end on **dev** first, then on **prod** with a throwaway test account,
immediately before onboarding client #1. This is the last manual gate before the
`dev`→`main` release. Tick each; if any fails, fix before launch (and keep the
rollback playbook handy: `docs/ops/rollback-playbook.md`).

## Auth & account
- [ ] Sign up a new account → receive verification email → verify email.
- [ ] Log in with the verified account.
- [ ] Set up 2FA → **the response shows 10 backup codes** (copy them). 2FA marked enabled.
- [ ] Log out, log in again → prompted for TOTP → enter code from authenticator → success.
- [ ] Log out, log in → on the TOTP prompt enter ONE of the backup codes → success.
- [ ] Reuse the SAME backup code again → rejected (single-use consumed).
- [ ] 5 wrong passwords in a row on one account → 6th attempt returns 429 (account lockout), even with the correct password; wait/clear → works again.

## Agents & RAG
- [ ] Create an agent (name + contexte). Very long name/contexte is accepted but truncated (not rejected, not stored unbounded).
- [ ] Upload a document of each type: PDF, TXT, DOCX → processed, appears in the agent's documents.
- [ ] Upload a non-allowed type / a fake `.pdf` (wrong magic bytes) → rejected with a clear error.
- [ ] Ask a question that should use the uploaded doc → answer cites/uses the content.
- [ ] Conversation history loads (most recent messages) on reopening the chat.

## Organization / company-RAG
- [ ] As an org admin, create a folder; upload a company doc into it.
- [ ] As a member, list company docs (visible); ask a question using company docs.
- [ ] Share an agent with another member of the SAME org → they can access it.
- [ ] Confirm a user from a DIFFERENT org cannot access these (no cross-tenant leak) — e.g. a foreign agent/doc id returns 404.

## Cost cap (WS2)
- [ ] (Optional, dev) Set a tiny `companies.llm_monthly_cap_usd` for the test org and seed/append usage over it → `/ask` returns 429 "monthly AI usage limit"; no LLM call made.

## Missions / recaps (if the client uses them)
- [ ] Create a mission; create/list a recap schedule; generate a recap.

## Ops
- [ ] Backend `/health` returns ok; startup logs show `migration_lock: acquired`,
      `ensure_rls_policies completed`, and (prod) `ENCRYPTION_KEY validation passed`.
- [ ] Note the current prod revision name BEFORE the release (rollback target).
- [ ] After prod deploy, re-run the RLS verification query (the 17 TENANT_TABLES
      are `enabled+forced`, 2 policies) on the prod DB.

## Owner pre-launch actions (not code)
- [ ] Revoke/rotate the leaked GitHub PAT.
- [ ] Enable branch protection on `main`/`dev` (require the 3 CI checks) — `docs/ops/ci-gating.md`.
- [ ] Gate Cloud Build on green CI (or merge to `main` only when `dev` CI is green).
- [ ] Set each real client's `llm_monthly_cap_usd` per contract (default 300 USD).
