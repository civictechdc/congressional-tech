# Congress MCP 0.6.2 and indexed archive cutover

Deploy the compatible site before selecting an indexed public archive. The older
site refuses `search_index.sqlite` in a manifest, so a successful server release
alone cannot protect the shared archive's browser consumer.

This is an execution order and evidence checklist. It records no publication or
deployment completion. Keep the current public pointer and its ETag until the
candidate passes its required gates.

1. Freeze the combined software commit and the retained native/index candidate.
   Keep 0.6.2 as the next package version. Complete source conservation,
   caption/transcript reconciliation, supported-corpus dispositions, original
   passage checks, model invariants and independent reviews against these exact
   inputs. Reuse retained completed work only when its definitions and inputs
   still match. A successful fixture is bounded evidence.
2. Build the exact wheel, desktop extension, local/web plugin ZIPs and hosted
   image. Run the normal installed, desktop and HTTP checks using one retained
   probe plan. `--require-research` requires a readable caption, PDF/text page and
   indexed hit to reopen their exact citations. Record actual index, metadata,
   image, scratch and cache bytes, fresh-start time and process-tree RSS. Select
   hosted disk/memory/startup bounds from these measurements. The committed
   `basic`/90-second settings remain the previous baseline until deliberately
   changed and qualified.
3. Publish tag `congress-mcp-v0.6.2` from the reviewed software commit through
   `.github/workflows/publish-congress-mcp.yml`. Wait for the build, macOS/Linux
   install checks, PyPI publication, fresh PyPI install/desktop checks and GitHub
   release assets. The workflow's small archive fixture checks packaging; it does
   not establish full-corpus or hosted acceptance. Verify downloadable hashes and
   version metadata before the website advertises those files.
4. Push the reviewed main commit and wait for `deploy-pages.yml`. It builds from
   that exact main revision, uses the existing retained `pipeline-data` browser
   publication, and runs `verify-archive-contract.py`. The contract now attaches
   an actual SQLite FTS5 file, checks the shared release identity, and confirms
   zero browser index downloads. Observe the deployed site on the still-selected
   old archive; retain its page/software identity and successful list/detail read.
5. Publish the qualified indexed archive using the maintained native publication
   path. `archive-jobs.yml` publish is explicitly dispatched; a main push does not
   start it. Reuse the retained qualified candidate and its expensive index where
   the existing publication resume path admits that exact input. Preserve the
   normal browser contract, HTTPS canary and conditional `If-Match` pointer flip
   in `archive_publish.publish_candidate` / `archive_gate.gate_and_flip`. Read
   back the acknowledged pointer, its ETag and the immutable manifest. Confirm the
   deployed site selects this exact indexed release and leaves the index unfetched.
6. Bind the hosted image to that exact immutable manifest in `wrangler.jsonc`.
   Generate types, check the build, deploy with the existing account, and wait for
   the image rollout to become active. Container names include the publication
   URL, preventing an old-release process from serving under the new selection.
   Observe cold `/ready` and warm MCP calls with the measured capacity limits;
   a root service response does not prove data readiness.
7. Run strict same-release checks through the hosted endpoint, a fresh published
   PyPI install, and every desktop package configuration using the same probe
   plan. Verify the declared 18 tools, useful parser/binder/parameter diagnostics,
   read-only SQL, compact fields, dates, batch results, action/vote/ballot coverage,
   hearing inventory/dossier, cue/page reads and search citation resolution.
   Retain failures and unavailable populations separately. Reconcile the next
   daily catalog/version inputs, then prune only owned worktrees through
   `scripts/dev.py prune-worktree` after durable evidence survives outside them.

Keep `.cache/archive-release/mcp-research-20261106/release/` as the durable evidence
root. The old immutable release, source archive and retained rollback inputs remain
available. A rollback must restore compatible software and the selected manifest
together, then pass the same consumer checks.
