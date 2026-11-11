---
id: ct-6qgg
status: open
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
