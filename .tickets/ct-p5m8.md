---
id: ct-p5m8
status: open
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 3
assignee: mikewolfd
tags: [video, reader]
---
# Video titles and descriptions flip between empty, one space and trailing space across cache refreshes

Release 2026-11-10: 31 descriptions go NULL to one space, one gains two spaces (youtube:asMWWn5Ztvs), 8 descriptions and 4 titles gain a trailing space; YouTube's text is unchanged and the cache keeps whichever of two answers was fetched last. 1,064 whitespace-only descriptions are already live. Source: .cache/archive-release/release-20261110/causes/video/README.md.

## Acceptance Criteria

The video record reader normalises surrounding whitespace and maps whitespace-only text to null; the count of whitespace-only titles and descriptions in a build is 0.

