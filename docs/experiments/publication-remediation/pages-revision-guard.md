# Keep Pages code and workflow revisions together

Automatic Explorer publication run `39169129652` completed from `dbfe389` after
main had advanced to `c326ce2`. Its downstream Pages run `39170982908` used the
new workflow but checked out the older `code_revision`. That checkout did not
contain the new `setup-node-project` local action. Build failed; deploy skipped.
The successful `c326ce2` Pages deployment from run `39169960167` remained live.

Pages now admits a dispatched build only when its selected site revision equals
the workflow event revision. Main pushes remain admitted. The code checkout
always uses that event revision, while the separately verified pipeline snapshot
keeps its explicit pin. A mismatch gets a small JSON log and job summary before
any checkout, environment setup, or deployment. The pipeline publication remains
retained; a current main push can deploy it. This addresses the observed stale
producer race, not arbitrary deployment reordering or force-reset history.

Validation: 49 Pages dependency and raw-source workflow tests passed. The
regression checks job-level admission before checkout, preserved pipeline pin,
deployment dependency, and executes the exact no-checkout mismatch receipt step
with the two observed revisions. No manual dispatch or retry was used.
