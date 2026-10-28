# First full v5 seed: qualified on its recorded graph

The full native conversion passed on site source `19b0327d`, runtime `885e8c3`, in 468.151 seconds. The maintained monitor measured 469.132 seconds, 7,960,976,968 B peak physical memory and 6,204,768,256 B peak RSS. Limits remained four CPUs, 14 GiB native pool, 3 GiB spill, 16 GiB physical memory and 5 GiB scratch. The lead approved the qualified 2,700-second runtime bound after the final-query diagnostic. No data guard changed.

Release: `2ebf773da49d326ec6fe75f1dc8fa4060991575cac66676633976e08cd9a4558`.

- All five common and nineteen seed guards are zero; all fifty sampled comparisons pass.
- Documents reconcile exactly: 1,241,157 = 936,580 listed + 281,200 merged duplicates + 23,377 excluded. Exclusions are 3,532 missing filenames and 19,845 missing formats (1.883%).
- Physical source rows reconcile exactly: 1,683,430 = 1,660,052 included + 23,378 excluded. The approved same-body document-name rule supplied 95,298 source filenames.
- The actual reader canary passed in 9.684 seconds, including a saved-copy GET from the public read-only raw origin. Targets were still owner-gated. Estimated retained list bytes were 129,956,240; estimated peak was 159,926,824. Sampled Node heap plus external memory peaked at 495,772,774 B.
- The built-site browser checks passed at desktop 1440×1000 and phone-sized 412×823, including stale/404 recovery and old-pointer refusal. These were correctness checks, without qualified throttled performance targets.

This release is not the final publication candidate: the root's final merged definitions include a newer raw-model module in the seed's custody profile. The imported probe helper remains exactly equal, and all twelve public files plus the manifest of the actual fifty-document sample remain byte-identical after merging root, but the profile must not be retagged. A fresh full build on the final merged definitions is required. Final phone/desktop targets remain on hold until core's deploy-path DISTINCT impact check clears the lead's conditional 885 pin.

Private evidence: `codex-site/seed/full-v5/{build-profile.json,job/result.json,reader-first.json,browser-first.json}`, `full-monitor-v5/`, and `landing-definitions-digest-equality.json`. Every DISTINCT occurrence in the frozen full SQL job is retained in `full-v5/distinct-inventory.json`; the SELECT DISTINCT sites are `lookup_sources`, `lookup_parts`, `url_keys`, four coverage subqueries over materialized tables, and the private five-column seed-members export. Core owns the final native trigger assessment.
