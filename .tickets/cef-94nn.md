---
id: cef-94nn
status: closed
deps: []
links: []
created: 2026-10-28T14:12:52Z
type: task
priority: 1
assignee: mikewolfd
---
# Pass bounded native limits through the retained news CLI

Expose the existing DocSpecClient limits parameter on every retained news CLI operation so local and CI native integration tests can use one explicit host-sized profile without changing defaults, skips, assertions, or native admission. Verify parsing and the existing real native CLI lifecycle with explicit bounded limits.


## Notes

**2026-10-28T14:23:45Z**

Local optional news CLI forwarding complete0e9af87c after49171457 contracts. Fivepublic-command checksRED5→GREEN5in0.83s including real native refusal for missing selected limits file. CODEAPPROVE native-cli-limits-review.md/no concerns. Default native limits unchanged. This is CI-health follow-up, not a local switch gate per lead141825. Explorer/Weekly/sync-weekly retention/forwarding tracked separatelycef-jh7i forF5.
