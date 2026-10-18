#!/bin/bash

set -e

echo "🚀 Setting up Congressional Tech development environment..."

# Resolve the repo root so this works no matter where the script is invoked
# from (devcontainers/ci runs it from the workspace root).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# The same lock and prerequisite checks used by CI. Poppler is an explicit
# container dependency; the macOS doctor only prints its installation command.
sudo apt-get update
sudo apt-get install -y --no-install-recommends poppler-utils procps
if ! command -v uv >/dev/null 2>&1; then
    python3 -m pip install --user 'uv==0.11.21'
    export PATH="$HOME/.local/bin:$PATH"
fi
uv sync --locked
. .venv/bin/activate
python scripts/dev.py prepare-baseline
python scripts/dev.py inventory
python scripts/dev.py doctor

# Node workspaces (Astro site, etc.) - best effort. The Python CLI jobs don't
# need it, so a hiccup here must not fail container setup.
if command -v npm >/dev/null 2>&1; then
    echo "📦 Installing Node workspace dependencies (best effort)..."
    npm install --no-audit --no-fund || echo "⚠️  npm install skipped/failed (non-fatal)"
fi

# Set up git configuration if not already set
if [ -z "$(git config --get user.name)" ]; then
    echo "⚙️  Setting up git configuration..."
    git config --global init.defaultBranch main
    git config --global pull.rebase false
    echo "ℹ️  Please set your git user.name and user.email:"
    echo "    git config --global user.name 'Your Name'"
    echo "    git config --global user.email 'your.email@example.com'"
fi

echo "✅ Development environment setup complete!"
echo ""
echo "🔗 Available console scripts (run source .venv/bin/activate):"
echo "  - youtube-fetch --help"
echo "  - youtube-analyze --help"
echo "  - congress-meetings --help"
echo "  - congress-committees --help"
echo "  - meeting-inventory --help"
echo ""
