---
id: cef-3mv3
status: closed
deps: []
links: []
created: 2026-10-28T06:35:03Z
type: task
priority: 2
assignee: mikewolfd
---
# D5 retire managed maintenance activation


## Notes

**2026-10-28T06:36:34Z**

Owner ARCH 8.6 decision replaces managed provider activation with application-owned generation rebuilds. Retained configure import/signature and legacy CLI options; execution now refuses before any client/environment access. Removed HTTP enable/readback code and credential dependencies; policy states disabled while reports explicitly state remote configuration was not observed. Contract b451cb32 red on old activation only (10 failures, 8 validation passes); focused pure production-offline runner with qualified71 now 18 passed in 0.04s. No native jobs, provider requests or credential reads. Awaiting root one code review before closure.

**2026-10-28T06:59:49Z**

CODE APPROVE: cx_d5_disable_review/review.md, no findings. 18 focused policy/CLI checks pass; execute refuses before client/HTTP/credential access, remote_state explicitly not_observed.
