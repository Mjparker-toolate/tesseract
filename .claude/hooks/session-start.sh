#!/bin/bash
# SessionStart hook for Claude Code on the web.
# Installs the build dependencies the CI workflows need (leptonica, libarchive,
# curl, pango, autotools, ninja, ...) so cmake/autotools builds, unit tests and
# the Python subproject work inside remote sessions. Local sessions are untouched.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"

# Skip apt when the packages are already present (container state is cached);
# the Python subproject install inside --build-deps is cheap and idempotent.
if pkg-config --exists lept libarchive libcurl 2>/dev/null && command -v ninja >/dev/null 2>&1; then
  echo "session-start: apt build dependencies already installed"
  SKIP_APT=1 bash setup-ai-tools.sh --build-deps
else
  bash setup-ai-tools.sh --build-deps
fi

# The AI CLIs installed by setup-ai-tools.sh live here (hermes, openclaw, cursor-agent).
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "${CLAUDE_ENV_FILE:-/dev/null}"
