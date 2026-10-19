# Colocated test integration

The completed test relocation is integrated with the previously reviewed script-package repairs. Tests now live beside the packages, application code and commands they verify, and the declared local test lane includes the new locations.

The external revision is `d0386c7a07f86fc94297e265ef3819908bc62268`; the integration base is `f409f670a9ce650837c2cb10cf77f29ecad4bb4a`. Both external commits and PR132 history are retained.

## Preservation and repairs

Independent inventories found the same 335 Python test files before and after the relocation. All 644 test functions and 1,433 assertions in the 68 moved Python test files were preserved; the moved DOM test body is unchanged. Both merge conflicts retained the prior regression assertions and corrected imports for the new directories.

Review repaired six references to moved research notes and made the bounded publication measurement select its fixture from either layout within the explicitly selected checkout. An escaping symlink is rejected; another checkout cannot supply a missing fixture. Research note admission occurs before population work.

The first full local production-offline run exercised 9,459 cases: 9,457 passed, 38 subtests passed and 50 loopback cases were excluded. Two relocation regressions failed: the source archive omitted the newly colocated development helpers, and one workflow test expected four roots after the inventory expanded to sixteen. The archive now includes its development assets and verifies its helper tests without importing application code; the workflow assertion derives the expected fixture count from the declared roots. These failures are retained in the evidence rather than presented as a passing full run.

## Qualification

Focused verification passed 59 measurement tests, 87 package/archive tests and three workflow tests. The final source-archive-only check passed after removing a redundant manifest entry. These cover the selected-checkout fixture, note defaults, extracted source archive, self-contained wheel, and actual offline workflow test execution. Independent reviews bind exact changed-file hashes. The evidence index records their commands, results and retained log hashes.

The full suite ran before the narrow fixes finished and is not claimed as an unchanged-final-tree pass. Targeted reruns qualify the repaired paths. No held-out classification, source acquisition, hosted publication or workflow dispatch was performed. No speed improvement is inferred from test-run timing.

The practical improvement is one discoverable home for each test, with the original test coverage and reproducible development archives retained. Remaining efficiency tickets resume from the merged baseline.
