# Install congressional search

On the private Linux search host, install the producer from its checkout or
Git archive using `sh deploy/spicyengine/install.sh <full-commit>`. Install
the SpicyEngine wheel with its Linux deployment installer. The two installers
can be run again. They use the same read-only serving mount and retain the
database volume. The host profile keeps the search runtime uncapped.

Run `sudo spicyengine-update` to install the current release. The command reads
the archive and text pointers, requires the same release and detail-file pin,
and saves the immutable inputs in `pin.json`. It prepares visible documents
once, then publishes the complete snapshot privately. A rerun skips completed
preparation and indexing. To replay an earlier release, run
`sudo spicyengine-update --pin /path/to/pin.json`. Copy that small file off
the host to reproduce the selection after an upstream pointer change.

Pass `--source-dir /absolute/path` to reuse matching local `detail.parquet`,
`sources.parquet` or `body_text.parquet`. The producer verifies supplied files
in place. It verifies downloads while writing and releases its own download
copies after the prepared output commits. Keep the previous and current
release files while their native indexes reference them. The command changes
neither public routing nor the upstream publication.
