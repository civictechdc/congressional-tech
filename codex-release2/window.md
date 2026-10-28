# Lead runtime, main and data switch window

Status: waiting for the qualified combined engine pin and final full-run proof. The forward block stops at its readiness guard until release fills every pin and marks it ready.

Only the lead executes these outward commands. B0 receipt rewriting and R2 bucket locks remain deferred to a supervised owner window; this block runs neither. The artifact is an ordinary `linux-amd64` build from `@SOURCE_REVISION@`: @BINARY_BYTES@ bytes, SHA-256 `@LINUX_SHA256@`. It passed @LINUX_TEST_COUNT@ project-runner checks inside amd64 Python 3.12.13, including real native model/group/export and runtime setup. The immutable packet includes the exact descriptor, rollback descriptor, cross recipe and qualification evidence.

Current variable readback is the previous `c949c6762f001845d2933e55cb9d7cf237e80810` runtime: 220,185,776 bytes, SHA-256 `c14bfbd12b6ad958e9fa8cd8d2bc57feb014ef12431a9826ec078c631fdafd33`, bucket `congressional-tech-runtime`. Its complete JSON is in `rollback-runtime-artifact.json` in the packet. The application pin and variable must change together. Keep publishing, capture and Pages workflows paused during the window. Disabling a workflow preserves running jobs; the drain check below stops until every existing job finishes. Keep them paused through hosted validation and use engine's switch checklist to activate the new pipeline and deploy after the pointer flip. A hosted check queued before the variable changes may need a rerun afterwards.

B15 must already be on main before recording the rollback application commit. That preserves raw-before-push behavior even if the integration landing is rolled back. All Git operations below use the landing worktree, never the pinned rescue worktree.

## Forward: upload, merge landing, set variable

