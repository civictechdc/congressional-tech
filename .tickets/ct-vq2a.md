---
id: ct-vq2a
status: open
deps: []
links: [ct-94hw]
created: 2026-11-04T20:47:30Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, correctness, release-blocker]
---
# package_id follows the saved copy: 45 documents lose it and 28 get non-GovInfo filename ids

Nightly candidate ef4c1632 vs e4538f00: when a newer identical copy becomes the saved file (saved-files.sql, newest fetch wins), detail.package_id is re-derived from the new filename. 45 documents lose package_id; 28 gain ids that are not GovInfo packages (e.g. BILLS-117hr1833ih-Katko); 2 changes look right. Evidence: .cache/archive-release/nightly/20261104T174328Z/causes/evidence/05b-possible-defect-package-id.json.

## Acceptance Criteria

package_id derives from evidence that does not depend on which identical copy is saved (any capture of the same bytes, or the GovInfo package), and only GovInfo package ids pass. Fixture: identical bytes saved under a dated HHRG name then a plain name keep the same package_id.

