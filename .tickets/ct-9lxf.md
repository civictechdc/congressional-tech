---
id: ct-9lxf
status: open
deps: []
links: [ct-tk10, ct-umtm]
created: 2026-11-02T16:23:34Z
type: chore
priority: 3
assignee: mikewolfd
tags: [disk, etl]
---
# Stop disk regrowth: pipeline-data refs, proof body copies, killed-job spill, cache retention

etl-storage 2026-11-02 (.cache/archive-release/investigations/storage/): ~233 GiB project footprint. Regrowth sources: the bot branch pipeline-data, force-pushed daily and kept by the reflog for refs/remotes/origin/pipeline-data (~20 GiB in .git); compatible_proof.py:97-101 copies every body per proof attempt; killed jobs leave spill dirs; scripts/dev.py clean keeps all of .cache and output. After-release prune candidates: output/corpus-retry-20261015 32 GiB, 48 dated .cache run dirs 67.5 GiB (2.7 GiB nara files need an owner look), older output publications 8.1 GiB, legacy docspec-catalog 6.9 GiB, docspec-rs target/debug 11.7 GiB. Never prune: r2-immutable mirror, archive-release inputs, stripped runtimes, source-history.

## Acceptance Criteria

Fetch refspec excludes pipeline-data (or it's fetched shallow), with a gc in a quiet window; proofs hardlink or clone bodies; the guard or watchdog deletes a killed job's spill dir; dev.py clean has a retention list; footprint re-measured.


## Notes

**2026-11-02T17:17:02Z**

Owner decision 2026-11-02: stop fetching pipeline-data locally (done: fetch refspec ^refs/heads/pipeline-data, remote-tracking ref removed); gc after the release when agents are idle; keep the NARA files.

**2026-11-02T17:17:59Z**

2026-11-02 owner: the NARA files were being used to recover documents. .cache/document-bulk-recovery-20261014T1552Z (nara/: 10 valid veterans.house.gov transcript recoveries, 175 bodies, a run intentionally stopped on proxy failures with 'preserve results') and .cache/nara-filename-estimate-20261015 (15 GB recovery workspace: Wayback continuation, residuals, docs.house.gov follow-ups, verified-local-recoveries.json) are recovery source material: never prune; added to the agent brief.

**2026-11-02T18:59:51Z**

2026-11-02: output/corpus-retry-20261015 (32 GiB) is recovery work (recovered hearings, reports and XML packages, govinfo-bulk-qualified downloads, publication checkpoints 16 and 19 at 9 GB, recovery ledgers). Protected like the other recovery workspaces; review with the owner in the post-release cleanup. .cache/document-recovery-finish-20261013T1136Z (10.6 GiB) and .cache/document-eot-expanded-20261013 are protected too. For this release the model run uses a 15 GiB guard disk floor instead of deleting anything (80 GiB free against a 53.4 GB capture_dup spill, until the engine spill fix lands).
