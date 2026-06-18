# Cloud Billing budget + alert (GCP-level cost guardrail)

This is the **infrastructure-level** safety net, complementary to the per-tenant
LLM spend cap enforced in the app (`llm_usage.check_company_monthly_cap`). The
app cap stops a single tenant; this budget alerts on **total GCP spend** (Cloud
Run, Cloud SQL, egress, and — if billed through GCP — Vertex/Gemini).

> Run once per environment by an operator with billing admin rights. Not code.

## 1. Find the billing account id

```bash
gcloud billing accounts list
# -> ACCOUNT_ID like 0X0X0X-0X0X0X-0X0X0X
```

## 2. Create a monthly budget with alert thresholds

Set a monthly amount that is comfortably above expected spend (an alarm, not a
hard stop — GCP budgets notify; they do not block by default).

```bash
gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="TAIC monthly budget" \
  --budget-amount=500USD \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0 \
  --filter-projects="projects/PROJECT_ID"
```

This emails the billing account's Budget admins/users at 50%, 90%, and 100%.

## 3. (Recommended) Route alerts to a Pub/Sub topic for automation

To react programmatically (e.g. page on-call, or auto-throttle), attach a
Pub/Sub topic:

```bash
gcloud pubsub topics create billing-alerts
gcloud billing budgets update BUDGET_ID \
  --billing-account=BILLING_ACCOUNT_ID \
  --all-updates-rule-pubsub-topic="projects/PROJECT_ID/topics/billing-alerts"
```

## 4. Verify

```bash
gcloud billing budgets list --billing-account=BILLING_ACCOUNT_ID
```

## Notes / relationship to the app-level cap

- The app's per-company monthly cap (`LLM_MONTHLY_CAP_USD_DEFAULT`, default 300
  USD, per-company override via `companies.llm_monthly_cap_usd`) is the **hard**
  stop that returns HTTP 429 before making an LLM call.
- This GCP budget is a **soft** alert across all infra; keep its amount above the
  sum of expected per-tenant caps plus infra baseline.
- The `google-cloud-billing-budgets` dependency is already in
  `backend/requirements.txt` if you later want to manage budgets from code.
- **Known coverage gap (WS2 v1):** streaming LLM responses (`get_answer_stream`,
  OpenAI stream variants) are not yet token-instrumented, so their cost is not
  counted toward the per-company cap. Non-streaming `/ask` (the dominant path)
  is covered. Closing the streaming gap is a documented follow-up.
```
