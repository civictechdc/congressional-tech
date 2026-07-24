---
id: "II.1"
title: "Automated Google Doc Creator for Meetings"
theme: "II"
status: "idea"
effort: "2"
---

Firefox bookmarklet that creates consistently named, pre-formatted Google Docs for meeting notes in the right Drive folder.

## Problem

Manually creating Google Docs for meeting notes is a repetitive and time-consuming task, often leading to inconsistencies in formatting and file naming.

## Solution

Develop a Firefox browser bookmarklet that automates the creation of new Google Docs for meeting notes:

- **Folder Creation:** Creates the new document within a pre-defined Google Drive folder.
- **Standardized Naming:** Automatically names the file using a consistent format: `YYYY-MM-DD [Person's Name]`. (e.g., "2025-01-15 Jane Smith"). A window should popup prompting the user for this name.
- **Pre-populated Format:** Sets up the document with a pre-defined template:
  - Person's name centered on the first line.
  - Date centered on the second line.
  - Cursor positioned, left-aligned, on the fourth line for note-taking.
- **Deployment:** Current Status: The script is already built, but deployment as a persistent Firefox bookmarklet is the remaining challenge.
