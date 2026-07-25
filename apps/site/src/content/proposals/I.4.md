---
id: "I.4"
title: "Appropriations Data Pipeline & Historical Analysis"
theme: "I"
status: "in-progress"
effort: "5+"
---

Comprehensive pipeline to track appropriations in real time, extract line-item data, and analyze report language historically across House/Senate stages.

## Problem

Information related to the appropriations process (bill text, committee reports, amendments, press releases) is distributed across multiple sources and often experiences delays in being updated on official platforms like Congress.gov. Analyzing historical line-item spending data and tracking changes in report language over time is also challenging.

## Solution

Develop a comprehensive system encompassing:

- **Real-time Appropriations Tracker:** A spreadsheet-based system to track the progress of appropriations bills through each stage of the legislative process (subcommittee, full committee, House/Senate floor, conference committee, joint explanatory statements). Include:
  - Bill text versions at each stage.
  - Committee report language versions at each stage.
  - Links to press releases summarizing committee actions.
  - Details of amendments offered and adopted (or rejected) at each stage.
  - Leverage an existing spreadsheet example as a starting point.
- **Line-Item Data Extraction & Visualization:** Extract line-item spending data from appropriations committee reports and transform it into structured data tables. Develop visualizations to track spending trends over time and across different accounts.
- **Report Language Analysis:** Implement a system to:
  - Identify changes in bill and report language as measures move through the legislative process.
  - Compare House and Senate versions of bill and report language to highlight differences.
  - Flag deadlines and directives to agencies contained within report language.
  - **Advanced Feature Suggestion:** Perform trend analysis on recurring report language sections across multiple Congresses to illustrate the evolution of policy and funding priorities.
