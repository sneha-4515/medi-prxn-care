#!/usr/bin/env bash
# One-shot Cloud Run + Cloud SQL (Postgres) deploy for Medi-Prxn-care.
# Usage:  PROJECT_ID=my-project GEMINI_API_KEY=xxxx ADMIN_EMAIL=you@example.com ./deploy/deploy.sh
# Re-running is safe: existing resources are reused and a new revision is deployed.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID}"
: "${GEMINI_API_KEY:?Set GEMINI_API_KEY (Google AI Studio key)}"
: "${ADMIN_EMAIL:?Set ADMIN_EMAIL (first reception admin)}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-medi-prxn-care}"
SQL_INSTANCE="${SQL_INSTANCE:-mediprxn-db}"
DB_NAME="${DB_NAME:-mediprxn}"
DB_USER="${DB_USER:-mediprxn}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)}"

gcloud config set project "$PROJECT_ID" >/dev/null
echo "==> Enabling APIs"
gcloud services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "==> Cloud SQL (Postgres 15)"
if ! gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1; then
  gcloud sql instances create "$SQL_INSTANCE" --database-version=POSTGRES_15 --tier=db-f1-micro \
    --region="$REGION" --storage-size=10GB --availability-type=zonal
fi
gcloud sql databases describe "$DB_NAME" --instance="$SQL_INSTANCE" >/dev/null 2>&1 || gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE"
DB_PASS="$(openssl rand -hex 16)"
if gcloud sql users list --instance="$SQL_INSTANCE" --format='value(name)' | grep -qx "$DB_USER"; then
  gcloud sql users set-password "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASS"
else
  gcloud sql users create "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASS"
fi
CONN="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"
DB_URL="postgresql://${DB_USER}:${DB_PASS}@/${DB_NAME}?host=/cloudsql/${CONN}"

put_secret() {  # name value
  if gcloud secrets describe "$1" >/dev/null 2>&1; then printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=- >/dev/null
  else printf '%s' "$2" | gcloud secrets create "$1" --data-file=- >/dev/null; fi
  gcloud secrets add-iam-policy-binding "$1" --member="serviceAccount:${RUN_SA}" --role=roles/secretmanager.secretAccessor >/dev/null
}
echo "==> Secrets"
gcloud secrets describe mediprxn-secret-key >/dev/null 2>&1 || put_secret mediprxn-secret-key "$(openssl rand -hex 32)"   # keep stable across deploys so sessions survive
put_secret mediprxn-database-url "$DB_URL"
put_secret mediprxn-gemini-key "$GEMINI_API_KEY"
put_secret mediprxn-admin-password "$ADMIN_PASSWORD"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${RUN_SA}" --role=roles/cloudsql.client >/dev/null

echo "==> Building and deploying to Cloud Run"
gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --add-cloudsql-instances "$CONN" \
  --set-env-vars "ENV=production,ADMIN_EMAIL=${ADMIN_EMAIL},GEMINI_MODEL=${GEMINI_MODEL:-gemini-3.8-flash}" \
  --set-secrets "SECRET_KEY=mediprxn-secret-key:latest,DATABASE_URL=mediprxn-database-url:latest,GEMINI_API_KEY=mediprxn-gemini-key:latest,ADMIN_PASSWORD=mediprxn-admin-password:latest" \
  --min-instances 0 --max-instances 3 --memory 512Mi --cpu 1 --timeout 120

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo
echo "Deployed: $URL"
echo "Admin login: ${ADMIN_EMAIL}  (password stored in Secret Manager: mediprxn-admin-password)"
echo "Health check: ${URL}/healthz"
