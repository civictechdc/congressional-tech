# Accepted viewer inventory and recovery status

Local implementation evidence, 2026-10-18. No remote publication ran.

The builder's existing per-file SHA-256 descriptions now return issued file proofs beside the public manifest. ID shards receive the same exact hash proof. Preparation combines these proofs with the accepted recovery-status bytes and its final canonical manifest; it does not rehash the payload at phase acceptance or its immediate verification. These are Python object attributes, absent from JSON and artifact restoration.

A fresh artifact verification hashes every inventory member once, including all 256 ID shards and the accepted status. Structural manifest/path/size checks, phase-state comparison, recovery indexing and downstream upload reuse that one issued proof while exact local custody, selected inputs and validator/runtime identity remain unchanged. Guarded upload and restored-write replay accept only issued local file objects. Remote byte readback remains independent, and a plain SDK client still uses full downloaded-object verification. Inventory proof cannot be supplied as a plain JSON dictionary, copied object or inherited process registry. A changed file, validator source/code, process or input binding refuses reuse. `RecoveryGuard` similarly retains its initial pin hash across phase seams only while device/inode/size/mtime/ctime remain unchanged; cloud and mutable selector checks remain fresh.

Recovery-only preparation computes the complete status once, pins its original source manifest, filename/group file descriptors, catalog row/entry identity, accepted-mapping presence and raw digest, and includes the resulting bytes in the artifact inventory. It removes only its owned temporary filename/group downloads after successful computation. Publication verifies that accepted status and current mappings; it performs no second index scan. Full preparation accepts status in the same way while retaining its payload files. Ordinary new mapping preparation remains supported. Conditional viewer selection and public proof remain required.

Hash budget:

- Build custody: each payload's required manifest/inventory digest once; final canonical manifest and accepted status each hash once. Rewriting the small manifest into the canonical publication encoding intentionally requires its new digest.
- Restored artifact custody: one full SHA-256 pass per inventory member. Same-process structural, phase, recovery and guarded transfer handoffs perform zero additional full payload SHA passes.
- Transport verification: remote full byte SHA verification remains required. Plain clients retain their separate downloaded-object readback. Resume uses fresh remote reconciliation, and local exact-file proof avoids hashing local payloads again during replay.

Tests count one hash call for every restored inventory member and no added calls across same-process verifier/manifest handoffs; copied and serialized proofs refuse. Tests forbid `index_recoveries` during full publication and recovery publication/resume, including runner loss after pointer selection. Mapping changes refuse before public/journal writes. Fresh phase acceptance now checks count/path limits before storing a checkpoint; a rejected phase leaves prior state unchanged.

The combined publication, journal, guard, recovery and workflow suites passed 116 tests and two subtests. A final 40-test run covers the new process binding, provenance revision and reference/file proof paths. Work counts come from bounded fixtures; these results do not establish production cost or qualification.

Custody assumption: files moved or linked by the preparation owner have no concurrent writer. The narrow owned move/link operations rebind change time after checking inode, size and modification time. These checks do not exclude an adversarial concurrent same-size write that restores modification time inside that handoff. All ordinary later mutations invalidate proof reuse; independent custody restoration rehashes complete bytes.
