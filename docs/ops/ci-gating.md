# Gate deploys behind green CI (runbook)

Today CI (`.github/workflows/ci.yml`: `lint-backend`, `lint-and-build-frontend`,
`test-backend`) runs on every push but does **not** block deploys — Cloud Build
triggers on push to `dev`/`main` independently. For the client launch we want a
red build to STOP a prod deploy. Two console/settings changes (the repo alone
can't enforce these):

## 1. Branch protection (gate merges into main/dev)

GitHub → Settings → Branches → Add rule for `main` (repeat for `dev`):
- ✅ Require a pull request before merging
- ✅ Require status checks to pass before merging → select `lint-backend`,
  `lint-and-build-frontend`, `test-backend`
- ✅ Require branches to be up to date before merging

`gh` equivalent:

```bash
gh api -X PUT repos/Taicai-1/TAIC/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[contexts][]=lint-backend' \
  -f 'required_status_checks[contexts][]=lint-and-build-frontend' \
  -f 'required_status_checks[contexts][]=test-backend' \
  -f 'enforce_admins=true' \
  -f 'required_pull_request_reviews[required_approving_review_count]=0' \
  -f 'restrictions=null'
```

## 2. Gate the Cloud Build deploy on CI

Pick ONE:

**Option A (recommended): move deploy into GitHub Actions.** Add a `deploy` job
to the workflow that `needs: [lint-backend, lint-and-build-frontend, test-backend]`
and only runs on `main`/`dev`, authenticating to GCP via Workload Identity
Federation and running `gcloud builds submit` (or `gcloud run deploy`). One source
of truth: a red test → no deploy. Disable the standalone Cloud Build push trigger.

**Option B: keep Cloud Build, add a gate.** Use the Cloud Build GitHub App and
configure the trigger to require the GitHub check suite to be green, or have the
first Cloud Build step poll the GitHub Checks API for the commit and fail fast if
CI isn't green.

> This is an infra change (CI/CD wiring + GCP auth), to be scheduled before the
> launch release — not a code edit in this repo. Until then, the manual rule is:
> **do not merge to `main` unless the `dev` CI run for that commit is green.**
