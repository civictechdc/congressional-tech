#!/usr/bin/env bash
set -euo pipefail

server_root="$(mktemp -d "$RUNNER_TEMP/filename-worker-site.XXXXXX")"
ln -s "$GITHUB_WORKSPACE/apps/site/dist" "$server_root/congressional-tech"
python -m http.server 4173 --bind 127.0.0.1 --directory "$server_root" > "$RUNNER_TEMP/filename-worker-server.log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
pages_url="http://127.0.0.1:4173/congressional-tech/dashboard/"
curl --silent --show-error --fail --retry 10 --retry-connrefused --retry-delay 1 --max-time 5 "$pages_url" > /dev/null
node apps/site/scripts/verify-live-publication.mjs \
  --viewer-url https://congressional-data.spicygov.ai/viewer-publications/manifest.json \
  --pages-url "$pages_url" \
  --review-descriptor apps/site/document-review-publication.json \
  --require-native-worker true \
  --output "$RUNNER_TEMP/filename-worker-built.json"
