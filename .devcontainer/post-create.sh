#!/bin/bash

set -e

echo "🚀 Setting up Congressional Tech development environment..."

# Resolve the repo root so this works no matter where the script is invoked
# from (devcontainers/ci runs it from the workspace root).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Install the Python package graph editable. Order is leaf-first so the
# cross-package deps resolve from the local tree instead of an index:
#   congress_shared  (auth + globals + bundled CSV/metadata)
#     -> youtube_api  (youtube-fetch / youtube-analyze console scripts)
#     -> congress_api (congress-fetch / congress-analyze console scripts)
#     -> committee_youtube (aggregator app; pulls both packages)
# Installing all four registers the four console scripts into ~/.local/bin.
echo "🐍 Installing Python package graph (editable)..."
pip install --user \
  -e packages/congress_shared \
  -e packages/youtube_api \
  -e packages/congress_api \
  -e apps/committee_youtube

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
echo "🔗 Available console scripts (ensure ~/.local/bin is on PATH):"
echo "  - youtube-fetch --help"
echo "  - youtube-analyze --help"
echo "  - congress-fetch --help"
echo "  - congress-analyze --help"
echo ""
