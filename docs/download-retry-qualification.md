# Download cleanup: local verification

The three changes in [the audit](download-retry-audit.md) are merged. They reduce
maintenance duplication while preserving source-specific behavior and data.

| Change | Result | Merge |
| --- | --- | --- |
| Congress.gov downloader | Both collectors use the transport owner; existing meeting imports remain available. | [#122](https://github.com/civictechdc/congressional-tech/pull/122), `edc93c69480342e3ae98d029a909115b4862bc7b` |
| Senate recording URLs | Audio and captions use one live-first/archive candidate builder. Validation, fallback and evidence remain with each caller. | [#123](https://github.com/civictechdc/congressional-tech/pull/123), `9253cbd922ab966eb5a1e9613d32648e3171da8a` |
| Object-storage downloads | Three synchronous body retry loops use one private runner. Each reader retains its version, absence, bounds and file rules. | [#124](https://github.com/civictechdc/congressional-tech/pull/124), `54b812ceb3080d99bf0515d01557057afc2ac54b` |

The audit and dependency graph were merged in
[#121](https://github.com/civictechdc/congressional-tech/pull/121). The six tickets
are `ct-yxup`, `ct-xh2t`, `ct-677t`, `ct-84x7`, `ct-kpuy` and parent `ct-8w0g`.
The three implementations depended on the completed audit; final verification
depended on all three implementations.

## Evidence

Independent reviews approved each implementation and integrated revision
`f18352c81de4dc0787a5296c0de623557f08b22c`. All 11 implementation source, test and
README files matched their reviewed versions exactly. The merged code at
`54b812ceb3080d99bf0515d01557057afc2ac54b` matches that tested code; ticket history
differs because the work was squash merged.

| Local check | Result |
| --- | --- |
| Congress.gov collectors, HTTP policies and import boundaries | 125 passed |
| Senate audio/caption ordering, caches, retained evidence and boundaries | 101 passed; 14 subtests passed |
| Storage stream failures, files, catalogs and boundaries | 177 passed |
| New storage behavior cases against the original implementation | 33 passed |
| Combined `production-offline` suite | 9,379 passed; 38 subtests passed; 252.35 seconds |

The focused counts overlap and must not be added together. The combined command
was `.venv/bin/python scripts/dev.py test production-offline`. It deselected 50
loopback tests and emitted five existing dependency syntax warnings. Native
source-fetch code was unchanged. The offline runner blocks Python sockets;
spawned processes are not independently network-isolated.

The storage checks cover interrupted partial bodies, response closure before
backoff, exhausted/disabled budgets, unchanged log fields, SDK failures outside
body retries, initial versus version-pinned absence, and index write authority
only after complete closure and length validation. All 33 new cases also passed
against baseline `eff81c4ea5ee43ac20a7b477340cc0a3ab0d53bd`.

## Practical effect and limits

Future fixes to these shared mechanics have one owner. Retry counts, delays,
timeouts, source validation, byte limits, provider fallback and stored formats
remain unchanged. Async storage and provider-specific transports remain separate.
No new source documents were acquired, source data migrated, classification run,
or production limits changed. Local tests and review were the requested merge
gate; CI was not used as a completion gate. This work makes no measured speed,
bandwidth, deployment or hosted qualification claim.

Machine-readable reviews, logs, baseline provenance and the final merge/cleanup
receipt are retained in the primary checkout under
`output/download-retry-cleanup-20261019/`. The completion receipt records the final
ticket counts and worktree cleanup after this evidence change is integrated.
