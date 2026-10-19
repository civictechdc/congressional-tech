# Bounded recovery mapping publication (ct-2uwd)

Mapping publication now shares the maintained complete-document reader in
`congress_api.retention.control_documents` with the viewer publisher. The viewer
publisher re-exports the same function and limits object. The reader's function
AST and its 4/16/32 MiB manifest/accepted/recovery limits are unchanged. This
removes a policy copy while applying the accepted mapping's 16 MiB limit to both
fresh mapping reads and independently verified write readbacks. Declared oversize,
streamed overrun, truncation, invalid JSON, invalid document shape/version and
missing object version fail before publication; proposed bytes must also fit.

An issuing client's exact key/body/current-version receipt still avoids a second
mapping-layer readback. Missing, foreign, stale or differently bound receipts now
trigger one independent bounded byte comparison. The guarded client retains its
own failure reconciliation. Plain clients send one conditional PUT and reuse a
successful lost-acknowledgment readback rather than downloading it again. If the
PUT and reconciliation both fail, the raised error retains both exception objects
and reports their types without formatting transport messages into its own text.

A local comparison against `6ce85eb629a63a48c18475d3f711e45526ac7526` used a
32-byte initial mapping, an 87-byte proposal, and one reused 16 MiB+1 overrun
fixture. Counts include the initial mapping GET:

| Path | Before | After |
| --- | --- | --- |
| Plain successful PUT | 2 full GETs, 1 PUT, 119 body bytes | Same |
| Plain lost acknowledgment | 3 full GETs, 1 PUT, 206 body bytes | 2 full GETs, 1 PUT, 119 body bytes |
| Valid guarded receipt | 2 full GETs, 1 HEAD, 1 PUT | Same |
| Unusable guarded receipt, exact remote bytes | Refusal after 2 GETs | Verified after 3 GETs; still 1 PUT |
| Declared 16 MiB+1 | 16,777,217 body bytes consumed before refusal | Zero body bytes consumed |
| Streamed 16 MiB+1 | 16,777,217 body bytes consumed | Same cap, bounded requests of at most 64 KiB |
| PUT and reconciliation both fail | Read error replaces PUT error | Both exception objects retained |

Successful plain, lost-ack and valid-receipt results and retained before/proposed
SHA-256 values match exactly. Every write uses the original ETag. Existing merge
regressions preserve fresh edits/deletions and reject conflicting additions. New
tests use the real guarded client to check issuing identity, exact binding and
current version, and prove a guarded reconciliation failure causes no outer GET
or second PUT. Publisher tests verify the shared policy remains monkeypatchable.

Evidence lives in `output/efficiency-debt-20261019/mappings/` in the primary
checkout: `compare.py`, `comparison.json`, `tests.log` and `receipt.json`. These
are injected-client local tests, not S3 or concurrency qualification. The valid
guarded path was already efficient at this baseline. The overrun fixture proves
a byte ceiling, not a reduction for every malformed input, a total heap ceiling
or a speed improvement. Complete admitted documents still remain in memory.
