#!/usr/bin/env bash
set -euo pipefail

# AI tooling + build dependency setup for this repository.
#
# Installs everything needed to run the CI workflows locally (autotools.yml,
# cmake.yml, unittest.yml, python-package.yml) and the AI agent CLIs used with
# this repo: Claude Code, Codex, OpenClaw, Hermes Agent, GitHub Copilot CLI,
# Cursor CLI and Ollama.
#
# Usage:
#   bash setup-ai-tools.sh                # build deps + all AI CLIs
#   bash setup-ai-tools.sh --build-deps   # only apt/brew build dependencies
#   bash setup-ai-tools.sh --ai-tools     # only the AI CLIs
#
# Environment:
#   SKIP_APT=1        do not touch apt/brew
#   NODE24_PREFIX     where to put a private Node >=24 runtime for OpenClaw
#                     (default: /opt/node24 if writable, else ~/.local/node24)
#
# Every step is idempotent: already-installed tools are reported and skipped.
# Vendor `curl | sh` installers are used when their hosts are reachable; when
# they are not (sandboxed CI, restricted egress) the script falls back to the
# npm / PyPI package of the same tool, which is what the vendors publish.

MODE="${1:-all}"
case "$MODE" in
  all|--all) DO_BUILD=1; DO_AI=1 ;;
  --build-deps) DO_BUILD=1; DO_AI=0 ;;
  --ai-tools) DO_BUILD=0; DO_AI=1 ;;
  -h|--help) sed -n '3,25p' "$0"; exit 0 ;;
  *) echo "unknown option: $MODE" >&2; exit 2 ;;
esac

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

log()  { printf '\n==> %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
reachable() { curl -fsSL -o /dev/null --max-time 15 "$1" 2>/dev/null; }
ver()  { "$@" 2>/dev/null | head -1 || true; }

# ---------------------------------------------------------------------------
# 1. Build dependencies (mirrors .github/workflows/*.yml)
# ---------------------------------------------------------------------------
install_build_deps() {
  log "Build dependencies"
  if [ "${SKIP_APT:-0}" = "1" ]; then
    echo "SKIP_APT=1, skipping system packages"
  elif have apt-get; then
    export DEBIAN_FRONTEND=noninteractive
    $SUDO apt-get update -qq
    # autotools.yml / cmake.yml / unittest.yml / installer-for-windows.yml
    $SUDO apt-get install -y -qq \
      build-essential g++ clang cmake ninja-build pkg-config \
      autoconf automake libtool \
      libleptonica-dev libtiff-dev libarchive-dev libcurl4-openssl-dev \
      libpango1.0-dev libicu-dev cabextract curl jq git
  elif have brew; then
    # autotools-macos.yml / unittest-macos.yml
    brew install autoconf automake libtool cabextract leptonica libarchive \
      pango icu4c curl cmake ninja pkg-config jq
  elif have pacman; then
    # msys2.yml
    pacman --noconfirm -S --needed mingw-w64-x86_64-gcc mingw-w64-x86_64-cmake \
      mingw-w64-x86_64-ninja mingw-w64-x86_64-pkg-config mingw-w64-x86_64-leptonica \
      mingw-w64-x86_64-libarchive mingw-w64-x86_64-curl mingw-w64-x86_64-icu \
      mingw-w64-x86_64-pango mingw-w64-x86_64-cairo mingw-w64-x86_64-zlib
  else
    echo "No supported package manager found (apt-get, brew, pacman)." >&2
  fi

  # python-package.yml: contrib/spotify-recommender
  if have python3 && [ -f contrib/spotify-recommender/pyproject.toml ]; then
    log "Python subproject (contrib/spotify-recommender)"
    # Distro-managed Pythons (PEP 668) refuse plain installs; retry with the override.
    python3 -m pip install -q -e "contrib/spotify-recommender[dev]" flake8 \
      || python3 -m pip install -q --break-system-packages -e "contrib/spotify-recommender[dev]" flake8
  fi

  log "Build dependency versions"
  for m in lept libtiff-4 libarchive libcurl; do
    printf '  %-12s %s\n' "$m" "$(pkg-config --modversion "$m" 2>/dev/null || echo MISSING)"
  done
}

# ---------------------------------------------------------------------------
# 2. AI agent CLIs
# ---------------------------------------------------------------------------
need_node() {
  if ! have node || ! have npm; then
    log "Node.js + npm are required for Claude Code, Codex, Copilot, OpenClaw"
    if have apt-get; then $SUDO apt-get install -y -qq nodejs npm; fi
  fi
}

node_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }

