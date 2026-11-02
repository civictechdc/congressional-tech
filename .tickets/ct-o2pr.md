---
id: ct-o2pr
status: open
deps: []
links: [ct-qg8e, ct-64el]
created: 2026-11-02T00:36:42Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, site, phase2]
---
# Hearing pages show duplicate transcripts

Events with duplicate transcript entries went from 3,199 to 11,263 in 448651e7, 8,064 of them new; entries went from 20,531 to 32,882. 959c23ee adds one entry per row, HearingDetail.tsx:172 does not dedupe, and no expected entry count was defined. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.

## Acceptance Criteria

The model defines one transcript entry per hearing package with its formats, and a check enforces it. Recheck after the ZIP rule, which may remove the new duplicates.


## Notes

**2026-11-02T04:01:45Z**

No code yet; recheck after a rebuild, since the ZIP rule may remove the new duplicates. The one-per-package rule and check do not exist.

**2026-11-02T10:36:11Z**

2026-11-02: one confirmed duplicate source. Cloudflare email obfuscation makes the ZIP member HTML (b14d49d9) and the direct HTML (c7768761) of CHRG-119hhrg64404 fingerprint differently though they are the same transcript. See ct-64el.

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): plan-g predicts about 2,906 events still duplicate after the ZIP rule. Fix: one entry per event and package with its formats, enforced by a failing check. Main duplicate source: Cloudflare email obfuscation (41,995 bodies; 6,850 of 6,864 differing ZIP-vs-direct pairs), NULL fingerprints (30,139 html readings), and ZIP members lacking their published address as an endpoint. impl-g, r1b-g.

**2026-11-02T13:15:40Z**

2026-11-02 (lead): impl-g r1b-g: 6,854 of 6,864 split packages now join. 7 differ only by a double-encoded U+FFFD in GovInfo's direct bytes; they stay as versions this release, and normalizing replacement characters in the fingerprint moves to Round 2's full html re-read (ct-pocg). CHRG-119hhrg60951 has different heading lines, so it's a real version. Run A on key packages: 2,853 events / 2,267 packages still duplicate on base code (predicted about 2,906).

**2026-11-02T14:16:11Z**

2026-11-02 impl-g (r1b-g): Run B slice (36,692 html bodies re-read): duplicate-transcript events 2,853 to 14 on key packages; 7,186 of 7,266 key packages are one document (Run A: 418); 71 of the remaining 80 are HTML+PDF not grouped, pre-existing. The slice doesn't build meetings, so the per-package entry rule is measured on the full run.
