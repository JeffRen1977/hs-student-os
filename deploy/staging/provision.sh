#!/usr/bin/env bash
# Staging environment for High School Student OS (Step 30). Safe to re-run: resources that
# already exist are skipped, and alert policies and the budget are not duplicated.
#
#   PROJECT_ID=hs-student-os-staging REGION=us-central1 ./deploy/staging/provision.sh          # dry run: prints commands
#   PROJECT_ID=hs-student-os-staging REGION=us-central1 APPLY=1 ./deploy/staging/provision.sh  # executes them
#
# LLM_PROVIDER=anthropic (default) or openai selects the model provider and its key secret
# (anthropic-api-key or openai-api-key).
#
# A dedicated project: never shared with other education projects (CLAUDE.md §1.1).
# Secrets are created empty; add versions by hand (gcloud secrets versions add ...). The first
# APPLY run stops before the image build until the Anthropic key has a version; re-run then.
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID (a dedicated staging project)}"
REGION="${REGION:-us-central1}"
# Firestore location may be a multi-region (e.g. nam5); Cloud Run/Tasks/Scheduler use REGION.
FIRESTORE_LOCATION="${FIRESTORE_LOCATION:-$REGION}"
APPLY="${APPLY:-0}"
LLM_PROVIDER="${LLM_PROVIDER:-anthropic}"
case "$LLM_PROVIDER" in
  anthropic) KEY_ENV=ANTHROPIC_API_KEY ;;
  openai) KEY_ENV=OPENAI_API_KEY ;;
  *) echo "LLM_PROVIDER must be anthropic or openai" >&2; exit 2 ;;
esac
KEY_SECRET="${LLM_PROVIDER}-api-key"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/hsos/server:${IMAGE_TAG:-$(git -C "$REPO_ROOT" rev-parse --short HEAD)}"

case "$PROJECT_ID" in
  demo-*) echo "refusing: demo-* projects are emulator-only" >&2; exit 2 ;;
esac

API_SA="hsos-api@${PROJECT_ID}.iam.gserviceaccount.com"
WORKER_SA="hsos-worker@${PROJECT_ID}.iam.gserviceaccount.com"
INVOKER_SA="hsos-tasks-invoker@${PROJECT_ID}.iam.gserviceaccount.com"  # Cloud Tasks + Scheduler OIDC identity

# gcloud run deploy takes one source of env vars (--env-vars-file and --set-env-vars are
# mutually exclusive): merge the checked-in file with values known only here.
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
merged_env() {  # checked-in env file, then KEY=VALUE pairs; prints the merged file's path
  local src="$1" out kv
  shift
  out="$TMP_DIR/$(basename "$src")"
  cp "$src" "$out"
  for kv in "$@"; do printf '%s: "%s"\n' "${kv%%=*}" "${kv#*=}" >>"$out"; done
  echo "$out"
}

run() {
  echo "+ $(printf '%q ' "$@")"
  if [ "$APPLY" = "1" ]; then "$@"; fi
}

# Like run, for create commands: a resource that already exists is skipped, not an error.
ensure() {
  echo "+ $(printf '%q ' "$@")"
  [ "$APPLY" = "1" ] || return 0
  local err
  if ! err="$("$@" 2>&1 >/dev/null)"; then
    if grep -qiE 'already exists|ALREADY_EXISTS|already own it' <<<"$err"; then
      echo "  (already exists, skipped)"
    else
      echo "$err" >&2
      return 1
    fi
  fi
}

# 1. APIs ---------------------------------------------------------------------------------
run gcloud services enable --project "$PROJECT_ID" \
  run.googleapis.com firestore.googleapis.com cloudtasks.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com storage.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com logging.googleapis.com \
  monitoring.googleapis.com identitytoolkit.googleapis.com billingbudgets.googleapis.com

