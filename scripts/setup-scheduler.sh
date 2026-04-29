#!/usr/bin/env bash
# Setup Cloud Scheduler for daily monitoring routines.
# Run once per environment. Requires gcloud CLI authenticated.

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-applydi}"
REGION="europe-west1"
SERVICE_ACCOUNT="taic-drive-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Dev environment
DEV_BACKEND_URL="https://dev-taic-backend-817946451913.${REGION}.run.app"
SCHEDULER_SECRET=$(gcloud secrets versions access latest --secret=ROUTINE_SCHEDULER_SECRET --project="${PROJECT_ID}" 2>/dev/null || echo "")

echo "Creating Cloud Scheduler job for dev..."
gcloud scheduler jobs create http taic-daily-routine-dev \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --schedule="0 9 * * *" \
  --time-zone="Europe/Paris" \
  --uri="${DEV_BACKEND_URL}/api/admin/routine/run-all" \
  --http-method=POST \
  --headers="X-Scheduler-Secret=${SCHEDULER_SECRET}" \
  --oidc-service-account-email="${SERVICE_ACCOUNT}" \
  --oidc-token-audience="${DEV_BACKEND_URL}" \
  --description="Daily monitoring routine (dev)" \
  --attempt-deadline=300s \
  || echo "Job already exists. Use 'gcloud scheduler jobs update http ...' to modify."

# Production environment
PROD_BACKEND_URL="https://applydi-backend-817946451913.${REGION}.run.app"

echo "Creating Cloud Scheduler job for production..."
gcloud scheduler jobs create http taic-daily-routine-prod \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --schedule="0 9 * * *" \
  --time-zone="Europe/Paris" \
  --uri="${PROD_BACKEND_URL}/api/admin/routine/run-all" \
  --http-method=POST \
  --headers="X-Scheduler-Secret=${SCHEDULER_SECRET}" \
  --oidc-service-account-email="${SERVICE_ACCOUNT}" \
  --oidc-token-audience="${PROD_BACKEND_URL}" \
  --description="Daily monitoring routine (prod)" \
  --attempt-deadline=300s \
  || echo "Job already exists. Use 'gcloud scheduler jobs update http ...' to modify."

echo "Done. Verify with: gcloud scheduler jobs list --project=${PROJECT_ID} --location=${REGION}"
