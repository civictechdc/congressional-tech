---
id: "billtrax"
title: "BillTrax"
tagline: "Public legislative-intelligence platform"
repo: "https://github.com/civictechdc/BillTrax"
upstream: "https://github.com/AgoraDMV/BillTrax"
liveUrl: "https://BillTrax.AgoraDMV.org"
liveLabel: "Soft launch — BillTrax.AgoraDMV.org"
status: "soft-launch"
proposal: "I.4"
order: 2
---

BillTrax is a public-facing legislative-intelligence platform that turns raw congressional data into structured, searchable, and summarized bill information for researchers, advocates, and planning teams.

## What it does

BillTrax ingests bill data from Congress.gov and builds an analysis layer on top of it:

- **Congress.gov ingestion** of bills and their text across versions.
- **Structured bill text**, parsed into sections rather than left as an opaque document.
- **Funding-change tracking** that follows how dollar figures move between versions.
- **AI-generated summaries and topic tags** that make each bill approachable for a non-specialist and searchable by subject.

It is the server-backed, public counterpart to DeltaTrack: where DeltaTrack is a local, zero-dependency diff engine for Hill staffers, BillTrax is a hosted platform that layers AI, tracking, and cross-bill analysis on the same structured-bill approach. It is deploying to **BillTrax.AgoraDMV.org** as a soft launch.

## Why it matters

Legislative information is scattered across sources and slow to update, which keeps meaningful analysis out of reach for anyone without a dedicated research staff. BillTrax gives advocates, journalists, and planners a single place to read what a bill does, see how its funding changed, and track it over time.

## How it relates to proposal I.4

BillTrax advances proposal I.4, the Appropriations Data Pipeline & Historical Analysis. It builds the structured-data pipeline and funding-change tracking the proposal calls for, and exposes it publicly with AI-assisted summaries and topic tagging.

## Links

- [civictechdc fork](https://github.com/civictechdc/BillTrax) — the Congressional Tech copy, kept in sync with upstream daily.
- [AgoraDMV upstream](https://github.com/AgoraDMV/BillTrax) — the original project this is forked from.
- [Soft launch — BillTrax.AgoraDMV.org](https://BillTrax.AgoraDMV.org) — the public deployment target.
