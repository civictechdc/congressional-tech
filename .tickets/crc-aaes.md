---
id: crc-aaes
status: closed
deps: []
links: []
created: 2026-10-28T10:36:17Z
type: task
priority: 0
assignee: mikewolfd
---
# Retain the actual offline runner exit code for hosted landing evidence

## Acceptance Criteria

All six shard commands record actual0 through5 exit code and propagate it unchanged; verifier can reject interrupted sessions; no assertion skip or CI-result relaxation; focused tests and review pass


## Notes

**2026-10-28T10:52:58Z**

Done: actual workflow shell retains one exit marker and propagates all0..5 exit statuses unchanged;-v retains collection evidence in the same test pass.80 focused checksPASS0.61s; landing exact-consumer adaptation41PASS0.53s. Independent producer APPROVE in review-window-hosted/review-fix-0bb09ed6.md; consumer phase-accounting fix remains a separate landing gate.
