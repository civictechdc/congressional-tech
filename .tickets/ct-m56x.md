---
id: ct-m56x
status: open
deps: []
links: [ct-94hw]
created: 2026-11-04T15:19:41Z
type: task
priority: 2
assignee: mikewolfd
tags: [capture, custody]
---
# Capture scheduler records the existing object's size and ETag when a conditional upload gets 412

On 412 (object exists) the scheduler records outcome=unchanged with no stored MD5/size, so a body uploaded by a run that wrote no receipt has no pinned capture anywhere. Record the existing object's size and ETag (HEAD) on that path. Check whether captures.py maps pins on unchanged receipts first; changing captures.py changes its byte-hashed parser_version. Does not repair the 85 existing bodies (handled by the daily listing).

