#!/usr/bin/env bash
# ==============================================================================
# Setup Workload Identity Federation (WIF) for GitHub Actions CI/CD
# Project: energy-carbon
# Repository: ducchuu/energy-carbon-forecast
# ==============================================================================

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-energy-carbon}"
REPO="ducchuu/energy-carbon-forecast"
POOL_NAME="github-actions-pool"
PROVIDER_NAME="github-actions-provider"
SA_NAME="github-actions-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== [1/6] Enabling Required GCP APIs ==="
gcloud services enable \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  --project="${PROJECT_ID}"

echo "=== [2/6] Creating Workload Identity Pool ==="
if ! gcloud iam workload-identity-pools describe "${POOL_NAME}" --location="global" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "${POOL_NAME}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --display-name="GitHub Actions Pool"
else
  echo "Pool ${POOL_NAME} already exists, skipping."
fi

echo "=== [3/6] Creating Workload Identity Provider ==="
if ! gcloud iam workload-identity-pools providers describe "${PROVIDER_NAME}" --workload-identity-pool="${POOL_NAME}" --location="global" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_NAME}" \
    --project="${PROJECT_ID}" \
    --location="global" \
    --workload-identity-pool="${POOL_NAME}" \
    --display-name="GitHub Actions Provider" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository == '${REPO}'"
else
  echo "Provider ${PROVIDER_NAME} already exists, skipping."
fi

echo "=== [4/6] Creating CI/CD Service Account ==="
if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --project="${PROJECT_ID}" \
    --display-name="GitHub Actions CI/CD Service Account"
else
  echo "Service account ${SA_EMAIL} already exists, skipping."
fi

echo "=== [5/6] Granting Permissions to CI/CD Service Account ==="
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.admin" \
  --condition=None >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/artifactregistry.writer" \
  --condition=None >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.jobUser" \
  --condition=None >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.dataEditor" \
  --condition=None >/dev/null

gcloud iam service-accounts add-iam-policy-binding "energy-streamlit-ui-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser" \
  --condition=None >/dev/null

echo "=== [6/6] Binding GitHub Repository to Service Account via WIF ==="
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")

gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/attribute.repository/${REPO}" \
  --condition=None >/dev/null

WIF_PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/providers/${PROVIDER_NAME}"

echo ""
echo "=============================================================================="
echo " SUCCESS! Workload Identity Federation is configured for repository: ${REPO}"
echo "=============================================================================="
echo ""
echo "Add the following 4 secrets to your GitHub repository:"
echo "Go to: https://github.com/${REPO}/settings/secrets/actions"
echo ""
echo "  1. GCP_PROJECT_ID:"
echo "     ${PROJECT_ID}"
echo ""
echo "  2. WIF_PROVIDER:"
echo "     ${WIF_PROVIDER_RESOURCE}"
echo ""
echo "  3. WIF_SERVICE_ACCOUNT:"
echo "     ${SA_EMAIL}"
echo ""
echo "  4. UI_SERVICE_ACCOUNT:"
echo "     energy-streamlit-ui-sa@${PROJECT_ID}.iam.gserviceaccount.com"
echo ""
if command -v gh >/dev/null 2>&1; then
  echo "Tip: Run the following commands to set them automatically via GitHub CLI:"
  echo "  gh secret set GCP_PROJECT_ID --body \"${PROJECT_ID}\""
  echo "  gh secret set WIF_PROVIDER --body \"${WIF_PROVIDER_RESOURCE}\""
  echo "  gh secret set WIF_SERVICE_ACCOUNT --body \"${SA_EMAIL}\""
  echo "  gh secret set UI_SERVICE_ACCOUNT --body \"energy-streamlit-ui-sa@${PROJECT_ID}.iam.gserviceaccount.com\""
fi
echo "=============================================================================="

