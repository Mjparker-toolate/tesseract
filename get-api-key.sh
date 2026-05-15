#!/usr/bin/env bash
set -euo pipefail

# Anthropic API Key Retrieval
# Fetches metadata for a single API key from the Anthropic Admin API.
#
# Usage:
#   ANTHROPIC_ADMIN_API_KEY=sk-ant-admin... ./get-api-key.sh <API_KEY_ID>
#
# Environment variables:
#   ANTHROPIC_ADMIN_API_KEY  Admin API key used to authenticate the request (required)
#   ANTHROPIC_API_BASE       API base URL (default: https://api.anthropic.com)
#   ANTHROPIC_API_VERSION    API version header (default: 2023-06-01)
#
# Reference: https://docs.anthropic.com/en/api/admin-api/apikeys/get-api-key

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <API_KEY_ID>" >&2
    exit 64
fi

API_KEY_ID="$1"

if [[ -z "${ANTHROPIC_ADMIN_API_KEY:-}" ]]; then
    echo "Error: ANTHROPIC_ADMIN_API_KEY is not set." >&2
    echo "Export an admin key (sk-ant-admin...) before running this script." >&2
    exit 1
fi

API_BASE="${ANTHROPIC_API_BASE:-https://api.anthropic.com}"
API_VERSION="${ANTHROPIC_API_VERSION:-2023-06-01}"

curl --fail-with-body --silent --show-error \
    "${API_BASE}/v1/organizations/api_keys/${API_KEY_ID}" \
    -H "anthropic-version: ${API_VERSION}" \
    -H "X-Api-Key: ${ANTHROPIC_ADMIN_API_KEY}"
