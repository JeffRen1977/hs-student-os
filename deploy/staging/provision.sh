#!/usr/bin/env bash
# Staging environment for High School Student OS (Step 30). Idempotent where gcloud allows.
#
#   PROJECT_ID=hs-student-os-staging REGION=us-central1 ./deploy/staging/provision.sh          # dry run: prints commands
#   PROJECT_ID=hs-student-os-staging REGION=us-central1 APPLY=1 ./deploy/staging/provision.sh  # executes them
#
# A dedicated project: never shared with other education projects (CLAUDE.md §1.1).
# Secrets are created empty; add versions by hand (gcloud secrets versions add ...).
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID (a dedicated staging project)}"
REGION="${REGION:-us-central1}"
APPLY="${APPLY:-0}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/hsos/server:${IMAGE_TAG:-$(git -C "$REPO_ROOT" rev-parse --short HEAD)}"

case "$PROJECT_ID" in
  demo-*) echo "refusing: demo-* projects are emulator-only" >&2; exit 2 ;;
esac

API_SA="hsos-api@${PROJECT_ID}.iam.gserviceaccount.com"
WORKER_SA="hsos-worker@${PROJECT_ID}.iam.gserviceaccount.com"
INVOKER_SA="hsos-tasks-invoker@${PROJECT_ID}.iam.gserviceaccount.com"  # Cloud Tasks + Scheduler OIDC identity

run() {
  echo "+ $(printf '%q ' "$@")"
  if [ "$APPLY" = "1" ]; then "$@"; fi
}

# 1. APIs ---------------------------------------------------------------------------------
run gcloud services enable --project "$PROJECT_ID" \
  run.googleapis.com firestore.googleapis.com cloudtasks.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com storage.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com logging.googleapis.com \
  monitoring.googleapis.com identitytoolkit.googleapis.com

# 2. Firestore (native mode), indexes, daily managed backups kept 14 days ---------------------
run gcloud firestore databases create --project "$PROJECT_ID" --location "$REGION" --type firestore-native
run gcloud firestore backups schedules create --project "$PROJECT_ID" --database '(default)' \
  --recurrence daily --retention 14d
# Indexes: firebase deploy --only firestore:indexes --project "$PROJECT_ID" (server/firestore.indexes.json)

# 3. Service accounts and IAM (API and worker are separate identities) -----------------------
for sa in hsos-api hsos-worker hsos-tasks-invoker; do
  run gcloud iam service-accounts create "$sa" --project "$PROJECT_ID" --display-name "$sa"
done
for sa in "$API_SA" "$WORKER_SA"; do
  run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$sa" --role roles/datastore.user
done
# The API enqueues Cloud Tasks that carry the invoker's OIDC token.
run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$API_SA" --role roles/cloudtasks.enqueuer
run gcloud iam service-accounts add-iam-policy-binding "$INVOKER_SA" --project "$PROJECT_ID" \
  --member "serviceAccount:$API_SA" --role roles/iam.serviceAccountUser
run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$WORKER_SA" --role roles/cloudtasks.enqueuer
run gcloud iam service-accounts add-iam-policy-binding "$INVOKER_SA" --project "$PROJECT_ID" \
  --member "serviceAccount:$WORKER_SA" --role roles/iam.serviceAccountUser

# 4. Secrets (values added by hand, never from this repo) -----------------------------------
run gcloud secrets create anthropic-api-key --project "$PROJECT_ID" --replication-policy automatic
run gcloud secrets add-iam-policy-binding anthropic-api-key --project "$PROJECT_ID" \
  --member "serviceAccount:$WORKER_SA" --role roles/secretmanager.secretAccessor

# 5. Storage: uploads (not used by the text-only pilot) and operator backups ----------------
run gcloud storage buckets create "gs://${PROJECT_ID}-uploads" --project "$PROJECT_ID" --location "$REGION" \
  --uniform-bucket-level-access --public-access-prevention
run gcloud storage buckets create "gs://${PROJECT_ID}-backups" --project "$PROJECT_ID" --location "$REGION" \
  --uniform-bucket-level-access --public-access-prevention
run gcloud storage buckets update "gs://${PROJECT_ID}-backups" --lifecycle-file "$REPO_ROOT/deploy/staging/backup-lifecycle.json"

# 6. Cloud Tasks queue: bounded retries with backoff; dispatch deadline set per task ---------
run gcloud tasks queues create runs --project "$PROJECT_ID" --location "$REGION" \
  --max-attempts 5 --min-backoff 5s --max-backoff 300s --max-dispatches-per-second 20 \
  --max-concurrent-dispatches 50

