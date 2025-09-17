# congressional-tech

## Contributors
| Fork | Branch Name  | Description                   |
|-----------------|--------------|-------------------------------|
| [agurvich](https://github.com/agurvich/congressional-tech)        | feature/tinydb  | adding TinyDB support  |
| mikewolfd        | N/A  | N/A  |
| [ezrajohnmitchell](https://github.com/ezrajohnmitchell/congressional-tech)        | N/A  | N/A  |
| dragonejt        | 3-congress_youtube-scrapes-congressional-committee-youtube-channels-for-all-videos  | Scraping YouTube metadata  |
| [fwliu1](https://github.com/fwliu1/congressional-tech-youtube)        | N/A  | N/A  |

## Git LFS Setup

⚠️ This repository uses [Git Large File Storage (LFS)](https://git-lfs.com/).️ ️⚠️

You **must** install Git LFS before cloning or working with this repo.

### Install Git LFS

**macOS (Homebrew):**
```bash
brew install git-lfs
```

Linux (Debian/Ubuntu):

```bash
sudo apt-get update
sudo apt-get install git-lfs
```

Linux (Fedora/RHEL/CentOS):

```bash
sudo dnf install git-lfs
```

Windows:
	•	Download and run the installer from https://git-lfs.com/
	•	Or install via Chocolatey:

```bash
choco install git-lfs
```

### Initialize Git LFS

Run this once after installing:

```bash
git lfs install
```

⚠️ If you don’t install Git LFS then running `git clone` will result in the following error message:
```bash
git-lfs filter-process: git-lfs: command not found
fatal: the remote end hung up unexpectedly
warning: Clone succeeded, but checkout failed.
You can inspect what was checked out with 'git status'
and retry with 'git restore --source=HEAD :/'
```
in which case you must delete the directory, install Git LFS following the instructions above, and try again.

## Development Containers

🐳 This repository includes [Development Container](https://containers.dev/) configuration for a consistent development environment.

### Quick Start with Devcontainers

**Prerequisites:**
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) or [Docker Engine](https://docs.docker.com/engine/install/)
- [VS Code](https://code.visualstudio.com/) with the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

**Getting Started:**
1. Clone this repository (Git LFS will be automatically configured)
2. Open the repository in VS Code
3. When prompted, click **"Reopen in Container"** or press `Ctrl+Shift+P` and select **"Dev Containers: Reopen in Container"**
4. Wait for the container to build and initialize (~3-5 minutes first time)

**What's Included:**
- **Ubuntu 22.04** base environment
- **Python 3.11** with all project dependencies pre-installed
- **Node.js 20** for the Next.js web application
- **Git LFS** pre-configured and initialized
- **VS Code extensions** for Python, TypeScript, and web development
- **Helpful shell aliases** for quick navigation between projects

**Available Commands:**
```bash
# Quick navigation
ct-root      # Navigate to project root
ct-app       # Navigate to Next.js app
ct-youtube   # Navigate to YouTube data project
ct-inflation # Navigate to inflation data project

# YouTube data processing
youtube-fetch --help      # Fetch committee YouTube videos  
youtube-analyze --help    # Analyze videos for missing event IDs
congress-fetch --help     # Fetch congressional meeting data

# Web application
cd app && npm run dev     # Start Next.js development server
```

**Benefits:**
- ✅ **No local setup required** - everything works out of the box
- ✅ **Consistent environment** - same setup for all developers and CI/CD
- ✅ **Isolated dependencies** - won't interfere with your host system
- ✅ **Pre-configured tools** - linting, formatting, and debugging ready to go

### Working with Git LFS Data Files

⚠️ **Important**: This repository uses Git LFS for large data files. JSON files in project `data/` directories may appear as Git LFS pointer files rather than actual data.

**To access actual data files:**
```bash
# Pull all Git LFS files (requires repository access and authentication)
git lfs pull
```

**If `git lfs pull` fails:**
- You may see `JSONDecodeError: Expecting value` when running data processing commands
- Solution: Use API commands to fetch fresh data instead of relying on cached files
- Commands will still work but may process empty datasets initially

### Development Workflow

**For YouTube Committee Data Project:**
```bash
# Navigate to project
ct-youtube

# With API credentials, fetch fresh data:
congress-fetch --congress-api-key YOUR_DATA_GOV_KEY
youtube-fetch --youtube-api-key YOUR_YOUTUBE_KEY --channels-csv-path congress_youtube/youtube/youtube-accounts.csv

# Analyze existing data (may require Git LFS files or fresh fetch first):
youtube-analyze --channels-csv-path congress_youtube/youtube/youtube-accounts.csv
```

**Alternative: Run modules directly with Python:**
```bash
cd projects/1.2-committee-youtube/python
python -m congress_youtube.youtube.analyze.main --channels-csv-path congress_youtube/youtube/youtube-accounts.csv
```

**Troubleshooting Common Issues:**

- **"JSONDecodeError: Expecting value"**: Git LFS pointer files being read as JSON
  - Try: `git lfs pull` or fetch new data with API commands
- **"youtube-analyze: command not found"**: Use Python module syntax as alternative
- **Empty analysis results**: Data files may be Git LFS pointers; fetch fresh data or use `git lfs pull`

## Project List

See the full project list & details at
https://github.com/civictechdc/congressional-tech/tree/main/docs/README.md

| Project name |  Level of Effort
|-----------------|--------------
| **I. Enhancing Congressional Data Accessibility & Usability** |
Unified Congressional Hearing & Markup Data Platform | 3
[Congressional Committee YouTube Video Dashboard & Event ID Tracking](https://github.com/civictechdc/congressional-tech/tree/main/projects/1.2-committee-youtube) | 2
Statements of Disbursements as Structured Data | 4
Appropriations Data Pipeline & Historical Analysis | 5+
||
| **II. Workflow Efficiency Tools for Congressional Operations** |
Automated Google Doc Creator for Meetings | 2
GitHub Wiki Indexing Bookmarklet | 2
Crosswalk Spreadsheet to Member Office Appropriations Submission Tool | 3
Floor Schedule to iCal & Enhanced Congressional Schedule Aggregation | 1
Congressional Job Board Aggregator | 1
||
| **III. Leveraging AI for Content Enhancement & Analysis** |
CRS Report Accessibility & Integration | 3
GAO Report Transformation & Dissemination | 3
Automated Committee Hearing Transcripts & Summaries | 2.5
Write My GovTrack Newsletter (AI-Powered Legislative Newsletter) | 5
Witness Database with Proceeding Links & Testimony Summarization | 5
||
| **IV. Predictive & Analytical Tools for Legislative Insight** |
Bills to Committee Referral Prediction | (not set)
Bill Delay Tracker | (not set)
Appropriations Notices & Deadlines Tracker | (not set)
Committee Funding Tracker & Visualization | (not set)
Line Up CBJs and Appropriations Committee Report Language | (not set)
||
| **V. Basic Utility Tools** |
[Inflation Calculator for Google Sheets](https://github.com/civictechdc/congressional-tech/tree/main/projects/5.1-inflation-gsheets) | 1