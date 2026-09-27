#!/usr/bin/env bash
# Commit the given files to the checked-out branch and push, rebasing if another
# job pushed first. Usage: commit-and-push.sh "<message>" <file>...
set -euo pipefail
message="$1"; shift
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add "$@"
if git diff --cached --quiet; then
  echo "No changes"
  exit 0
fi
git commit -q -m "$message"
branch="$(git rev-parse --abbrev-ref HEAD)"
for attempt in 1 2 3; do
  git push -q origin "HEAD:$branch" && exit 0
  echo "push rejected (attempt $attempt) -- rebasing on origin/$branch"
  git pull -q --rebase origin "$branch"
done
exit 1
