#!/usr/bin/env bash
set -euo pipefail

# AI tooling + build dependency setup for this repository.
#
# Installs everything needed to run the CI workflows locally (autotools.yml,
# cmake.yml, unittest.yml, msys2.yml, python-package.yml) and the AI agent CLIs
# used with this repo: Claude Code, Codex, OpenClaw, Hermes Agent, GitHub
# Copilot CLI, Cursor CLI and Ollama.
#
# Usage:
#   bash setup-ai-tools.sh                # build deps + all AI CLIs
#   bash setup-ai-tools.sh --build-deps   # only system build dependencies
#   bash setup-ai-tools.sh --ai-tools     # only the AI CLIs
#
# Environment:
#   SKIP_APT=1        never touch the system package manager
#   NODE24_PREFIX     where to put a private Node 24 runtime for OpenClaw
#                     (default: /opt/node24 if writable, else ~/.local/node24)
#
# Every step is idempotent: already-installed tools are reported and skipped,
# and the system package step is skipped entirely when every package is
# already present. Vendor `curl | sh` installers are used when their hosts are
# reachable; when they are not (sandboxed CI, restricted egress) the script
# falls back to the npm / PyPI package of the same tool, which is what the
# vendors publish.
#
# Supported package managers: apt (Debian/Ubuntu), Homebrew (macOS),
# pacman under MSYS2 (Windows) and pacman on Arch Linux.

MODE="${1:-all}"
case "$MODE" in
  all|--all) DO_BUILD=1; DO_AI=1 ;;
  --build-deps) DO_BUILD=1; DO_AI=0 ;;
  --ai-tools) DO_BUILD=0; DO_AI=1 ;;
  -h|--help) sed -n '3,29p' "$0"; exit 0 ;;
  *) echo "unknown option: $MODE" >&2; exit 2 ;;
esac

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

log()  { printf '\n==> %s\n' "$*"; }
die()  { echo "error: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
ver()  { "$@" 2>/dev/null | head -1 || true; }
reachable() {
  have curl || die "curl is required to probe $1 but is not installed"
  curl -fsSL -o /dev/null --max-time 15 "$1" 2>/dev/null
}

# Which package manager family are we on? pacman exists on both MSYS2 and
# Arch Linux with entirely different package names, so tell them apart.
pkg_manager() {
  if have apt-get; then echo apt
  elif have brew; then echo brew
  elif have pacman && [ -n "${MSYSTEM:-}" ]; then echo msys2
  elif have pacman; then echo arch
  else echo none; fi
}
PKG="$(pkg_manager)"

# MSYS2 package prefix for the active environment (msys2.yml uses MINGW64).
msys2_prefix() {
  case "${MSYSTEM:-MINGW64}" in
    MINGW64) echo mingw-w64-x86_64 ;;
    UCRT64) echo mingw-w64-ucrt-x86_64 ;;
    CLANG64) echo mingw-w64-clang-x86_64 ;;
    CLANGARM64) echo mingw-w64-clang-aarch64 ;;
    *) echo "mingw-w64-$(echo "${MSYSTEM}" | tr '[:upper:]' '[:lower:]')" ;;
  esac
}

# Install packages with whichever manager is present. pkg_install <family> pkgs...
pkg_install() {
  local family="$1"; shift
  [ "$#" -gt 0 ] || return 0
  case "$family" in
    apt)
      export DEBIAN_FRONTEND=noninteractive
      $SUDO apt-get update -qq
      $SUDO apt-get install -y -qq "$@" ;;
    brew) brew install "$@" ;;
    msys2) pacman --noconfirm -S --needed "$@" ;;
    arch) $SUDO pacman --noconfirm -S --needed "$@" ;;
    *) die "no supported package manager found (apt-get, brew, pacman); install manually: $*" ;;
  esac
}

# Debian packages not yet installed, one per line.
apt_missing() {
  local p
  for p in "$@"; do
    dpkg-query -W -f='${Status}\n' "$p" 2>/dev/null | grep -q "install ok installed" || echo "$p"
  done
}

# ---------------------------------------------------------------------------
# 1. Build dependencies (mirrors .github/workflows/*.yml)
# ---------------------------------------------------------------------------
# autotools.yml / cmake.yml / unittest.yml / installer-for-windows.yml
APT_PKGS=(
  build-essential g++ clang cmake ninja-build pkg-config
  autoconf automake libtool
  libleptonica-dev libtiff-dev libarchive-dev libcurl4-openssl-dev
  libpango1.0-dev libicu-dev cabextract curl jq git
  python3 python3-pip python3-venv
)
# autotools-macos.yml / unittest-macos.yml
BREW_PKGS=(autoconf automake libtool cabextract leptonica libarchive pango icu4c
  curl cmake ninja pkg-config jq git python)
# msys2.yml: host autotools + MinGW libraries
MSYS2_HOST_PKGS=(autoconf automake automake-wrapper git libtool make)
# Arch Linux equivalent (base-devel carries gcc, make, autoconf, automake, libtool)
ARCH_PKGS=(base-devel clang cmake ninja pkgconf leptonica libarchive curl pango icu
  cabextract jq git python python-pip)

