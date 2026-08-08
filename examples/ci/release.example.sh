#!/usr/bin/env bash
set -euo pipefail

# Example release flow for a multi-contract repo.
# Review the generated manifest before creating PRs.

BASE_ROOT="${BASE_ROOT:-./contracts-main}"
CANDIDATE_ROOT="${CANDIDATE_ROOT:-./contracts-release}"
MANIFEST_PATH="${MANIFEST_PATH:-./artifacts/release_manifest.json}"
REPO_PATH="${REPO_PATH:-.}"

: "${ADO_ORGANIZATION:?Set ADO_ORGANIZATION}"
: "${ADO_PROJECT:?Set ADO_PROJECT}"
: "${ADO_REPOSITORY_ID:?Set ADO_REPOSITORY_ID}"
: "${ADO_PAT_TOKEN:?Set ADO_PAT_TOKEN}"

semapact release build-manifest \
  --base-root "${BASE_ROOT}" \
  --candidate-root "${CANDIDATE_ROOT}" \
  --output "${MANIFEST_PATH}"

echo "Review and edit ${MANIFEST_PATH} before continuing."

semapact release create-prs \
  --manifest "${MANIFEST_PATH}" \
  --repo-path "${REPO_PATH}" \
  --organization "${ADO_ORGANIZATION}" \
  --project "${ADO_PROJECT}" \
  --repository-id "${ADO_REPOSITORY_ID}" \
  --pat-token "${ADO_PAT_TOKEN}" \
  --push