# OpenClaw needs Node >=24.16. Provide a private runtime from the npm registry
# (the `node` package ships official binaries) without replacing system node.
ensure_node24() {
  if [ "$(node_major)" -ge 24 ]; then echo "node $(node --version) satisfies OpenClaw"; return 0; fi
  local prefix="${NODE24_PREFIX:-}"
  if [ -z "$prefix" ]; then
    if [ -w /opt ] || [ -n "$SUDO" ]; then prefix=/opt/node24; else prefix="$HOME/.local/node24"; fi
  fi
  if [ ! -x "$prefix/node_modules/node/bin/node" ]; then
    log "Installing private Node 24 runtime into $prefix (npm package 'node@24')"
    $SUDO mkdir -p "$prefix"
    $SUDO chown "$(id -u)" "$prefix" 2>/dev/null || true
    (cd "$prefix" && npm install --no-audit --no-fund node@24)
  fi
  NODE24_BIN="$prefix/node_modules/node/bin"
  echo "node24: $("$NODE24_BIN/node" --version)"
}

install_claude() {
  log "Claude Code"
  if have claude; then echo "already installed: $(ver claude --version)"; return; fi
  npm install -g @anthropic-ai/claude-code
  echo "installed: $(ver claude --version)"
}

install_codex() {
  log "OpenAI Codex CLI"
  if have codex; then echo "already installed: $(ver codex --version)"; return; fi
  if reachable https://chatgpt.com/codex/install.sh; then
    curl -fsSL https://chatgpt.com/codex/install.sh | sh
  else
    npm install -g @openai/codex
  fi
  echo "installed: $(ver codex --version)"
}

install_copilot() {
  log "GitHub Copilot CLI"
  if have copilot; then echo "already installed: $(ver copilot --version)"; return; fi
  npm install -g @github/copilot
  echo "installed: $(ver copilot --version)"
}

install_openclaw() {
  log "OpenClaw"
  if have openclaw; then echo "already installed: $(ver openclaw --version)"; return; fi
  if reachable https://openclaw.ai/install.sh; then
    curl -fsSL https://openclaw.ai/install.sh | bash
  else
    ensure_node24
    if [ "$(node_major)" -ge 24 ]; then
      npm install -g openclaw@latest
    else
      # Install with the private Node 24 so its preinstall engine check passes,
      # then expose a launcher on PATH that always runs it under that runtime.
      local prefix="${NODE24_BIN%/node_modules/node/bin}/openclaw"
      PATH="$NODE24_BIN:$PATH" npm install -g --prefix "$prefix" openclaw@latest
      local launcher="$HOME/.local/bin/openclaw"
      mkdir -p "$(dirname "$launcher")"
      printf '#!/usr/bin/env bash\nexport PATH="%s:$PATH"\nexec "%s/bin/openclaw" "$@"\n' \
        "$NODE24_BIN" "$prefix" > "$launcher"
      chmod +x "$launcher"
      echo "launcher: $launcher (uses $NODE24_BIN/node)"
    fi
  fi
  echo "installed: $(ver openclaw --version || ver "$HOME/.local/bin/openclaw" --version)"
}

install_hermes() {
  log "Hermes Agent (Nous Research)"
  if have hermes; then echo "already installed: $(ver hermes --version)"; return; fi
  if reachable https://hermes-agent.nousresearch.com/install.sh; then
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
  else
    # PyPI package published by Nous Research; requires Python >=3.11,<3.14.
    if ! have uv; then python3 -m pip install -q uv; fi
    uv tool install hermes-agent --python 3.11 || uv tool install hermes-agent
  fi
  echo "installed: $(ver hermes --version || ver "$HOME/.local/bin/hermes" --version)"
}

install_cursor() {
  log "Cursor CLI (cursor-agent)"
  if have cursor-agent; then echo "already installed: $(ver cursor-agent --version)"; return; fi
  if reachable https://cursor.com/install; then
    curl -fsSL https://cursor.com/install | bash
    echo "installed: $(ver "$HOME/.local/bin/cursor-agent" --version)"
  else
    echo "cursor.com not reachable from here; run 'curl https://cursor.com/install -fsS | bash' on a networked host." >&2
  fi
}

install_ollama() {
  log "Ollama"
  if have ollama; then echo "already installed: $(ver ollama --version)"; return; fi
  if reachable https://ollama.com/install.sh; then
    bash setup-ollama.sh
  else
    echo "ollama.com not reachable from here; run 'bash setup-ollama.sh' on a networked host." >&2
  fi
}

install_ai_tools() {
  need_node
  install_claude
  install_codex
  install_copilot
  install_openclaw
  install_hermes
  install_cursor
  install_ollama
}

# ---------------------------------------------------------------------------
[ "$DO_BUILD" = 1 ] && install_build_deps
[ "$DO_AI" = 1 ] && install_ai_tools

log "Summary"
for t in claude codex copilot openclaw hermes cursor-agent ollama; do
  if have "$t"; then printf '  %-13s %s\n' "$t" "$(ver "$t" --version)"
  elif [ -x "$HOME/.local/bin/$t" ]; then printf '  %-13s %s (~/.local/bin, add to PATH)\n' "$t" "$(ver "$HOME/.local/bin/$t" --version)"
  else printf '  %-13s MISSING\n' "$t"; fi
done
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *)
  echo; echo "Note: add \$HOME/.local/bin to PATH for hermes / openclaw / cursor-agent launchers." ;;
esac
