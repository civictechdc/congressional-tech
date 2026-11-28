# Install congressional search

On the private Linux search host, install the producer from its checkout or
Git archive using `sh deploy/spicyengine/install.sh <full-commit>`. Install
the SpicyEngine wheel with its Linux deployment installer. The two installers
can be run again. `install.sh` preserves any existing `/etc/spicyengine/search.env`
overrides (appending only missing default keys) and installs the read-only
`/usr/local/sbin/spicyengine-healthcheck` script plus its optional 15-minute
`spicyengine-healthcheck.timer` unit (`sudo systemctl enable --now spicyengine-healthcheck.timer`).
They use the same read-only serving mount and retain the database volume. The
host profile keeps the search runtime uncapped.

Run `sudo spicyengine-update` to install the current release. The command reads
the archive and text pointers, requires the same release and detail-file pin,
and saves the immutable inputs in `pin.json`. It prepares visible documents
once, then publishes the complete snapshot privately. New releases include the publisher
listing and page-addressable PDF URL in each prepared row. A completed search-v1
release reuses its original shards, index and link file. A rerun skips completed
preparation and indexing. To replay an earlier release, run
`sudo spicyengine-update --pin /path/to/pin.json`. Copy that small file off
the host to reproduce the selection after an upstream pointer change.

After the first successful publication, enable regular updates with
`sudo systemctl enable --now spicyengine-update.timer`. The timer checks every
minute with `--prefer-staged` using the same publisher and release lock, so it
prepares and indexes a staged candidate release ahead of the live
`viewer-publications/manifest.json` flip (and falls back to the live pointers
otherwise). If the archive and text pointers disagree, the current index stays
online and the next run retries. When live SpicyEngine has attached passage
embeddings, `spicyengine-update` refuses a bare publish that would drop them
unless you supply `--passages-manifest /path/to/manifest.json` (which validates
the manifest against the target release before publishing and attaches passages
with the new `config_version`) or explicitly pass `--allow-drop-passages`.
When live SpicyEngine also indexes `keyword_parquet` or uses `layout="unified"`,
`spicyengine-update` refuses to attach a vector-only manifest unless you pass
`--ensure-keywords` (which builds and verifies the sibling `keywords/` directory
before publishing, hard-linking unchanged shards from the live keyword directory
or `--previous-keywords /path/to/keywords` and writing `keyword_parquet` into
`passages-attach.json`), `--unified-passages` (which builds and verifies a
single combined text + `float16` vector dataset in sibling `unified/` with
`layout="unified"`, reusing unchanged shards from `--previous-unified` or the
live unified directory), or explicitly pass `--allow-drop-passage-keywords`.
After `attach-passages`, `spicyengine-update` inspects `/proc/meminfo` and logs
a structured stderr warning if swap usage exceeds `--swap-warn-gib` (default
`2.0` GiB); pass `--recycle-db-if-swapped` (requires root/systemctl privileges)
to restart `spicyengine-db.service` and `spicyengine.service` automatically when
swap exceeds that threshold.
The passage builder can also be run standalone via
`python -m viewer_publication.passage_keywords --serving <dir> --prepared <dir> --output <dir> --release-id <sha>`
(add `--build-unified --dimensions 512` for unified Parquet or `--stamp-manifest`
to verify an existing `keywords/` directory and seed `manifest.json` in place).
Inspect the latest attempt with `journalctl -u spicyengine-update.service`.
Stop the timer before deliberately holding the host on an earlier pin.
An exact release match is required for Congress Explorer’s hosted search tools.

Search filters use the most recent formal name in the release's committee directory,
or the directory's display name where it has no name history. Earlier names are
searchable and selections keep their original committee IDs. The first update of
an existing release reads only its committee ID column and the pinned directory.

The search filters and archive viewer share the document classification vocabulary in
`packages/congress_shared/src/congress_shared/data/document-classifications.json`.
The search release publishes its display names and definitions as filter metadata.

Pass `--source-dir /absolute/path` to reuse matching local `detail.parquet`,
`sources.parquet`, `committees.parquet` or `body_text.parquet`. The producer verifies supplied files
in place. It verifies downloads while writing and releases its own download
copies after the prepared output commits. Keep the previous and current
release files while their native indexes reference them. The command changes
neither public routing nor the upstream publication.
