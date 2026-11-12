---
id: ct-esuu
status: open
deps: []
links: [ct-fa2h]
created: 2026-11-12T06:08:47Z
type: bug
priority: 2
assignee: mikewolfd
tags: [model, senate, filenames]
---
# Senate URLs ending in a bare UUID segment lose slug-derived filename, kind, and family

When `www.energy.senate.gov` pages under `/hearings/YYYY/M/<slug>/<uuid>` were fetched at HTTP 200 in `ct-fa2h` recapture run `20261112T031832Z-f7ede707000a`, two business-meeting HTML pages whose earlier `/hearings/hearings-YYYY-M-<slug>-<uuid>/` captures carried descriptive slugs updated their primary saved capture to the `/<uuid>`-suffixed canonical-alias URL:

- Live `21fc049940bb` row `296784` -> `ede659a056c0` row `26389`: `filename` changed from `hearings-2021-11-business-meeting-pending-nominations-60bdf4d2-9524-4699-9553-caf33a0da8be` to `60bdf4d2-9524-4699-9553-caf33a0da8be` (`https://www.energy.senate.gov/hearings/2021/11/business-meeting-pending-nominations/60bdf4d2-9524-4699-9553-caf33a0da8be`), dropping filename-derived `facts`, `document_kind` (`['business-meeting'] -> []`), and `document_family` (`['business-meeting'] -> []`).
- Live `21fc049940bb` row `296805` -> `ede659a056c0` row `25643`: `filename` changed from `hearings-2021-5-nomination-business-meeting-5c20db43-6834-46b2-b92f-40c4c719a379` to `5c20db43-6834-46b2-b92f-40c4c719a379` (`https://www.energy.senate.gov/hearings/2021/5/nomination-business-meeting/5c20db43-6834-46b2-b92f-40c4c719a379`), dropping filename-derived `facts`, `document_kind` (`['business-meeting'] -> []`), and `document_family` (`['business-meeting'] -> []`).

Recorded as an `accepted_defect` on `{detail,list}.parquet|changed {filename,document_kind,document_family}` and `detail.parquet|changed facts` in `model/jobs/release-causes/21fc049940bb-ede659a056c0.json`.

## Acceptance Criteria

- URL-derived filenames for HTML pages whose final path segment is a bare UUID (preceded by a descriptive `<slug>` segment, e.g. `/hearings/YYYY/M/<slug>/<uuid>`) retain or prefer the descriptive slug so `filename`, `facts`, `document_kind`, and `document_family` do not regress to a bare UUID.
- Covered by unit/model regression tests on `business-meeting-pending-nominations/60bdf4d2-9524-4699-9553-caf33a0da8be` and `nomination-business-meeting/5c20db43-6834-46b2-b92f-40c4c719a379`.