```sh
set +x
set -euo pipefail
WINDOW_READY=0
test "$WINDOW_READY" -eq 1
export REPO=civictechdc/congressional-tech
export CLOUDFLARE_ACCOUNT_ID=174055408ff1560e60601c4d12c561c4
export LANDING=/Users/mikewolfd/Work/wt/ct-landing-engine-first-20261028
export CI=/Users/mikewolfd/Work/wt/ct-release2-ci
export RUNTIME_PACKET=/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-coord/shared/@RUNTIME_PACKET_NAME@
export WINDOW=/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-release2/lead-window
mkdir "$WINDOW"

# gh returns the newly created run URL. Use its ID, never a previous run's ID.
dispatch_and_watch() {
  local workflow="$1"; shift
  local stem="${workflow%.yml}" run_id
  test "$(gh api "repos/$REPO/git/ref/heads/main" --jq .object.sha)" = "$LANDED_APPLICATION"
  gh workflow run "$workflow" --ref main --repo "$REPO" "$@" \
    | tee "$WINDOW/dispatch-$stem.txt"
  run_id=$(sed -nE 's@.*https://github\.com/civictechdc/congressional-tech/actions/runs/([0-9]+).*@\1@p' \
    "$WINDOW/dispatch-$stem.txt")
  case "$run_id" in
    ''|*[!0-9]*)
      gh run list --all --workflow "$workflow" --repo "$REPO" --commit "$LANDED_APPLICATION" \
        --event workflow_dispatch --limit 5 --json databaseId,createdAt,status,url
      return 1 ;;
  esac
  gh run view "$run_id" --repo "$REPO" --json headSha,event \
    > "$WINDOW/run-$stem-identity.json"
  test "$(jq -r .headSha "$WINDOW/run-$stem-identity.json")" = "$LANDED_APPLICATION"
  test "$(jq -r .event "$WINDOW/run-$stem-identity.json")" = workflow_dispatch
  printf '%s\n' "$run_id" > "$WINDOW/run-$stem-id.txt"
  gh run watch "$run_id" --exit-status --repo "$REPO"
  gh run view "$run_id" --repo "$REPO" --json conclusion > "$WINDOW/run-$stem-result.json"
  test "$(jq -r .conclusion "$WINDOW/run-$stem-result.json")" = success
}

# Lead only: refresh the target before its local merge; release never fetched.
git -C "$LANDING" fetch origin main
test -z "$(git -C "$LANDING" status --porcelain)"
QUALIFIED_LANDING=@LANDING_COMMIT@
git -C "$LANDING" merge-base --is-ancestor "$QUALIFIED_LANDING" HEAD
# Only the final handoff notes and this ticket closure may follow the tested code.
git -C "$LANDING" diff --quiet "$QUALIFIED_LANDING" HEAD -- . \
  ':(exclude)codex-release2/window.md' \
  ':(exclude)codex-release2/final-report.md' ':(exclude).tickets/clef2-7kpa.md'
PREVIOUS_APPLICATION=$(git -C "$LANDING" rev-parse origin/main)
git -C "$LANDING" merge-base --is-ancestor 5f9c4657 "$PREVIOUS_APPLICATION"
printf '%s\n' "$PREVIOUS_APPLICATION" > "$WINDOW/previous-application-commit.txt"
gh variable get DOCSPEC_RUNTIME_ARTIFACT --repo "$REPO" > "$WINDOW/previous-runtime-artifact.json"
jq -S . "$WINDOW/previous-runtime-artifact.json" > "$WINDOW/previous-canonical.json"
jq -S . "$RUNTIME_PACKET/rollback-runtime-artifact.json" > "$WINDOW/expected-canonical.json"
cmp "$WINDOW/previous-canonical.json" "$WINDOW/expected-canonical.json"
gh variable list --repo "$REPO" --json name > "$WINDOW/previous-variable-names.json"
ACCOUNT_PRESENT=$(jq -r 'any(.[]; .name == "CLOUDFLARE_ACCOUNT_ID")' "$WINDOW/previous-variable-names.json")
case "$ACCOUNT_PRESENT" in
  true) gh variable get CLOUDFLARE_ACCOUNT_ID --repo "$REPO" > "$WINDOW/previous-account-id.txt" ;;
  false) : > "$WINDOW/previous-account-id.txt" ;;
  *) exit 1 ;;
esac
printf '%s\n' "$ACCOUNT_PRESENT" > "$WINDOW/previous-account-present.txt"

# Pause the pre-existing outward workflows and retain their exact prior state.
gh workflow list --all --repo "$REPO" --json id,path,state > "$WINDOW/workflows-before.json"
jq '[.[] | select(.path == ".github/workflows/deploy-pages.yml" or
  .path == ".github/workflows/publish-explorer.yml" or
  .path == ".github/workflows/publish-filename-viewer.yml" or
  .path == ".github/workflows/update-data.yml" or
  .path == ".github/workflows/capture-raw-sources.yml")]' \
  "$WINDOW/workflows-before.json" > "$WINDOW/managed-workflows-before.json"
test "$(jq length "$WINDOW/managed-workflows-before.json")" -eq 5
jq -e 'all(.[]; (.id | type == "number") and (.state | type == "string"))' \
  "$WINDOW/managed-workflows-before.json" > /dev/null
jq -r '.[] | select(.state == "active") | .id' \
  "$WINDOW/managed-workflows-before.json" > "$WINDOW/previously-active-workflows.txt"
while IFS= read -r workflow_id; do
  gh workflow disable "$workflow_id" --repo "$REPO"
done < "$WINDOW/previously-active-workflows.txt"
jq -r '.[].id' "$WINDOW/managed-workflows-before.json" > "$WINDOW/managed-workflow-ids.txt"
# Stop before uploading/merging if any acquisition, publisher or deployment is live.
# Never automatically cancel a job that may hold newly acquired data.
while IFS= read -r workflow_id; do
  for state in queued in_progress requested waiting pending; do
    gh run list --all --workflow "$workflow_id" --repo "$REPO" --status "$state" --limit 1 \
      --json databaseId,status,url > "$WINDOW/drain-$workflow_id-$state.json"
    test "$(jq length "$WINDOW/drain-$workflow_id-$state.json")" -eq 0
  done
done < "$WINDOW/managed-workflow-ids.txt"

# 1. Private binary upload is create-only and verifies complete readback.
cd "$CI"
.venv/bin/python -I -m viewer_publication.publish_docspec_runtime \
  --upload --bucket congressional-tech-runtime --binary "$RUNTIME_PACKET/docspec" \
  --source-revision @SOURCE_REVISION@ --platform linux-amd64 \
  --output "$WINDOW/uploaded-runtime-artifact.json"
jq -S . "$WINDOW/uploaded-runtime-artifact.json" > "$WINDOW/uploaded-canonical.json"
jq -S . "$RUNTIME_PACKET/runtime-artifact.json" > "$WINDOW/approved-canonical.json"
cmp "$WINDOW/uploaded-canonical.json" "$WINDOW/approved-canonical.json"

# 2. Merge latest main ancestry without changing the qualified landing tree.
QUALIFIED_TREE=$(git -C "$LANDING" rev-parse HEAD^{tree})
git -C "$LANDING" merge --no-edit origin/main
# Stop on a conflict or a real tree change; release must resolve/recheck it.
test "$(git -C "$LANDING" rev-parse HEAD^{tree})" = "$QUALIFIED_TREE"
git -C "$LANDING" push origin HEAD:refs/heads/main
LANDED_APPLICATION=$(git -C "$LANDING" rev-parse HEAD)
printf '%s\n' "$LANDED_APPLICATION" > "$WINDOW/landed-application-commit.txt"

# 3. Set the exact approved descriptor after the landing, in this same window.
gh variable set DOCSPEC_RUNTIME_ARTIFACT --repo "$REPO" \
  --body "$(cat "$WINDOW/uploaded-runtime-artifact.json")"
gh variable set CLOUDFLARE_ACCOUNT_ID --repo "$REPO" --body 174055408ff1560e60601c4d12c561c4
gh variable get CLOUDFLARE_ACCOUNT_ID --repo "$REPO" > "$WINDOW/account-readback.txt"
test "$(cat "$WINDOW/account-readback.txt")" = 174055408ff1560e60601c4d12c561c4
gh variable get DOCSPEC_RUNTIME_ARTIFACT --repo "$REPO" > "$WINDOW/runtime-readback.json"
jq -S . "$WINDOW/runtime-readback.json" > "$WINDOW/readback-canonical.json"
cmp "$WINDOW/readback-canonical.json" "$WINDOW/approved-canonical.json"
# New schedules also remain paused until their operator bindings/switch are ready.
gh workflow disable capture-archive.yml --repo "$REPO"
gh workflow disable archive-jobs.yml --repo "$REPO"
```

