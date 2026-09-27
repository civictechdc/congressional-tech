#!/usr/bin/env bash
# Replace the pipeline-data branch with a single snapshot commit of ./pipeline-data,
# so raw caches never accumulate history. Usage: save-pipeline-data.sh "<what changed>"
set -euo pipefail
cd pipeline-data
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git checkout -q --orphan snapshot
git add -A
git commit -q -m "Pipeline data snapshot: $1 ($(date -u +%Y-%m-%d))"
git push -q -f origin snapshot:pipeline-data
