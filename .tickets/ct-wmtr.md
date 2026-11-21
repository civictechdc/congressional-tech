---
id: ct-wmtr
status: closed
deps: []
links: []
created: 2026-11-21T06:43:44Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-qmh5
---
# Require named review before withdrawing a saved archive download

A release comparison can report a previously saved file with no primary copy in the candidate. The automatic recapture check currently equates that empty answer with an absent receipt match. The manual correction record also requires a replacement hash, so it cannot describe an intentional withdrawal. The release must distinguish a reviewed bad copy from accidental loss.

## Acceptance Criteria

Keep the unattended release stopped for every unproven withdrawal. A reviewed release can name each affected link, lookup key or source address with its exact prior hash and an explicit empty primary only when that hash appears in the reviewed unusable-download registry. Refuse unreviewed, mismatched and unnamed withdrawals. Preserve the existing gates for positive replacements.


## Notes

**2026-11-21T06:46:36Z**

Both planted checks failed on the old publisher. With the fix, an absent receipt proves zero recaptures and a cause record must name each affected key and the reviewed prior file. The release, cause-record and data-only checks passed all 498 cases.

**2026-11-21T09:03:16Z**

The hosted publisher stopped release 1fad38cc75ba before switching the public pointer. A reviewed cause matched 97 findings across 32 document links, 35 lookup keys and 26 source addresses, each to an exact prior hash and an empty primary. The ordinary publisher then selected the release, and the public check confirmed all 31 document pages still open. [Release safeguard](https://github.com/civictechdc/congressional-tech/pull/221) · [Applied release record](https://github.com/civictechdc/congressional-tech/pull/223)
