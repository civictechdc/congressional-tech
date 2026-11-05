---
id: ct-vrxc
status: open
deps: []
links: [ct-vq2a]
created: 2026-11-05T02:36:33Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, parser]
---
# Filename date lost when a title contains 'Act of YYYY' before the real date (EPS Improvement Act of 2016 1-12-16)

saved-copy-identity stops 'Act of <year>' from dating documents, which loses the real trailing date on 'FP Opening Statement--EPS Improvement Act of 2016 1-12-16.pdf' (was 2016-01-12, now undated). A correct fix needs the filename reader to skip the act-title token and keep reading, which bumps the house_naming parser version (byte-hashed) and needs a filename_readings backfill.

## Acceptance Criteria

The reader dates that filename 2016-01-12 and still refuses 'Act of 2019_6-23-20' style misreads; batch with the next filename-reader change.

