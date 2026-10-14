#!/usr/bin/env bash
# Deploys: service account, secret, Cloud Run function, scheduler job,
# BigQuery dataset, and the GCS -> BigQuery Data Transfer.
# Fill in the variables, read each step, then run. Idempotent where gcloud allows.
set -euo pipefail

PROJECT=your-project-id
REGION=us-east4
BUCKET=${PROJECT}-admissions-landing
SA=sftp-ingest
SFTP_HOST=sftp.example.com
SFTP_USER=exports
SFTP_DIR=/outbound
SFTP_HOST_KEY="ssh-ed25519 AAAA...replace-with-server-host-key"

gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudfunctions.googleapis.com cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com bigquerydatatransfer.googleapis.com

# --- landing bucket: uniform access, no public access, 400-day lifecycle on raw files
gcloud storage buckets create "gs://$BUCKET" --location="$REGION" \
  --uniform-bucket-level-access --public-access-prevention || true
cat > /tmp/lifecycle.json << 'JSON'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 400}}]}
JSON
gcloud storage buckets update "gs://$BUCKET" --lifecycle-file=/tmp/lifecycle.json

# --- least-privilege service account: write objects to one bucket, read one secret
gcloud iam service-accounts create "$SA" --display-name="SFTP ingest" || true
SA_EMAIL="$SA@$PROJECT.iam.gserviceaccount.com"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/storage.objectCreator
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/storage.objectViewer   # list + size for idempotency

# --- SFTP private key in Secret Manager (create the key file yourself; never commit it)
gcloud secrets create sftp-key --replication-policy=automatic || true
# gcloud secrets versions add sftp-key --data-file=./sftp_ed25519
gcloud secrets add-iam-policy-binding sftp-key \
  --member="serviceAccount:$SA_EMAIL" --role=roles/secretmanager.secretAccessor

# --- function (private: no unauthenticated invocations)
cat > /tmp/sftp-ingest.env.yaml << YAML
GCS_BUCKET: "$BUCKET"
SFTP_HOST: "$SFTP_HOST"
SFTP_USER: "$SFTP_USER"
SFTP_DIR: "$SFTP_DIR"
SFTP_KEY_SECRET: "projects/$PROJECT/secrets/sftp-key/versions/latest"
SFTP_HOST_KEY: "$SFTP_HOST_KEY"
YAML
gcloud functions deploy sftp-ingest --gen2 --runtime=python312 --region="$REGION" \
  --source=function --entry-point=ingest --trigger-http --no-allow-unauthenticated \
  --service-account="$SA_EMAIL" --memory=512Mi --timeout=540s \
  --env-vars-file=/tmp/sftp-ingest.env.yaml

# --- scheduler calls the function with an OIDC token every morning
gcloud iam service-accounts create scheduler-invoker || true
INVOKER="scheduler-invoker@$PROJECT.iam.gserviceaccount.com"
gcloud functions add-invoker-policy-binding sftp-ingest --region="$REGION" --member="serviceAccount:$INVOKER"
URL=$(gcloud functions describe sftp-ingest --region="$REGION" --format='value(serviceConfig.uri)')
gcloud scheduler jobs create http sftp-ingest-daily --location="$REGION" \
  --schedule="30 6 * * *" --time-zone="America/New_York" --uri="$URL" --http-method=POST \
  --oidc-service-account-email="$INVOKER" || true

# --- BigQuery: raw table + scheduled GCS transfer (runs a few hours after the ingest).
# The GCS transfer only picks up objects new or changed since its last run, so
# APPEND doesn't reload history; applicant_current dedupes to the latest record.
bq --location=US mk -d "$PROJECT:raw_admissions" || true
bq --location=US mk -d "$PROJECT:admissions" || true
bq mk -t "$PROJECT:raw_admissions.applicant_events" infra/applicant_events_schema.json || true
bq mk --transfer_config --data_source=google_cloud_storage \
  --display_name="admissions-gcs-load" --target_dataset=raw_admissions \
  --schedule="every day 11:00" \
  --params="{
    \"data_path_template\": \"gs://$BUCKET/raw/applicants/*\",
    \"destination_table_name_template\": \"applicant_events\",
    \"file_format\": \"CSV\",
    \"skip_leading_rows\": \"1\",
    \"write_disposition\": \"APPEND\"
  }"

for f in sql/01_applicant_current.sql sql/02_funnel_by_program_channel.sql; do
  sed "s/{project}/$PROJECT/g" "$f" | bq query --use_legacy_sql=false
done
echo "done"
