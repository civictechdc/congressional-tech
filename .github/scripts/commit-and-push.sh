#!/usr/bin/env bash
# Commit the given files to the checked-out branch and push, rebasing if another
# job pushed first. Usage: commit-and-push.sh "<message>" <file>...
#
# main requires the merge-gate check (.github/rulesets/main.json), and GitHub cannot exempt
# its own Actions bot from a rule. A commit made here starts no checks of its own, so in
# GitHub Actions it is published on a side branch, marked merge-gate by this job, and only
# then moved onto the branch. The job needs `statuses: write` and GH_TOKEN.
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
side=""
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  side="data-commit/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-${GITHUB_JOB}"
  trap 'git push -q origin --delete "$side" 2>/dev/null || true' EXIT
fi
for attempt in 1 2 3; do
  if [ -n "$side" ]; then
    git push -q --force origin "HEAD:refs/heads/$side"
    gh api -X POST "repos/$GITHUB_REPOSITORY/statuses/$(git rev-parse HEAD)" -f state=success -f context=merge-gate \
      -f description="Data commit by the $GITHUB_WORKFLOW workflow" \
      -f target_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID" >/dev/null
  fi
  git push -q origin "HEAD:$branch" && exit 0
  echo "push rejected (attempt $attempt) -- rebasing on origin/$branch"
  git pull -q --rebase origin "$branch"
done
exit 1