The push is normal and fast-forward only; it never forces main. If main changed in a way that changes the landing tree, the command stops before pushing. If protection rejects the push, stop and use the lead's approved merge method; do not force or bypass protection. No data upload, public pointer flip, capture activation or legacy deletion is part of this block.

## Hosted validation, controller, then Pages

Keep the same shell so `dispatch_and_watch`, `WINDOW`, `REPO` and `LANDED_APPLICATION` stay defined. Engine must announce accepted full D1/model/E4 and the committed publish binding before the controller step. The switch checklist is `docs/plans/engine-first-switch.md`; its accepted release/pins and selective workflow restoration govern this phase.

```sh
# 3. A real hosted green check follows the coherent application/runtime pair.
dispatch_and_watch validate-explorer.yml

# 4. Confirm the committed publisher binding without opening runtime credentials.
cd "$LANDING"
.venv/bin/python -I .github/scripts/run-archive-job.py publish --check-binding
# From this point, use engine's data-aware rollback if publication is attempted.
touch "$WINDOW/data-activation-started"
gh workflow enable archive-jobs.yml --repo "$REPO"
dispatch_and_watch archive-jobs.yml --raw-field operation=publish
PUBLISH_RUN_ID=$(cat "$WINDOW/run-archive-jobs-id.txt")
test "$(gh run view "$PUBLISH_RUN_ID" --repo "$REPO" --json jobs \
  --jq '.jobs[] | select(.name == "publish") | .conclusion')" = success

# 5. The controller's successful contract/canary/CAS precedes the new interface.
gh api "repos/$REPO/git/ref/heads/pipeline-data" --jq .object.sha > "$WINDOW/pipeline-revision.txt"
PIPELINE_REVISION=$(cat "$WINDOW/pipeline-revision.txt")
gh workflow enable deploy-pages.yml --repo "$REPO"
dispatch_and_watch deploy-pages.yml --raw-field code_revision="$LANDED_APPLICATION" \
  --raw-field pipeline_revision="$PIPELINE_REVISION"

# Keep the old raw capture and retired filename publisher off.
# Restore the meeting inventory and remaining workflows only per the switch plan.
gh workflow enable update-data.yml --repo "$REPO"
```

