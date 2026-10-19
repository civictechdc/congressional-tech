# Shared baseline for the remaining efficiency and debt work

The integration preserves the eleven local Grok/Cursor commits through `5150f34` and the reviewed backlog/evidence commit `9400073`. Command scripts are grouped by purpose; reusable recovery and publication code belongs to `corpus_recovery` and `viewer_publication`.

Independent review found move regressions before merge. Repair commit `1478865beea896e43b860972859f9a542cab03d5` corrects browser benchmark paths, historical measurement module selection, preservation-probe scope, frozen transcript classification, focused-test import paths, eager package imports, unbounded admission hashing, and executing-module pins. It also corrects entry-point documentation and checks explicit verification roots. Each repair has focused failure-path coverage and independent cross-review.

The complete local `production-offline` lane passed **9,459 tests and 38 subtests**, with 50 tests excluded by the declared lane. Pytest took 293.25 seconds; the measured command took 295.18 seconds. No reviewed file changed during execution. Focused repair runs passed 142 measurement/Web Harvest checks, 149 recovery tests plus five subtests, and 41 publication/status tests; these counts overlap the complete lane and are not additive.

The full conflicting-runtime requirement remains open under `ct-piku`; fixing eager preflight imports does not establish complete alternate-runtime ownership. All twelve existing efficiency/debt followups retain their acceptance criteria. Local tests are the user-requested merge gate; no CI, hosted publication, source acquisition, held-out classification or new production performance result is claimed.

`integration-evidence.json` records exact artifact hashes retained in the primary checkout. Original findings remain available alongside repair and cross-review receipts, so the initial rejected shape is distinguishable from the accepted repair.
