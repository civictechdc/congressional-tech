---
id: cef-bb8z
status: closed
deps: []
links: []
created: 2026-10-28T05:26:12Z
type: task
priority: 2
assignee: mikewolfd
---
# Validate kept release inputs before derived retention

Build a local-tested metadata-only release retention plan and collector for weekly lake guards. Preserve live, previous and explicit pins; validate every kept input identity and receipt list; refuse changed pointer before deleting only old unkept derived release keys.


## Notes

**2026-10-28T06:31:02Z**

Local helper done: contracts7fc9c2bf,b887b52a,563019a2 and binding e633f27a plus complete-pin fix; 40 focused production-offline cases passed in0.26s using maintained receipt/selector/profile helpers. All kept identities and exact three-table selectors qualify before derived-only deletion or D5 evidence return; historical generation guards covered. Single CODE review confirmed one concern, now fixed. Weekly CLI integration remains root scope; no live execution/raw deletion performed.

**2026-10-28T06:31:16Z**

Complete kept-pin binding03eda3fc fixes the sole confirmed review concern; bounded fix requires no additional review round per root instruction.
