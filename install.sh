#!/usr/bin/env bash
# Clipper-Flash one-command installer (macOS / Linux)
# Usage: curl -fsSL https://raw.githubusercontent.com/tahacore/Clipper-Flash/main/install.sh | bash
set -euo pipefail

info() { printf '\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32mOK %s\033[0m\n' "$1"; }
warn() { printf '  \033[33m!! %s\033[0m\n' "$1"; }

info "Clipper-Flash installer ($(uname -s))"

export PATH="$HOME/.local/bin:$PATH"

# --- 1. uv (installs/manages Python for us) -----------------------------------
if ! command -v uv >/dev/null 2>&1; then
    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv $(uv --version | awk '{print $2}')"

# --- 2. Python 3.12 ------------------------------------------------------------
info "Ensuring Python 3.12..."
uv python install 3.12 >/dev/null 2>&1 || true
ok "python ready"

# --- 3. FFmpeg -----------------------------------------------------------------
if ! command -v ffmpeg >/dev/null 2>&1; then
    info "Installing FFmpeg..."
    case "$(uname -s)" in
        Darwin)
            if command -v brew >/dev/null 2>&1; then
                brew install ffmpeg
            else
                warn "Homebrew not found - install it from https://brew.sh then rerun"
            fi
            ;;
        Linux)
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg
            elif command -v dnf >/dev/null 2>&1; then
                sudo dnf install -y ffmpeg
            elif command -v pacman >/dev/null 2>&1; then
                sudo pacman -S --noconfirm ffmpeg
            else
                warn "No known package manager found - install ffmpeg manually"
            fi
            ;;
    esac
fi
command -v ffmpeg >/dev/null 2>&1 && ok "ffmpeg available" || warn "ffmpeg missing - cf doctor will flag it"

# --- 4. Clipper-Flash ----------------------------------------------------------
info "Installing Clipper-Flash (this can take a minute)..."
uv tool install --force "clipper-flash[vision,web] @ git+https://github.com/tahacore/Clipper-Flash" >/dev/null
ok "clipper-flash installed"

# --- 5. Agent skill -------------------------------------------------------------
info "Installing skill for Claude Code / Codex..."
cf install-skill || true

# --- 6. Verify ------------------------------------------------------------------
info "Running doctor..."
cf doctor || true

echo ""
printf '\033[35mDone! Open Claude Code or Codex and say:\033[0m\n'
printf '   "Check my channel and clip anything new."\n'
