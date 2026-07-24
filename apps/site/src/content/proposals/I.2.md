---
id: "I.2"
title: "Congressional Committee YouTube Video Dashboard & Event ID Tracking"
theme: "I"
status: "built"
effort: "2"
repo: "https://github.com/civictechdc/congressional-tech/tree/main/apps/committee_youtube"
---

Dashboard that monitors committee YouTube uploads, cross-references with Congress.gov/Docs.house.gov to link official Event IDs, and surfaces metrics and alerts.

## Problem

Committees often fail to include official Event IDs in the descriptions of their YouTube videos. This makes it difficult to link videos to official records on Congress.gov and hinders public discoverability.

## Solution

Develop a dashboard that:

- **Tracks All Committee Channels:** Monitors all House and Senate committee YouTube channels and their uploaded videos.
- **Cross-References with Official Data:** Uses APIs from Congress.gov and Docs.house.gov to cross-reference video metadata (title, date, description) with official hearing and markup information. Employs fuzzy logic matching for video titles when Event IDs are missing.
- **Displays Consistency Metrics:** Presents a clear ranking of committees based on their consistency in including Event IDs in video descriptions.
- Alerts and Reporting:
  - **Potential Feature:** Sends automated weekly emails to committee staff, listing videos that are missing Event IDs and providing the correct ID for easy updating.
  - Provides a user interface to view detailed information about each committee's video metadata and Event ID compliance.
