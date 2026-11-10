---
id: ct-4nax
status: open
deps: []
links: []
created: 2026-11-10T19:07:52Z
type: task
priority: 0
assignee: mikewolfd
---
# Release gate: a changed link passes only as a named correction in the reviewed record

The link rule refuses any live link key, lookup key or address that answers another file, and no record overrides it (ct-4qld, ct-wscb). The owner's record corrections (ct-u9y4) change 30 link keys and 38 lookup keys on purpose, so release aef93461 cannot pass. Owner decision 2026-11-10 (questions dialog): 'Accept named corrections': the gate lets a changed answer through only when the reviewed cause record names that exact key with its live file, its candidate file and the correction decision; any key not named still refuses; missing, dangling and unchecked stay absolute. Follow-up for the data-proven form is a separate ticket.

