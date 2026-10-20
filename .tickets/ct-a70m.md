---
id: ct-a70m
status: open
deps: [ct-qdkd]
links: []
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Use protected native retention and restore planning

Expose safe inspection/planning of native-owned retained data and restore prerequisites using maintained APIs. Keep filesystem caches and non-native archive data outside ownership. No automatic deletion or expiration.

## Acceptance Criteria

Read-only operator planning lists protected/reclaimable ownership and remote quiescence requirements. Tests prove selected, active-reader and incomplete-operation data cannot be proposed as unprotected. No live removal or restoration in this ticket.

