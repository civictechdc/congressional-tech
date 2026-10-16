# Finish corpus document recovery

Goal: make genuinely missing documents accessible in the viewer and give remaining URLs an evidence-backed disposition. Preserve existing files, source relationships, and failure evidence. A filename, HTTP 200, or stored response alone does not prove recovery.

## Verified checkpoint

The accompanying `../recovery/corpus-recovery-checkpoint-20261016.json` records the snapshot time, counts, and local evidence hashes. These counts describe local preparation, not publication:

- 184 recovered URL links reference 137 distinct validated file bodies.
- 15 retained ZIPs yielded 149 distinct validated PDFs, with prepared parent/member receipts. No ZIP redownload was needed.
- The combined preview adds 5,924 URL mappings while preserving all 14,505 previous mappings.
- Document groups without a saved copy fall from 311 to 277 in the preview. The 149 ZIP members are not yet included in that reduction.
- The separately deferred 164 files remain excluded.

The first direct NARA session processed 35 of 776 entries: 33 validated links, one unsuccessful entry, and one rate-limited entry. It stopped on HTTP 429. The new continuation includes 741 untouched entries plus the rate-limited entry, preserves the original run, reuses successful digests, and waits 15 seconds between requests. Its live status is `output/corpus-retry-20261015/nara-direct-resume/status.json`.

One Zyte HTTP proxy request returned a rate-limit page. Actual billed cost is not yet known; the pass has a $25 total cap and a $0.02 conservative reservation for that request. Current acquisition uses direct Web Harvest access, with no active paid route.

## Remaining work and completion evidence

1. Finish targeted acquisition. Reuse completed indexes and valid files before requesting anything. Finish the direct NARA queue; stop on rate limits, access checks, or repeated transport failures. Preserve those outcomes as unfinished, not absent. Retry the eight incomplete Wayback index partitions within the existing bounded retry policy; keep complete partitions. Check official package and retained-body routes before paid fallback. Record each outstanding URL's next route or reason to stop.
2. Combine recovery evidence. Merge newly validated bodies and URL associations, verify full hashes, deduplicate bodies without losing URLs, and regenerate the preview. Validate every ZIP member's parent association. Preserve prior mappings and exclude the 164 deferred files. Report unique URLs, unique bodies, and missing document groups separately.
3. Wait for the existing cloud writer. Run 38823678887 was active at the checkpoint. Do not cancel it or publish over its inputs. Before any shared write, verify all cloud capture writers are clear, acquire the existing local recovery lock, and read fresh raw index versions, selected catalog, and accepted mappings. Rebase preparation if they changed.
4. Import and publish. Use maintained import/publication functions, retain original ZIP parent/member context, and preserve raw download state where required. Upload only absent verified bodies. Use conditional updates and reconcile uncertain acknowledgments before retrying. Do not select an older catalog or overwrite another writer's mappings.
5. Verify the user-visible outcome. Read back the selected generation and paired catalog hashes, verify all new URL mappings reference retained bodies, and check representative PDFs through the public viewer, including ZIP members, official bill aliases, and archive recoveries. Publish final counts and remaining dispositions with the exact snapshot time.

Completion requires successful publication and readback, not just this plan, a running downloader, or a local preview. Blocked routes do not establish archive exhaustion or corpus completeness. No video bytes are in scope. Commit only this recovery checkpoint and plan; existing unrelated workspace changes remain separate.
