---
id: "deltatrack"
title: "DeltaTrack"
tagline: "Structural bill-version diffs for Hill staffers"
repo: "https://github.com/civictechdc/DeltaTrack"
upstream: "https://github.com/AgoraDMV/DeltaTrack"
liveUrl: "https://agoradmv.github.io/DeltaTrack/hr4366_committee_vs_floor.html"
liveLabel: "Live example — HR 4366, committee vs. floor"
status: "live"
proposal: "I.4"
order: 1
---

DeltaTrack structurally diffs two versions of a U.S. bill and shows what actually changed — added, removed, modified, and moved sections — instead of the formatting noise a plain text diff produces.

## What it does

DeltaTrack pulls official bill text straight from the GPO govinfo repository and compares two versions section by section. Rather than a line-by-line character diff, it reports the structural changes a legislative analyst cares about:

- **Added, removed, and modified sections** between two stages of a bill.
- **Moved sections**, detected and labeled as moves rather than a delete-plus-add.
- An **account-level appropriations money table** that lays old dollar amounts against new ones, so a reader can see exactly how funding shifted.

It runs fully local with **zero dependencies** — a single self-contained artifact a staffer can open in a browser, with nothing to install and no data leaving their machine.

## Why it matters

When an appropriations bill moves from subcommittee to full committee to the floor, the meaningful changes hide inside hundreds of pages of reformatted text. DeltaTrack answers "what changed, and by how much" in seconds — the exact question Hill staffers ask at every stage of markup.

## How it relates to proposal I.4

DeltaTrack is a concrete piece of proposal I.4, the Appropriations Data Pipeline & Historical Analysis. It delivers the report-language and bill-text comparison layer — identifying changes as measures move through the process and highlighting differences between versions — as a shipping, standalone tool.

## Links

- [civictechdc fork](https://github.com/civictechdc/DeltaTrack) — the Congressional Tech copy, kept in sync with upstream daily.
- [AgoraDMV upstream](https://github.com/AgoraDMV/DeltaTrack) — the original project this is forked from.
- [Live example — HR 4366, committee vs. floor](https://agoradmv.github.io/DeltaTrack/hr4366_committee_vs_floor.html) — a rendered diff you can open right now.
