---
id: ct-f6xa
status: closed
deps: []
links: [ct-ogcq]
created: 2026-11-25T12:01:57Z
type: task
priority: 2
assignee: mikewolfd
tags: [archive, warc, release]
---
# Record Gate-1 release cause for 8,510 retired WARC/ARC envelope link_keys on next archive publish

Because PR #240 (ct-ogcq) classifies format='other' WARC/ARC envelopes in model/sql/record-roles.sql as record_role='envelope', the next full model publish will intentionally retire the 8,510 legacy format='other' WARC/ARC envelope link_keys from 0e7084cd... into retired_links.parquet (7,661 duplicates pointing to their capture_index=0 unwrapped payload, 829 non-document listing/wrapper shells removed, and 20 promoted to saved_kind='recovery' PDFs; zero R2 backfill needed). Investigation evidence: .cache/archive-release/investigations/ct-ogcq-warc-promotion-20261124.md.

## Acceptance Criteria

Next archive release Gate-1 cause record documents the 8,510 intentional WARC/ARC envelope link_key retirements with zero unattributed retirements or Gate-1 failures.

## Notes

**2026-11-25T19:56:30Z**

Closed after live `Archive publish` run `45683220871` (https://github.com/civictechdc/congressional-tech/actions/runs/45683220871) completed with `conclusion: success` under cause PR #248 (`61fd54f3`, `model/jobs/release-causes/453351a3a57b-a422335579f0.json`), promoting live release `a422335579f0df176199c406f7f5b56e7d7278e61faaea4069baee1c530e8228` (PR #240 WARC retirements + PR #243/#244/#245 organization tables + `45621357436` daily receipts).

