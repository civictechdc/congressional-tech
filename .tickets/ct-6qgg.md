---
id: ct-6qgg
status: closed
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 3
assignee: mikewolfd
tags: [model, video]
---
# Recording link pattern misses malformed YouTube embeds

Seven embeds on newly read democrats-veterans pages are not recognised as recordings because the address is malformed (e.g. /embed/FySkoDtoxp8&list=...). All seven are full hearings already in videos. The pattern file is unchanged since 2026-10-30, so this predates the release. Source: .cache/archive-release/release-20261110/causes/review-video/.

## Acceptance Criteria

The seven links resolve to their recordings; a looser-pattern scan over all read pages lists any remaining non-matching embed with a reason.


## Notes

**2026-11-11T14:41:00Z**

validated 2026-11-11, left open: not fixed. model/registries/recording-sources.json youtube-embed-or-live still requires [/?#] or the end right after the 11-character id, so /embed/FySkoDtoxp8&list=... does not match; the file is unchanged since 959c23ee.

**2026-11-12T04:37:00Z**

Closed: updated `youtube-embed-or-live` in `model/registries/recording-sources.json` to accept `&` immediately after the 11-character video ID (`[/?&#]|$`) as well as double-wrapped `/embed/https://youtube.com/live/<11-char-id>` CMS embeds. All seven `democrats-veterans.house.gov` embeds (`FySkoDtoxp8`, `YzFFXeDonIg`, `jJj2qoIj-sc`, `VCiH6kOEEEk`, `3v8I_Oxrwv8`, `xtkwFNmQuUc`, `UnAZvMF-b3g`) resolve through native `recording_url_sources` SQL.

Looser-pattern scan over all 14,540 distinct retained YouTube URLs (after `url_resolve` protocol-relative expansion) leaves exactly 1 non-matching `/embed/` URL:
- `https://www.youtube.com/embed/1bxY6pFimYg021424?rel=0&wmode=opaque`: author concatenated a 6-digit MMDDYY hearing date (`021424`) directly onto the 11-character video ID `1bxY6pFimYg` (`@HouseBudgetGOP`) with no delimiter, producing a broken 17-character path segment that YouTube itself rejects and that cannot be safely matched without guessing arbitrary trailing digits on valid path segments.

### Final Wave 4 Verification & Merge Closeout (2026-11-12)
- **Code Commit:** `4a19b8cb` (`claude/ct-wave-4-model`, fast-forwarded onto `origin/main`)
- **Hosted CI (`validate-explorer.yml`):** Run `43250539064` — **7/7 GREEN** (all 6 offline shards + Explorer bundle validation)
- **Blind Multi-Skill Review:** Round 3 **SHIP** (`0 P0, 0 P1, 0 P2`)
- **End-to-End 4-Hop Horizontal Verification:** Candidate release `a1a07698ef50066bf41f621751b0c83c5912e9a71e45bb7b40077d0658e44003` (`0` violations across all 36 invariants) + Playwright Chromium UI & live `ede659a056c0` comparison documented in `wave4_horizontal_e2e_trace.md`.