# Budget: alert thresholds on the billing account (set BILLING_ACCOUNT to apply). Created
# first so it is in place before anything billable runs. A budget notifies; it does not stop
# spending. Not duplicated on re-run.
if [ -n "${BILLING_ACCOUNT:-}" ]; then
  if [ "$APPLY" = "1" ] && [ -n "$(gcloud billing budgets list --billing-account "$BILLING_ACCOUNT" \
      --filter 'displayName=hsos-staging' --format 'value(name)')" ]; then
    echo "  (budget hsos-staging exists, skipped)"
  else
    run gcloud billing budgets create --billing-account "$BILLING_ACCOUNT" \
      --display-name "hsos-staging" --budget-amount "${BUDGET_USD:-20}USD" \
      --filter-projects "projects/${PROJECT_ID}" --threshold-rule percent=0.5 --threshold-rule percent=0.9 --threshold-rule percent=1.0
  fi
fi

# 2. Firestore (native mode), indexes, daily managed backups kept 14 days ---------------------
ensure gcloud firestore databases create --project "$PROJECT_ID" --location "$FIRESTORE_LOCATION" --type firestore-native
ensure gcloud firestore backups schedules create --project "$PROJECT_ID" --database '(default)' \
  --recurrence daily --retention 14d
# Indexes: firebase deploy --only firestore:indexes --project "$PROJECT_ID" (server/firestore.indexes.json)

# 3. Service accounts and IAM (API and worker are separate identities) -----------------------
for sa in hsos-api hsos-worker hsos-tasks-invoker; do
  ensure gcloud iam service-accounts create "$sa" --project "$PROJECT_ID" --display-name "$sa"
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
ensure gcloud secrets create "$KEY_SECRET" --project "$PROJECT_ID" --replication-policy automatic
run gcloud secrets add-iam-policy-binding "$KEY_SECRET" --project "$PROJECT_ID" \
  --member "serviceAccount:$WORKER_SA" --role roles/secretmanager.secretAccessor

# 5. Storage: uploads (not used by the text-only pilot) and operator backups ----------------
ensure gcloud storage buckets create "gs://${PROJECT_ID}-uploads" --project "$PROJECT_ID" --location "$REGION" \
  --uniform-bucket-level-access --public-access-prevention
ensure gcloud storage buckets create "gs://${PROJECT_ID}-backups" --project "$PROJECT_ID" --location "$REGION" \
  --uniform-bucket-level-access --public-access-prevention
run gcloud storage buckets update "gs://${PROJECT_ID}-backups" --lifecycle-file "$REPO_ROOT/deploy/staging/backup-lifecycle.json"

# 6. Cloud Tasks queue: bounded retries with backoff; dispatch deadline set per task ---------
ensure gcloud tasks queues create runs --project "$PROJECT_ID" --location "$REGION" \
  --max-attempts 5 --min-backoff 5s --max-backoff 300s --max-dispatches-per-second 20 \
  --max-concurrent-dispatches 50

# 7. Image and Cloud Run services --------------------------------------------------------------
# Cloud Run refuses a secret with no version, so stop here (before the paid build) until the
# model provider's key is added by hand. It never passes through this repo.
if [ "$APPLY" = "1" ] && [ -z "$(gcloud secrets versions list "$KEY_SECRET" --project "$PROJECT_ID" \
    --filter 'state=ENABLED' --limit 1 --format 'value(name)')" ]; then
  cat >&2 <<EOF
stopping before the image build: secret $KEY_SECRET has no enabled version. Add it, then re-run:
  printf '%s' "\$$KEY_ENV" | gcloud secrets versions add $KEY_SECRET --data-file=- --project $PROJECT_ID
EOF
  exit 3
fi
ensure gcloud artifacts repositories create hsos --project "$PROJECT_ID" --location "$REGION" --repository-format docker
run gcloud builds submit "$REPO_ROOT/server" --project "$PROJECT_ID" --tag "$IMAGE"

# The worker's own URL is its OIDC audience, and staging refuses to start without it, so it
# must be known before the first deploy. Cloud Run's deterministic URL form is
# https://SERVICE-PROJECT_NUMBER.REGION.run.app (it serves alongside the hashed status.url).
if [ "$APPLY" = "1" ]; then
  PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
else
  PROJECT_NUMBER="PROJECT_NUMBER"
fi
WORKER_URL="https://hsos-worker-${PROJECT_NUMBER}.${REGION}.run.app"

