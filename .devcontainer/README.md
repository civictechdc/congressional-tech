# Development Container Setup

This directory contains the configuration for a Development Container (devcontainer) that provides a consistent development environment for the Congressional Tech project.

## What's Included

### Base Environment
- **Ubuntu 22.04** base image
- **Python 3.11** with pip and common development tools
- **Node.js 20** with npm for the Next.js application
- **Git** with **Git LFS** support and **GitHub CLI** for version control and GitHub integration

### Python Environment
- Congressional YouTube package installed in development mode
- Dependencies for inflation data processing (pandas, openpyxl, requests)
- Python development tools (pylint, black formatter)

### Node.js Environment
- Next.js dependencies installed for the web application
- VS Code extensions for TypeScript and Tailwind CSS

### Development Tools
- VS Code extensions for Python, TypeScript, and web development
- Custom aliases for quick navigation between project directories
- Formatted shell prompt with helpful information

## Quick Start

1. **Open in VS Code**: If you have the Dev Containers extension installed, VS Code will prompt you to reopen in container when you open this repository.

2. **Manual Setup**: Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac) and select "Dev Containers: Reopen in Container"

3. **First Time Setup**: The container will automatically run the setup script that:
   - Installs Node.js dependencies for the Next.js app
   - Installs Python packages in development mode
   - Initializes Git LFS for the repository
   - Sets up helpful shell aliases

## Available Commands

After the container starts, you can use these commands:

### YouTube Data Processing
```bash
# Fetch YouTube data (requires API key)
youtube-fetch --youtube-api-key YOUR_KEY --channels-csv-path congress_youtube/youtube/youtube-accounts.csv

# Analyze YouTube data
youtube-analyze --channels-csv-path congress_youtube/youtube/youtube-accounts.csv

# Fetch Congress data (requires API key)
congress-fetch --congress-api-key YOUR_KEY
```

### Next.js Web Application
```bash
# Start development server
cd app && npm run dev
# Then visit http://localhost:3000
```

### Quick Navigation Aliases
```bash
ct-root      # Navigate to project root
ct-app       # Navigate to Next.js app directory  
ct-youtube   # Navigate to YouTube data project
ct-inflation # Navigate to inflation data project
```

## CI/CD Integration

The GitHub Actions workflow (`update-youtube.yml`) uses the same devcontainer environment via `devcontainers/ci@v0.3`, ensuring consistency between development and CI environments.

## Customization

- **VS Code settings**: Modify `.devcontainer/devcontainer.json`
- **System packages**: Edit `.devcontainer/Dockerfile`
- **Setup steps**: Update `.devcontainer/post-create.sh`
- **Shell environment**: Customize `.devcontainer/bashrc`

## Troubleshooting

### Container won't start
- Ensure Docker is running on your system
- Try rebuilding the container: "Dev Containers: Rebuild Container"

### Python packages not found
- The post-create script installs packages in user mode (`--user`)
- Packages are installed to `~/.local/bin` which is added to PATH

### Permission issues
- The container runs as the `vscode` user (UID 1000)
- Files created in the container will have the correct permissions for your host system
