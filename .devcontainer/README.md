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

#### Working with Git LFS Data Files

⚠️ **Important**: This project stores data files using Git LFS. JSON files in project `data/` directories may appear as Git LFS pointer files rather than actual data.

**To access actual data files:**

```bash
# Pull all Git LFS files (requires repository access and authentication)
git lfs pull
```

**If `git lfs pull` fails:**

- You may see `JSONDecodeError: Expecting value` when running data processing commands
- Solution: Use API commands to fetch fresh data instead of relying on cached files
- Commands will still work but may process empty datasets initially

#### Complete Workflow

**Step 1: Navigate to project**

```bash
ct-youtube
```

**Step 2: Fetch fresh data (requires API credentials)**

```bash
# Fetch congressional committee meeting data
congress-fetch --congress-api-key YOUR_DATA_GOV_KEY

# Fetch YouTube video metadata for all committees
youtube-fetch --youtube-api-key YOUR_YOUTUBE_KEY --channels-csv-path congress_youtube/youtube/youtube-accounts.csv
```

**Step 3: Analyze data**

```bash
# Analyze videos for missing event IDs
youtube-analyze --channels-csv-path congress_youtube/youtube/youtube-accounts.csv
```

#### Alternative: Run modules directly with Python

If the CLI commands aren't available, you can run the modules directly:

```bash
cd projects/1.2-committee-youtube/python

# Fetch congressional data
python -m congress_youtube.congress.fetch.main --congress-api-key YOUR_DATA_GOV_KEY

# Fetch YouTube data
python -m congress_youtube.youtube.fetch.main --youtube-api-key YOUR_YOUTUBE_KEY --channels-csv-path congress_youtube/youtube/youtube-accounts.csv

# Analyze videos
python -m congress_youtube.youtube.analyze.main --channels-csv-path congress_youtube/youtube/youtube-accounts.csv
```

#### Expected Behavior

**With Git LFS data files:**

- `youtube-analyze` processes existing video metadata
- `congress-fetch` and `youtube-fetch` add new data to existing databases

**Without Git LFS data files:**

- `youtube-analyze` may encounter JSON parsing errors or process empty datasets
- `congress-fetch` and `youtube-fetch` create new databases from scratch
- You'll see warnings about missing or invalid data files

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

### Container Issues

**Container won't start:**

- Ensure Docker is running on your system
- Try rebuilding the container: "Dev Containers: Rebuild Container"

**Python packages not found:**

- The post-create script installs packages in user mode (`--user`)
- Packages are installed to `~/.local/bin` which is added to PATH

**Permission issues:**

- The container runs as the `vscode` user (UID 1000)
- Files created in the container will have the correct permissions for your host system

### Data Processing Issues

**"JSONDecodeError: Expecting value" errors:**

- This typically means Git LFS pointer files are being read as JSON
- Solution: Use `git lfs pull` or fetch fresh data with API commands
- The system may have built-in fallbacks for some operations

**Commands not found:**

- Ensure you're in the dev container environment
- Try running modules directly with `python -m` as shown in the YouTube Data Processing section

**Empty analysis results:**

- Data files may be Git LFS pointers; fetch fresh data or use `git lfs pull`
- Check that API keys are correctly configured for data fetching commands