# Worker first: the API needs its URL. Not public: only the invoker identity may call it.
run gcloud run deploy hsos-worker --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --service-account "$WORKER_SA" --no-allow-unauthenticated --ingress internal-and-cloud-load-balancing \
  --timeout 600 --concurrency 10 --max-instances 5 --cpu 1 --memory 1Gi \
  --env-vars-file "$(merged_env "$REPO_ROOT/deploy/staging/worker.env.yaml" \
    "HSOS_GCP_PROJECT_ID=${PROJECT_ID}" "HSOS_WORKER_SERVICE_ACCOUNT=${INVOKER_SA}" \
    "HSOS_WORKER_URL=${WORKER_URL}" "HSOS_WORKER_OIDC_AUDIENCE=${WORKER_URL}" \
    "HSOS_CLOUD_TASKS_LOCATION=${REGION}" "HSOS_LLM_PROVIDER=${LLM_PROVIDER}")" \
  --set-secrets "${KEY_ENV}=${KEY_SECRET}:latest"
run gcloud run services add-iam-policy-binding hsos-worker --project "$PROJECT_ID" --region "$REGION" \
  --member "serviceAccount:$INVOKER_SA" --role roles/run.invoker

# API: public HTTPS (students authenticate with Firebase ID tokens). SSE streams close after
# HSOS_SSE_MAX_STREAM_SECONDS (300 s), well inside the 900 s request timeout; clients resume
# with Last-Event-ID.
run gcloud run deploy hsos-api --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --service-account "$API_SA" --allow-unauthenticated \
  --timeout 900 --concurrency 80 --max-instances 5 --cpu 1 --memory 512Mi \
  --env-vars-file "$(merged_env "$REPO_ROOT/deploy/staging/api.env.yaml" \
    "HSOS_GCP_PROJECT_ID=${PROJECT_ID}" "HSOS_WORKER_URL=${WORKER_URL}" \
    "HSOS_WORKER_OIDC_AUDIENCE=${WORKER_URL}" "HSOS_WORKER_SERVICE_ACCOUNT=${INVOKER_SA}" \
    "HSOS_CLOUD_TASKS_LOCATION=${REGION}" "HSOS_LLM_PROVIDER=${LLM_PROVIDER}")"

# 8. Cloud Scheduler: every job calls the worker with the invoker's OIDC token --------------
schedule() {  # name, cron, path
  ensure gcloud scheduler jobs create http "$1" --project "$PROJECT_ID" --location "$REGION" \
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
# Alert policies go through the Monitoring REST API: `gcloud monitoring policies` exists only
# in the alpha/beta components, which a default gcloud install lacks.
monitoring_api() {  # method, path under projects/PROJECT_ID, extra curl args
  local method="$1" path="$2"
  shift 2
  curl -fsS -X "$method" "https://monitoring.googleapis.com/v3/projects/${PROJECT_ID}/${path}" \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "Content-Type: application/json" "$@"
}
for m in "$REPO_ROOT"/deploy/monitoring/metric-*.yaml; do
  name="$(basename "$m" .yaml)"; name="${name#metric-}"
  ensure gcloud logging metrics create "$name" --project "$PROJECT_ID" --config-from-file "$m"
done
for p in "$REPO_ROOT"/deploy/monitoring/alert-*.json; do
  display="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["displayName"])' "$p")"
  if [ "$APPLY" = "1" ] && monitoring_api GET "alertPolicies" | python3 -c '
import json, sys
names = [p.get("displayName") for p in json.load(sys.stdin).get("alertPolicies", [])]
sys.exit(0 if sys.argv[1] in names else 1)' "$display"; then
    echo "  (alert policy exists, skipped: $display)"
    continue
  fi
  echo "+ POST monitoring.googleapis.com/v3/projects/${PROJECT_ID}/alertPolicies < $(basename "$p")"
  if [ "$APPLY" = "1" ]; then monitoring_api POST "alertPolicies" --data-binary "@$p" >/dev/null; fi
done

echo "done (APPLY=$APPLY). Record which checks ran in doc/OPERATIONS.md §5."
