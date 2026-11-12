---
id: ct-5q3g
status: closed
deps: []
links: [ct-fk4w, ct-jcnd, ct-egoo]
created: 2026-11-11T19:02:18Z
type: task
priority: 2
assignee: mikewolfd
tags: [titles, model]
---
# Titles: one model step composes document titles (title design stage 1)

Stage 1 of .cache/archive-release/investigations/title-design-20261111/DESIGN.md: titles.sql is the one place a document title is chosen, publishes detail.title_source, rules in title-rules.json, corrections in title-overrides.json; 0 title changes (proof: .cache/archive-release/investigations/title-stage1-20261111/). Next: stage 2 (MODS rank, cleanup, rejects fall through, print_number), then 3-5. Relates to ct-jcnd (item 4: one label list), ct-egoo (part 2), ct-fk4w (document text, stage 5).


## Notes

**2026-11-12T06:30:22Z**

Published in release `ede659a056c04ce0c4f51c70b6848b4eaf1db1a2a2fa8aee04076973e2a1a450` (`nightly/20261112T061147.068599Z`, commit `ea76829fa376980a038cfcc1faa16b9901223cf7`, notes `docs/releases/2026-11-12-ede659a056c0.md`). Verified on the published `detail.parquet` and `schema.json` against `21fc049940bb`: `model/sql/titles.sql` composes all 322,965 document titles with **0** title changes across all matched documents (`generic_titles = 0`, `retired_title_reviews = 0`), publishing `detail.title_source` (`None: 260,653`, `other_format_page_title: 33,958`, `page_title: 14,518`, `link_text: 12,004`, `copy_link_text: 1,240`, `label_witness: 560`, `recovered_copy: 23`, `page_heading: 9`). Stage 2+ tracked separately. Closed.
