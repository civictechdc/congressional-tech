#!/usr/bin/env bash
# Commit the snapshot, preserve it in raw, then publish the pipeline-data ref.
# Reports, changed derived files and pipeline-data never enter the writer checkout.
set -euo pipefail
application_root=$(git rev-parse --show-toplevel)
application_revision=$(git -C "$application_root" rev-parse HEAD)
snapshot_root="$application_root/pipeline-data"
cd "$snapshot_root"
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git checkout -q --orphan snapshot
git add -A
git commit -q -m "Pipeline data snapshot: $1 ($(date -u +%Y-%m-%d))"
cd "$application_root"
writer_work=$(mktemp -d "$RUNNER_TEMP/pipeline-raw-writer.XXXXXX")
trap 'rm -rf "$writer_work"' EXIT
writer_root="$writer_work/application"
"$application_root/.github/scripts/prepare-raw-writer.sh" "$application_root" "$writer_root" "$application_revision"
"$writer_root/.venv/bin/python" -I -m congress_api.cli.pipeline_raw --snapshot "$snapshot_root"
git -C "$snapshot_root" push -q -f origin snapshot:pipeline-data
