---
id: ct-aoxp
status: in_progress
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


## Notes

**2026-11-10T13:27:30Z**

2026-11-10 status: fixed on the stacked next-release branch claude/ct-next-release (commits 672bf44a test, 787ea6d7 fix: the help page is a wrapper through registry kind wrapper_url). Lanes green on the source branch (six shards + storage-loopback). Left: lanes and a full model build on the stack, the one review, release. Closes when released.
