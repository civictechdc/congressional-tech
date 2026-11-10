---
id: ct-aoxp
status: open
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 2
assignee: mikewolfd
tags: [model, record-roles, meetings]
---
# docs.house.gov/committee/Help.aspx is published as a document of 81 meetings

Newly captured House meeting pages link the site's help page, and the model publishes it as a document of 81 meetings; it accounts for 81 of the 105 document-count rises in meeting_coverage on 2026-11-10. It is site furniture, the same family of rule as ct-m878 (GovInfo landing pages). Source: .cache/archive-release/release-20261110/causes/video/README.md (coverage section).

## Acceptance Criteria

The help page has role wrapper (or is excluded) and is a document of no meeting; a scan lists other addresses that are a document of more than N meetings with a non-document path, with the count before and after.

