#!/usr/bin/env bash
# One-time Google Cloud setup for RenovAI's model worker. Safe to run again.
#
# In the Google Cloud console, open Cloud Shell (the >_ button at the top) and run:
#
#   curl -fsSL https://raw.githubusercontent.com/aayushdhanotia12/RenovIA/main/deploy/gcp/setup.sh | bash -s -- PROJECT_ID
#
# It turns on the services the worker needs, creates the image registry, the worker's access
# token (kept in Secret Manager, never printed), a service account the worker runs as, and a
# deploy account GitHub Actions signs in as through Workload Identity Federation: no key
# files to leak or rotate, and only this repository's main branch can use it.
# At the end it prints four values for the repository's Actions variables; once they're set,
# every push to main that touches workers/ builds the image and deploys it to Cloud Run.
set -euo pipefail

PROJECT="${1:?usage: setup.sh PROJECT_ID [OWNER/REPO]}"
REPO="${2:-aayushdhanotia12/RenovIA}"
REGION="${REGION:-us-central1}"   # Cloud Run L4 regions: us-central1, us-east4, europe-west1/4, asia-southeast1, asia-south1

say() { printf '\n== %s\n' "$*"; }

gcloud config set project "$PROJECT" >/dev/null
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"

say "Turning on Cloud Run, Artifact Registry, Secret Manager and keyless sign-in from GitHub"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
  iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com

say "Image registry renovai in $REGION"
gcloud artifacts repositories describe renovai --location "$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create renovai --repository-format docker --location "$REGION" \
       --description "RenovAI model worker images"

say "Worker access token (Secret Manager: renovai-worker-token)"
gcloud secrets describe renovai-worker-token >/dev/null 2>&1 \
  || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' \
     | gcloud secrets create renovai-worker-token --replication-policy automatic --data-file -

say "Service accounts"
RUNTIME_SA="renovai-worker@$PROJECT.iam.gserviceaccount.com"
DEPLOY_SA="renovai-deployer@$PROJECT.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1 \
  || gcloud iam service-accounts create renovai-worker --display-name "RenovAI model worker (runs the service)"
gcloud iam service-accounts describe "$DEPLOY_SA" >/dev/null 2>&1 \
  || gcloud iam service-accounts create renovai-deployer --display-name "RenovAI deploys from GitHub Actions"

# The worker reads only its own token. The deployer pushes images, deploys the service, runs
# it as the worker account, and reads the token once to check the deploy answers.
gcloud secrets add-iam-policy-binding renovai-worker-token --quiet \
  --member "serviceAccount:$RUNTIME_SA" --role roles/secretmanager.secretAccessor >/dev/null
gcloud secrets add-iam-policy-binding renovai-worker-token --quiet \
  --member "serviceAccount:$DEPLOY_SA" --role roles/secretmanager.secretAccessor >/dev/null
gcloud artifacts repositories add-iam-policy-binding renovai --location "$REGION" --quiet \
  --member "serviceAccount:$DEPLOY_SA" --role roles/artifactregistry.writer >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" --quiet --condition None \
  --member "serviceAccount:$DEPLOY_SA" --role roles/run.admin >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" --quiet \
  --member "serviceAccount:$DEPLOY_SA" --role roles/iam.serviceAccountUser >/dev/null

say "Keyless sign-in for GitHub Actions ($REPO, main branch only)"
POOL="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github"
gcloud iam workload-identity-pools describe github --location global >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create github --location global --display-name "GitHub Actions"
gcloud iam workload-identity-pools providers describe renovai-repo --location global \
    --workload-identity-pool github >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools providers create-oidc renovai-repo --location global \
       --workload-identity-pool github --display-name "RenovAI repository" \
       --issuer-uri "https://token.actions.githubusercontent.com" \
       --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
       --attribute-condition "assertion.repository == '$REPO' && assertion.ref == 'refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --quiet \
  --member "principalSet://iam.googleapis.com/$POOL/attribute.repository/$REPO" \
  --role roles/iam.workloadIdentityUser >/dev/null

say "Done. Add these as repository variables (GitHub: Settings > Secrets and variables > Actions > Variables), or send them to Claude:"
cat <<EOF
GCP_PROJECT_ID=$PROJECT
GCP_REGION=$REGION
GCP_WIF_PROVIDER=$POOL/providers/renovai-repo
GCP_DEPLOY_SA=$DEPLOY_SA
EOF
echo
echo "None of these are secrets. The worker's token stays in Secret Manager; read it when the app server needs it:"
echo "  gcloud secrets versions access latest --secret renovai-worker-token"
