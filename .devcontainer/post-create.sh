#!/bin/bash

set -e

echo "🚀 Setting up Congressional Tech development environment..."

# Install npm dependencies for the Next.js app
echo "📦 Installing Node.js dependencies..."
cd /workspaces/congressional-tech/app
npm install

# Install Python dependencies for the YouTube project
echo "🐍 Installing Python dependencies..."
cd /workspaces/congressional-tech/projects/1.2-committee-youtube/python
pip install --user -e .

# Install dependencies for the inflation project
echo "📈 Installing inflation project dependencies..."
cd /workspaces/congressional-tech/projects/5.1-inflation-gsheets
pip install --user pandas openpyxl requests

# Go back to root
cd /workspaces/congressional-tech

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
echo "🔗 Available services:"
echo "  - Next.js app: http://localhost:3000 (run: cd app && npm run dev)"
echo "  - YouTube data fetcher: youtube-fetch --help"
echo "  - YouTube analyzer: youtube-analyze --help"
echo "  - Congress data fetcher: congress-fetch --help"
echo ""
