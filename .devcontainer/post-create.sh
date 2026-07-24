#!/bin/bash

set -e

echo "🚀 Setting up Congressional Tech development environment..."

# Resolve the repo root (this script lives in .devcontainer/) so the setup
# works regardless of the caller's current directory.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- Python: committee_youtube (congress_youtube) package ---
# Provides the console scripts used by the update-youtube workflow:
#   youtube-fetch / youtube-analyze / congress-fetch / congress-analyze
# Installed editable (-e) so the __file__-relative data paths in
# globals.py resolve into apps/committee_youtube/data inside the repo
# (which is exactly what the workflow commits back). Installed with
# --user, so the console scripts land in ~/.local/bin; the workflow's
# runCmd prepends that directory to PATH for the non-interactive shell.
echo "🐍 Installing committee_youtube Python package (editable)..."
pip install --user -e apps/committee_youtube

# --- Node: workspace dependencies (best-effort, for local web dev) ---
# The YouTube CI job does not need Node, so this must never fail the
# container setup. Local developers still get their dependencies.
if command -v npm >/dev/null 2>&1; then
    echo "📦 Installing Node.js workspace dependencies (best-effort)..."
    npm install || echo "⚠️  npm install skipped/failed (non-fatal for Python tooling)"
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
echo "🔗 Console scripts (installed to ~/.local/bin):"
echo "  - youtube-fetch --help    (fetch committee YouTube video metadata)"
echo "  - youtube-analyze --help  (report videos missing event IDs)"
echo "  - congress-fetch --help   (fetch congressional committee events)"
echo "  - congress-analyze --help (build congress metadata)"
echo ""
