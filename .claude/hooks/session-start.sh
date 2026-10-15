#!/bin/bash
# SessionStart hook for Claude Code on the web.
# Installs the build dependencies the CI workflows need (leptonica, libarchive,
# curl, pango, icu, autotools, ninja, ...) so cmake/autotools builds, unit tests and
# the Python subproject work inside remote sessions. Local sessions are untouched.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"

# setup-ai-tools.sh checks every required package itself and skips apt when
# all of them are already present (container state is cached between sessions).
bash setup-ai-tools.sh --build-deps

# The AI CLIs installed by setup-ai-tools.sh live here (hermes, openclaw, cursor-agent).
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "${CLAUDE_ENV_FILE:-/dev/null}"
