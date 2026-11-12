---
id: ct-v8us
status: closed
deps: []
links: []
created: 2026-11-10T13:26:44Z
type: task
priority: 3
assignee: mikewolfd
tags: [model, gate, meetings]
---
# meetings.outcome_source_reference stores a release-local row number: 516 rows differ at every release for no reason

Found 2026-11-10 in the release 619db5f9e08e difference review (.cache/archive-release/release-20261110/causes-2/reference/). For a committee_transcript outcome the column stores the transcript's list_row, which is valid only inside one release. Any release that adds documents shifts it: 516 of the 520 changed rows were pure renumbering (offsets -144 to +1,170), each old and new row holding the same file name and sharing a link key; the 11-08 release recorded the same 516 for the same reason. Each release therefore needs a hand-written cause for a non-change.

## Acceptance Criteria

The reference is stored or compared through a release-stable key (the link key, as the gate already does for transcripts), so an unchanged meeting produces no difference; one release comparison shows zero renumbering rows.


## Notes

**2026-11-10T20:39:29Z**

2026-11-10 still happening in release 77673bfb8fcf. Checked on published release 77673bfb8fcf against 619db5f9e08e with DuckDB on the published tables. Meetings whose outcome_source_reference differs: 530, and 516 of them have the same outcome and outcome_basis, so they changed only by renumbering. The cause record explained the group by hand again (ct-v8us, ct-h8dr).

**2026-11-11T14:43:58Z**

validated 2026-11-11, left open: not fixed; release 77673bfb8fcf still shows 516 renumber-only rows of 530 changed outcome_source_reference values against 619db5f9e08e (2026-11-10 note), and no commit names ct-v8us since its filing.

**2026-11-12T02:50:30Z**

Implemented on `claude/ct-wave-4-model`: `model/sql/entity-meetings.sql` now joins `committee_transcript` rows of `transcript_ranked` (left build side) to `details` on `list_row` and publishes `lower(encode(d.link_key,'hex'))` as `outcome_source_reference` instead of `cast(list_row AS VARCHAR)`. Updated `model/registries/release-schema.json`, regenerated `docs/release-relationships.md`, updated the `release_comparison.py` comment, and verified all repo readers (`HearingDetail.tsx` renders the string directly; `release_comparison.py` only compares 64-hex `record_sha` on publisher outcomes). Added unit + row-shift stability test in `test_meeting_outcome_evidence.py`. Ready to close once the Wave 4 release ships and the subsequent release comparison shows zero renumbering rows.

### Final Wave 4 Verification & Merge Closeout (2026-11-12)
- **Code Commit:** `4a19b8cb` (`claude/ct-wave-4-model`, fast-forwarded onto `origin/main`)
- **Hosted CI (`validate-explorer.yml`):** Run `43250539064` — **7/7 GREEN** (all 6 offline shards + Explorer bundle validation)
- **Blind Multi-Skill Review:** Round 3 **SHIP** (`0 P0, 0 P1, 0 P2`)
- **End-to-End 4-Hop Horizontal Verification:** Candidate release `a1a07698ef50066bf41f621751b0c83c5912e9a71e45bb7b40077d0658e44003` (`0` violations across all 36 invariants) + Playwright Chromium UI & live `ede659a056c0` comparison documented in `wave4_horizontal_e2e_trace.md`.