# 7. Image and Cloud Run services --------------------------------------------------------------
run gcloud artifacts repositories create hsos --project "$PROJECT_ID" --location "$REGION" --repository-format docker
run gcloud builds submit "$REPO_ROOT/server" --project "$PROJECT_ID" --tag "$IMAGE"

# Worker first: the API needs its URL. Not public: only the invoker identity may call it.
run gcloud run deploy hsos-worker --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --service-account "$WORKER_SA" --no-allow-unauthenticated --ingress internal-and-cloud-load-balancing \
  --timeout 600 --concurrency 10 --max-instances 5 --cpu 1 --memory 1Gi \
  --env-vars-file "$REPO_ROOT/deploy/staging/worker.env.yaml" \
  --set-env-vars "HSOS_GCP_PROJECT_ID=${PROJECT_ID},HSOS_WORKER_SERVICE_ACCOUNT=${INVOKER_SA}" \
  --set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest
run gcloud run services add-iam-policy-binding hsos-worker --project "$PROJECT_ID" --region "$REGION" \
  --member "serviceAccount:$INVOKER_SA" --role roles/run.invoker

if [ "$APPLY" = "1" ]; then
  WORKER_URL="$(gcloud run services describe hsos-worker --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')"
else
  WORKER_URL="https://hsos-worker-UNKNOWN.run.app"
fi

# API: public HTTPS (students authenticate with Firebase ID tokens). SSE streams close after
# HSOS_SSE_MAX_STREAM_SECONDS (300 s), well inside the 900 s request timeout; clients resume
# with Last-Event-ID.
run gcloud run deploy hsos-api --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --service-account "$API_SA" --allow-unauthenticated \
  --timeout 900 --concurrency 80 --max-instances 5 --cpu 1 --memory 512Mi \
  --env-vars-file "$REPO_ROOT/deploy/staging/api.env.yaml" \
  --set-env-vars "HSOS_GCP_PROJECT_ID=${PROJECT_ID},HSOS_WORKER_URL=${WORKER_URL},HSOS_WORKER_OIDC_AUDIENCE=${WORKER_URL},HSOS_WORKER_SERVICE_ACCOUNT=${INVOKER_SA},HSOS_CLOUD_TASKS_LOCATION=${REGION}"
run gcloud run services update hsos-worker --project "$PROJECT_ID" --region "$REGION" \
  --update-env-vars "HSOS_WORKER_URL=${WORKER_URL},HSOS_WORKER_OIDC_AUDIENCE=${WORKER_URL},HSOS_CLOUD_TASKS_LOCATION=${REGION}"

# 8. Cloud Scheduler: every job calls the worker with the invoker's OIDC token --------------
schedule() {  # name, cron, path
  run gcloud scheduler jobs create http "$1" --project "$PROJECT_ID" --location "$REGION" \
    --schedule "$2" --time-zone UTC --http-method POST --uri "${WORKER_URL}$3" \
    --oidc-service-account-email "$INVOKER_SA" --oidc-token-audience "$WORKER_URL" \
    --attempt-deadline 540s
}
schedule hsos-outbox-dispatch   "* * * * *"    /internal/outbox/dispatch
schedule hsos-run-recovery      "*/5 * * * *"  /internal/runs/recover
schedule hsos-planning-schedule "*/15 * * * *" /internal/planning/schedule
schedule hsos-reminders         "*/5 * * * *"  /internal/reminders/deliver
schedule hsos-ops-check         "*/5 * * * *"  /internal/ops/check
schedule hsos-event-retention   "30 3 * * *"   /internal/retention/events

# 9. Monitoring: log-based metrics and alert policies (deploy/monitoring/) ------------------
for m in "$REPO_ROOT"/deploy/monitoring/metric-*.yaml; do
  name="$(basename "$m" .yaml)"; name="${name#metric-}"
  run gcloud logging metrics create "$name" --project "$PROJECT_ID" --config-from-file "$m"
done
for p in "$REPO_ROOT"/deploy/monitoring/alert-*.json; do
  run gcloud alpha monitoring policies create --project "$PROJECT_ID" --policy-from-file "$p"
done

# 10. Budget: a finite monthly cap on the billing account (set BILLING_ACCOUNT to apply) ----
if [ -n "${BILLING_ACCOUNT:-}" ]; then
  run gcloud billing budgets create --billing-account "$BILLING_ACCOUNT" \
    --display-name "hsos-staging" --budget-amount "${BUDGET_USD:-200}USD" \
    --filter-projects "projects/${PROJECT_ID}" --threshold-rule percent=0.5 --threshold-rule percent=0.9
fi

echo "done (APPLY=$APPLY). Record which checks ran in doc/OPERATIONS.md §5."