install_build_deps() {
  log "Build dependencies ($PKG)"
  if [ "${SKIP_APT:-0}" = "1" ]; then
    echo "SKIP_APT=1, skipping system packages"
  else
    case "$PKG" in
      apt)
        local missing
        missing="$(apt_missing "${APT_PKGS[@]}")"
        if [ -z "$missing" ]; then
          echo "all ${#APT_PKGS[@]} apt packages already installed"
        else
          echo "installing:" $missing
          # shellcheck disable=SC2086
          pkg_install apt $missing
        fi ;;
      brew) pkg_install brew "${BREW_PKGS[@]}" ;;
      msys2)
        local pfx; pfx="$(msys2_prefix)"
        pkg_install msys2 "${MSYS2_HOST_PKGS[@]}" \
          "$pfx-gcc" "$pfx-gcc-libs" "$pfx-cmake" "$pfx-ninja" "$pfx-pkg-config" \
          "$pfx-leptonica" "$pfx-libarchive" "$pfx-curl" "$pfx-icu" "$pfx-pango" \
          "$pfx-cairo" "$pfx-zlib" "$pfx-python" "$pfx-python-pip" ;;
      arch) pkg_install arch "${ARCH_PKGS[@]}" ;;
      *) echo "No supported package manager found (apt-get, brew, pacman); install build deps manually." >&2 ;;
    esac
  fi

  # python-package.yml: contrib/spotify-recommender
  if have python3 && [ -f contrib/spotify-recommender/pyproject.toml ]; then
    log "Python subproject (contrib/spotify-recommender)"
    ensure_pip
    # Distro-managed Pythons (PEP 668) refuse plain installs; retry with the override.
    python3 -m pip install -q -e "contrib/spotify-recommender[dev]" flake8 \
      || python3 -m pip install -q --break-system-packages -e "contrib/spotify-recommender[dev]" flake8
  fi

  log "Build dependency versions"
  for m in lept libtiff-4 libarchive libcurl; do
    printf '  %-12s %s\n' "$m" "$(pkg-config --modversion "$m" 2>/dev/null || echo MISSING)"
  done
}

ensure_pip() {
  python3 -m pip --version >/dev/null 2>&1 && return 0
  echo "pip is missing for $(command -v python3); installing"
  python3 -m ensurepip --upgrade >/dev/null 2>&1 \
    || python3 -m ensurepip --upgrade --user >/dev/null 2>&1 \
    || { [ "$PKG" = apt ] && [ "${SKIP_APT:-0}" != "1" ] && pkg_install apt python3-pip; } \
    || true
  python3 -m pip --version >/dev/null 2>&1 || die "python3 has no pip module; install python3-pip (or equivalent) and re-run"
}

# ---------------------------------------------------------------------------
# 2. AI agent CLIs
# ---------------------------------------------------------------------------
need_curl() {
  have curl && return 0
  log "curl is required for the vendor installers"
  case "$PKG" in
    apt) pkg_install apt curl ;;
    brew) pkg_install brew curl ;;
    msys2) pkg_install msys2 "$(msys2_prefix)-curl" ;;
    arch) pkg_install arch curl ;;
    *) die "curl is not installed and no package manager was found" ;;
  esac
}

need_node() {
  if ! have node || ! have npm; then
    log "Node.js + npm are required for Claude Code, Codex, Copilot, OpenClaw"
    case "$PKG" in
      apt) pkg_install apt nodejs npm ;;
      brew) pkg_install brew node ;;
      msys2) pkg_install msys2 "$(msys2_prefix)-nodejs" ;;
      arch) pkg_install arch nodejs npm ;;
      *) die "Node.js is not installed and no package manager was found; install it from https://nodejs.org" ;;
    esac
    have node && have npm || die "Node.js/npm still not on PATH after install"
  fi
  ensure_npm_prefix_writable
}

# Distro-managed Node usually has a root-owned global prefix. Rather than
# running npm under sudo, point global installs at a user-owned prefix so
# `npm install -g` works for any user; binaries land in ~/.local/bin.
ensure_npm_prefix_writable() {
  local prefix
  prefix="$(npm prefix -g 2>/dev/null || true)"
  if [ -n "$prefix" ] && { [ -w "$prefix/lib/node_modules" ] || { [ ! -e "$prefix/lib/node_modules" ] && [ -w "$prefix/lib" ]; }; } \
     && [ -w "$prefix/bin" ]; then
    return 0
  fi
  export npm_config_prefix="$HOME/.local"
  mkdir -p "$HOME/.local/bin" "$HOME/.local/lib"
  echo "npm global prefix $prefix is not writable; using $npm_config_prefix (binaries in ~/.local/bin)"
}

node_ok_for_openclaw() {
  # OpenClaw's engines field: node >=24.16.0 <25 || >=26.1.0
  node -e 'const [M,m]=process.versions.node.split(".").map(Number);
           process.exit((M===24&&m>=16)||(M>26)||(M===26&&m>=1)?0:1)' 2>/dev/null
}

# Provide a private Node 24 runtime from the npm registry (the `node` package
# ships the official binaries) without replacing the system node.
ensure_node24() {
  if have node && node_ok_for_openclaw; then echo "node $(node --version) satisfies OpenClaw"; return 0; fi
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
    if node_ok_for_openclaw; then
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
    if ! have uv; then ensure_pip; python3 -m pip install -q uv || python3 -m pip install -q --user uv; fi
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

# Installs only the ollama CLI. Starting the server and pulling a model is a
# separate, explicit step: `bash setup-ollama.sh [model]`.
install_ollama() {
  log "Ollama"
  if have ollama; then echo "already installed: $(ver ollama --version)"; return; fi
  if reachable https://ollama.com/install.sh; then
    curl -fsSL https://ollama.com/install.sh | sh
    echo "installed: $(ver ollama --version)"
    echo "to start a server and pull a model: bash setup-ollama.sh [model]"
  else
    echo "ollama.com not reachable from here; run 'curl -fsSL https://ollama.com/install.sh | sh' on a networked host." >&2
  fi
}

install_ai_tools() {
  need_curl
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
