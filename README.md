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