The first hosted check verifies private download credentials and Ubuntu execution; local Linux checks do not claim that boundary. If `gh workflow run` does not return the new run URL, the function stops and lists matching runs. Select the just-dispatched run using its URL/creation time, record its ID in the corresponding `run-*-id.txt`, verify its exact head and watch it; do not dispatch a duplicate controller job. Keep old capture and the retired filename publisher disabled. The meeting inventory stays enabled after the switch; other workflow states follow engine's switch checklist.

## Paired rollback: variable and previous application tree

Use only before any public pointer flip or data activation, keeping workflows paused. After a flip, engine's data/application rollback is required; this runtime/application block alone cannot restore pointer compatibility. This restores the saved application tree in a new forward commit, preserves the pre-window B15 repair, and does not rewrite Git history or delete any raw object.

```sh
set +x
set -euo pipefail
PREVIOUS_APPLICATION=$(cat "$WINDOW/previous-application-commit.txt")
LANDED_APPLICATION=$(cat "$WINDOW/landed-application-commit.txt")
test ! -e "$WINDOW/data-activation-started"
test -z "$(git -C "$LANDING" status --porcelain)"
git -C "$LANDING" fetch origin main
test "$(git -C "$LANDING" rev-parse origin/main)" = "$LANDED_APPLICATION"
gh variable set DOCSPEC_RUNTIME_ARTIFACT --repo "$REPO" \
  --body "$(cat "$WINDOW/previous-runtime-artifact.json")"
case "$(cat "$WINDOW/previous-account-present.txt")" in
  true) gh variable set CLOUDFLARE_ACCOUNT_ID --repo "$REPO" --body "$(cat "$WINDOW/previous-account-id.txt")" ;;
  false) gh variable delete CLOUDFLARE_ACCOUNT_ID --repo "$REPO" ;;
  *) exit 1 ;;
esac
git -C "$LANDING" switch -c rollback/engine-first-20261028 "$LANDED_APPLICATION"
git -C "$LANDING" restore --source="$PREVIOUS_APPLICATION" --staged --worktree -- .
git -C "$LANDING" commit -m 'Restore the previous application with its qualified runtime' \
  -m 'Roll back the integration landing as one forward commit; preserve the pre-window B15 raw safety repair and leave all stored data intact.'
git -C "$LANDING" push origin HEAD:refs/heads/main
gh variable get DOCSPEC_RUNTIME_ARTIFACT --repo "$REPO" > "$WINDOW/rollback-readback.json"
jq -S . "$WINDOW/rollback-readback.json" > "$WINDOW/rollback-canonical.json"
cmp "$WINDOW/rollback-canonical.json" "$WINDOW/previous-canonical.json"
# Only a coherent pre-switch rollback restores the prior enabled workflow set.
while IFS= read -r workflow_id; do
  gh workflow enable "$workflow_id" --repo "$REPO"
done < "$WINDOW/previously-active-workflows.txt"
```

Stop if another application commit has landed since the window; do not overwrite it. Retain both private runtime objects and all window evidence. The lead then verifies the previous application and restores its prior workflow state. A variable-only rollback is insufficient because the new application correctly rejects the old runtime pin.

If a drain or upload stops before the application push, keep the application and runtime variable unchanged. The saved drain JSON identifies the live run; let it finish, then repeat only the drain checks. To abandon that pre-push window, restore its recorded active workflow IDs with the final `while` loop above. A new archive workflow may take a few seconds to become visible after main advances; if either disable command reports that it is unavailable, keep the old workflows paused and repeat those two commands before proceeding. None of these commands cancels an acquisition job.
