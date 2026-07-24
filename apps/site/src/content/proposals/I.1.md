---
id: "I.1"
title: "Unified Congressional Hearing & Markup Data Platform"
theme: "I"
status: "idea"
effort: "3"
---

A centralized, regularly updated platform (sheet → website/wiki) that aggregates and links key committee proceeding data.

## Problem

Information about congressional hearings and markups is scattered across multiple websites (Congress.gov, Docs.house.gov, committee pages, YouTube), making it difficult for staff and the public to get a comprehensive view of legislative activity.

## Solution

Create a centralized, regularly updated platform (initially a spreadsheet, then a public-facing website/wiki) that aggregates key data points:

- Date of the hearing or markup.
- Event Type (Hearing or Markup).
- Title of the Proceeding (and separate column for Event ID).
- Committee of Jurisdiction (and separate column for unique Committee ID).
- Indication of Full Committee or Subcommittee proceeding.
- Direct Links to:
  - The committee's webpage for the proceeding.
  - The Docs.house.gov page for the proceeding (if it's a House event).
  - The video of the proceeding (YouTube or Akami).
  - The transcript of the proceeding (when available).
- Phases:
  - **Data Aggregation (Spreadsheet):** Build the initial spreadsheet, populating it with data from the various sources. Implement automated data scraping where possible.
  - **Public-Facing Platform (Wiki/Website):** Publish the aggregated data on a user-friendly website or wiki, with clear navigation and search capabilities. Manage hyperlinks appropriately.
  - **Alert System:** Develop an alert system (e.g., email notifications) to notify users when new information is added for committees they are tracking. Priority: House Administration and Senate Rules Committees.
