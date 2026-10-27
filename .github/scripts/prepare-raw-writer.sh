#!/usr/bin/env bash
# Build an isolated application checkout; reports and inventory stay with the caller.
set -euo pipefail
source_root=$(git -C "$1" rev-parse --show-toplevel)
writer_root=$2
revision=$3
if ! [[ "$writer_root" = /* && "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'Raw writer needs an absolute destination and exact application commit' >&2
  exit 1
fi
case "$writer_root/" in
  "$source_root/"*) echo 'Raw writer checkout must be outside the working application tree' >&2; exit 1 ;;
esac
git -C "$source_root" cat-file -e "$revision^{commit}"
if [[ -e "$writer_root" ]]; then
  echo 'Raw writer checkout requires a fresh destination' >&2
  exit 1
fi
git clone --quiet --local --no-hardlinks --no-checkout "$source_root" "$writer_root"
git -C "$writer_root" checkout --quiet --detach "$revision"
uv sync --locked --project "$writer_root"
test "$(git -C "$writer_root" rev-parse HEAD)" = "$revision"
test -z "$(git -C "$writer_root" status --porcelain)"
