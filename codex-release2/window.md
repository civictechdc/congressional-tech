# Lead runtime, main and data switch window

Status: runtime `885e8c3` is qualified locally. A remains blocked on the frozen landing’s full regression result and this checklist’s review. A covers runtime upload, main landing, variables and hosted validation. B remains separately blocked on acceptance of the full seed; A does not require that acceptance. Both blocks stop at their own readiness guards.

Only the lead executes these outward commands. B0 receipt rewriting and R2 bucket locks remain deferred to a supervised owner window; this block runs neither. The artifact is an ordinary `linux-amd64` build from `885e8c3c2a971a0c11b16ff9ca5a69e8ecb79c26`: 227161600 bytes, SHA-256 `bd337f62a9f98e23da834a04159d59b41860a14a718e91dc8728480cc1094edd`. Linux qualification evidence: 159 passed on application `553a8383`; the three affected cases passed on application `a27a3351` after the approved worker repair (3 passed in 157.29s). Initial failures and both source-specific logs remain in the packet; this does not claim all 163 tests passed on one source. The checks use amd64 Python 3.12.13 and real native model/group/export plus runtime setup. The unchanged 120-second bounded-metadata fanout assertion timed out under QEMU; it must pass on the hosted native amd64 runner. If it fails there, stop before data activation and use the paired rollback below; never raise its timeout. The immutable packet includes the exact descriptor, rollback descriptor, cross recipe and qualification evidence.

Current variable readback is the previous `c949c6762f001845d2933e55cb9d7cf237e80810` runtime: 220,185,776 bytes, SHA-256 `c14bfbd12b6ad958e9fa8cd8d2bc57feb014ef12431a9826ec078c631fdafd33`, bucket `congressional-tech-runtime`. Its complete JSON is in `rollback-runtime-artifact.json` in the packet. The application pin and variable must change together. Keep publishing, capture and Pages workflows paused during the window. Disabling a workflow preserves running jobs; the drain check below stops until every existing job finishes. Keep them paused after A and through B’s seed publication, then restore the old capture and update jobs after Pages succeeds. The new capture stays disabled until the raw rebuild passes its release checks. A hosted check queued before the variable changes may need a rerun afterwards.

B15 must already be on main before recording the rollback application commit. That preserves raw-before-push behavior even if the integration landing is rolled back. All Git operations below use the landing worktree, never the pinned rescue worktree.

The lead also confirms that no local v6 publisher or opaque wrapper is running.
The process gate covers the maintained CLI names; workflow pauses do not drain
local commands. Let each publisher's owner finish or stop it safely before this window.

## A: upload, land main, set variables, validate hosted

```sh
set +x
set -euo pipefail
WINDOW_A_READY=0
test "$WINDOW_A_READY" -eq 1
export REPO=civictechdc/congressional-tech
export CLOUDFLARE_ACCOUNT_ID=174055408ff1560e60601c4d12c561c4
export LANDING=/Users/mikewolfd/Work/wt/ct-landing-engine-first-20261028
export RUNTIME_PACKET=/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-coord/shared/linux-runtime-885e8c3
export WINDOW=/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-release2/lead-window
mkdir "$WINDOW"

# gh returns the newly created run URL. Use its ID, never a previous run's ID.
dispatch_and_watch() {
  local workflow="$1"; shift
  local stem="${workflow%.yml}" run_id baseline_validation=false
  if test "${1:-}" = --baseline-validation; then
    test "$workflow" = validate-explorer.yml
    baseline_validation=true
    shift
  fi
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
  if "$baseline_validation"; then
    # Wait for completion while preserving the run's visible red conclusion.
    gh run watch "$run_id" --repo "$REPO"
    gh run view "$run_id" --repo "$REPO" --json headSha,event,status,conclusion,jobs \
      > "$WINDOW/hosted-validation-run.json"
    gh run view "$run_id" --repo "$REPO" --log > "$WINDOW/hosted-validation.log"
    "$LANDING/.venv/bin/python" -I "$LANDING/.github/scripts/verify-hosted-baseline.py" \
      --run "$WINDOW/hosted-validation-run.json" --log "$WINDOW/hosted-validation.log" \
      --baseline "$LANDING/.github/ci-baseline-failures-20261027.json" \
      --expected-head "$LANDED_APPLICATION" --output "$WINDOW/hosted-baseline-comparison.json"
    return
  fi
  gh run watch "$run_id" --exit-status --repo "$REPO"
  gh run view "$run_id" --repo "$REPO" --json conclusion > "$WINDOW/run-$stem-result.json"
  test "$(jq -r .conclusion "$WINDOW/run-$stem-result.json")" = success
}

# Lead only: refresh the target before its local merge; release never fetched.
git -C "$LANDING" fetch origin main
test -z "$(git -C "$LANDING" status --porcelain)"
QUALIFIED_LANDING=32c25abe967be74f00f4868fd95456974fafa211
git -C "$LANDING" merge-base --is-ancestor "$QUALIFIED_LANDING" HEAD
# Only the final handoff notes, this ticket closure and the exact reviewed operator test blob may follow the tested application code.
git -C "$LANDING" diff --quiet "$QUALIFIED_LANDING" HEAD -- . \
  ':(exclude)codex-release2/window.md' \
  ':(exclude)codex-release2/final-report.md' ':(exclude).tickets/clef2-7kpa.md' \
  ':(exclude).github/tests/test_release_window.py'
test "$(git -C "$LANDING" rev-parse HEAD:.github/tests/test_release_window.py)" = c71f5cdcbc46acc729d4c0da0b4e50c73e812942
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

# Record the pre-window pipeline revision and pointer bytes/ETag before any live effect.
gh api "repos/$REPO/git/ref/heads/pipeline-data" --jq .object.sha > "$WINDOW/previous-pipeline-revision.txt"
export ROLLBACK_WINDOW="$WINDOW"
cd "$LANDING"
.venv/bin/python -I - <<'PY_A'
from pathlib import Path
import os,json
from congress_shared.storage import connect_r2
from viewer_publication.archive_publish import read_pointer
w=Path(os.environ['ROLLBACK_WINDOW'])
client=connect_r2(bucket='congressional-tech-raw',retries={'total_max_attempts':1})
value,etag=read_pointer(client,bucket='congressional-tech-raw',evidence=w/'before-A-pointer.json')
if not etag:raise ValueError('Existing pre-window pointer and ETag are required')
with (w/'before-A-pointer.etag.json').open('x') as f:
    json.dump({'etag':etag,'release_id':value['release_id'] if value else None},f);f.write('\n')
PY_A

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

# Local v6 publishers are separate from Actions and must also be drained.
if pgrep -f '[p]ublish[-_]viewer[-_]r2|[p]ublish_local_preparation[.]py|[p]ublish-filename-viewer[.]py' \
  > "$WINDOW/local-v6-publisher-pids.txt"; then
  echo 'A local v6 publisher is active; its PIDs are retained in the window evidence.'
  exit 1
else
  local_probe_status=$?
  test "$local_probe_status" -eq 1
fi

# 1. Private binary upload is create-only and verifies complete readback.
cd "$LANDING"
.venv/bin/python -I -m viewer_publication.publish_docspec_runtime \
  --upload --bucket congressional-tech-runtime --binary "$RUNTIME_PACKET/docspec" \
  --expected-descriptor "$RUNTIME_PACKET/runtime-artifact.json" \
  --source-revision 885e8c3c2a971a0c11b16ff9ca5a69e8ecb79c26 --platform linux-amd64 \
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

# All six hosted shards must complete; retain the visible red baseline result.
dispatch_and_watch validate-explorer.yml --baseline-validation
touch "$WINDOW/window-a-complete"
```

The push is normal and fast-forward only; it never forces main. If main changed in a way that changes the landing tree, the command stops before pushing. If protection rejects the push, stop and use the lead's approved merge method; do not force or bypass protection. No data upload, public pointer flip, capture activation or legacy deletion is part of this block.

## B: accepted seed, controller, then Pages

Before setting `WINDOW_B_READY=1`, the lead retains the engine-approved full manifest as `$WINDOW/accepted-seed-manifest.json` and the exact committed active publisher specification as `$WINDOW/accepted-publish-spec.json`. Require count reconciliation, at most 3% reasoned exclusions, the fifty-document comparison, canary, browser checks and accepted emulated speed targets. B remains stopped until engine supplies these exact artifact paths and their accepted source pins. If the active publisher binding lands after A, update and requalify the application handoff before B; the existing main-head guard intentionally refuses a silent head change.

Keep the same shell so `dispatch_and_watch`, `WINDOW`, `REPO` and `LANDED_APPLICATION` stay defined. Engine must announce the accepted seed and committed publish binding before the controller step. The first release records `seed: v5 catalog 596f08fa` and its pinned input SHA-256s. Its schema, reader, canary, desktop/phone/404 checks, count reconciliation and 50-document comparison must pass. The raw rebuild continues separately; seed `url_state` never drives capture. The switch checklist is `docs/plans/engine-first-switch.md`; its seed release and publish pins govern this phase.

```sh
set +x
set -euo pipefail
WINDOW_B_READY=0
test "$WINDOW_B_READY" -eq 1
test -e "$WINDOW/window-a-complete"
test -s "$WINDOW/accepted-seed-manifest.json"
test -s "$WINDOW/accepted-publish-spec.json"
test -s "$WINDOW/previous-pipeline-revision.txt"

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

# The seed is display-only: preserve existing acquisition until the raw rebuild.
# Disable automatic archive publication after this one accepted seed publish.
gh workflow disable archive-jobs.yml --repo "$REPO"
gh workflow enable capture-raw-sources.yml --repo "$REPO"
gh workflow enable update-data.yml --repo "$REPO"
# capture-archive.yml and the retired filename publisher remain disabled.
```

The first hosted check verifies private download credentials and Ubuntu execution; local Linux checks do not claim that boundary. The lead's landing gate requires six completed shard test sessions within 30 minutes each, actual runner exits and matching selected/completed node counts, successful infrastructure steps, and failure identities that are a subset of the pinned 36. Compare both directions and retain every resolved identity; only a new identity fails this part of the gate. Retain all logs, job metadata and `hosted-baseline-comparison.json`. Report the actual status as **red on N pre-existing baseline failures, no new failures; R resolved**. Say green only when the entire workflow succeeds with zero failures. Tests still run and fail visibly; this evidence check changes no CI conclusion, assertion, skip or workflow result. Missing evidence, interrupted or partial sessions, infrastructure failures, new identities or timed-out shards stop the window. Error counts require explicit setup-phase tracebacks; a teardown error stops this gate because one test can otherwise be counted twice. Retain the diagnostics for owner inspection; do not adjust the counts or suppress the error. Publisher and Pages dispatch still require success. If `gh workflow run` does not return the new run URL, the function stops and lists matching runs. Select the just-dispatched run using its URL/creation time, record its ID in the corresponding `run-*-id.txt`, verify its exact head and watch it; do not dispatch a duplicate controller job. Keep new archive capture, automated archive publication and the retired filename publisher disabled. The old raw capture and meeting updates stay enabled until the accepted raw rebuild replaces the seed; the owner will then use engine's rebuild switch checklist.

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
git -C "$LANDING" switch -c rollback/engine-first-20261028 "$LANDED_APPLICATION"
git -C "$LANDING" restore --source="$PREVIOUS_APPLICATION" --staged --worktree -- .
git -C "$LANDING" commit -m 'Restore the previous application with its qualified runtime' \
  -m 'Roll back the integration landing as one forward commit; preserve the pre-window B15 raw safety repair and leave all stored data intact.'
test "$(gh api "repos/$REPO/git/ref/heads/main" --jq .object.sha)" = "$LANDED_APPLICATION"
gh variable set DOCSPEC_RUNTIME_ARTIFACT --repo "$REPO" \
  --body "$(cat "$WINDOW/previous-runtime-artifact.json")"
case "$(cat "$WINDOW/previous-account-present.txt")" in
  true) gh variable set CLOUDFLARE_ACCOUNT_ID --repo "$REPO" --body "$(cat "$WINDOW/previous-account-id.txt")" ;;
  false) gh variable delete CLOUDFLARE_ACCOUNT_ID --repo "$REPO" ;;
  *) exit 1 ;;
esac
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


## After B: restore pointer, paired application, prior Pages and workflow states

Run this from the still-landed checkout before restoring its tree. Keep publishers and Pages paused and drain them using A's checks; never cancel acquisition. Retain the exact recorded publish run and attempt. The saved outgoing pointer is the controller's immediate pre-flip target; A's earlier pointer snapshot remains evidence and is never silently substituted. A missing outgoing pointer, changed seed/status, conditional-write conflict (409/412) or lost acknowledgement stops the block without retry. If status fails after the durable pointer acknowledgement, stop and repair only status through the existing writer; never repeat the pointer write. No raw object or immutable release is deleted.

```sh
set +x
set -euo pipefail
export ROLLBACK_WINDOW="$WINDOW"
PUBLISH_RUN_ID=$(cat "$WINDOW/run-archive-jobs-id.txt")
test "$(gh run view "$PUBLISH_RUN_ID" --repo "$REPO" --json headSha --jq .headSha)" = "$(cat "$WINDOW/landed-application-commit.txt")"
PUBLISH_ATTEMPT=$(gh api "repos/$REPO/actions/runs/$PUBLISH_RUN_ID" --jq .run_attempt)
mkdir "$WINDOW/post-data-rollback"
gh run download "$PUBLISH_RUN_ID" --repo "$REPO" \
  --name "archive-publish-evidence-$PUBLISH_RUN_ID-$PUBLISH_ATTEMPT" \
  --dir "$WINDOW/post-data-rollback/publish-evidence"
cd "$LANDING"
# Existing publisher token, supplied by the lead: R2_ACCESS_KEY_ID,
# R2_SECRET_ACCESS_KEY and CLOUDFLARE_ACCOUNT_ID. Do not echo their values.
.venv/bin/python -I - <<'PY_ROLLBACK'
from pathlib import Path
from hashlib import sha256
import json, os
from congress_shared.storage import connect_r2
from viewer_publication.archive_publish import (
    CONTROL_BYTES, STATUS, _read, _sha, read_pointer, write_status,
)
from viewer_publication.client import publish_manifest_pointer

window=Path(os.environ['ROLLBACK_WINDOW'])
work=window/'post-data-rollback'
evidence=work/'publish-evidence'
manifest=json.loads((window/'accepted-seed-manifest.json').read_text())
expected=_sha(manifest['release_id'])
origin=manifest.get('origin',{})
if origin.get('kind')!='seed_v5' or origin.get('display_only') is not True:
    raise ValueError('Rollback requires this window\'s accepted display-only seed')
spec=json.loads((window/'accepted-publish-spec.json').read_text())
if spec.get('model_kind')!='seed_v5':raise ValueError('Unexpected publication binding')
bucket=spec['bucket']
if bucket!='congressional-tech-raw':
    raise ValueError('Unexpected publication bucket')
for name in ['contract','canary']:
    receipt=json.loads((evidence/(name+'.json')).read_text())
    if (receipt.get('status')!='passed' or receipt.get('releaseId')!=expected
            or receipt.get('targets') not in {'owner-approved','provisional-emulated'}):
        raise ValueError('Evidence does not identify the accepted seed: '+name)
# read_pointer already validated and retained these exact outgoing bytes before B.
# They are used verbatim, never re-encoded, and remain in the window evidence.
saved=evidence/'outgoing-pointer.json'
if saved.is_symlink() or not 0<saved.stat().st_size<=CONTROL_BYTES:
    raise ValueError('Missing or invalid saved outgoing pointer')
raw=saved.read_bytes()
old=json.loads(raw)
if not isinstance(old,dict) or old.get('release_id')==expected:
    raise ValueError('Saved outgoing pointer does not precede this seed')
if (str(old.get('version'))!='1' or str(old.get('publisher_version'))!='10'
        or not isinstance(old.get('catalog_id'),str) or not old['catalog_id']
        or not isinstance(old.get('manifest'),str) or not old['manifest']
        or 'release_id' in old or 'previous_release_id' in old):
    raise ValueError('First-seed rollback requires its saved legacy v5 pointer')
restored=None
digest=sha256(raw).hexdigest()
# No hidden SDK retries around this single conditional pointer write.
client=connect_r2(bucket=bucket,retries={'total_max_attempts':1})
current,etag=read_pointer(client,bucket=bucket,evidence=work/'observed-seed-pointer.json')
status_raw,_=_read(client,bucket,STATUS)
status=json.loads(status_raw)
if (not isinstance(status,dict) or not isinstance(current,dict)
        or set(current)!={'release_id','previous_release_id'}
        or current.get('release_id')!=expected
        or current.get('previous_release_id') is not None
        or status.get('status')!='published' or status.get('release_id')!=expected
        or status.get('live_release')!=expected
        or status.get('live_release_basis')!='conditional_flip_acknowledged'
        or status.get('input_kind')!='seed_v5' or status.get('display_only') is not True):
    raise ValueError('Current pointer/status no longer identifies this window\'s published seed')
# If-Match binds the exact ETag observed above. A 409/412 or lost response
# propagates: stop and investigate; never retry or write an unconditional pointer.
transfer=publish_manifest_pointer(client,bucket=bucket,pointer=raw,expected_etag=etag)
if (not isinstance(transfer.etag,str) or not transfer.etag.strip()
        or transfer.sha256!=digest or transfer.bytes!=len(raw)):
    raise ValueError('Pointer restore lacks acknowledgement; stop and inspect')
ack=dict(status='pointer_restored',from_release=expected,restored_release=restored,
    previous_etag=etag,restored_etag=transfer.etag,saved_pointer_sha256=digest,
    restored_catalog_id=old['catalog_id'],
    bytes=transfer.bytes)
# Make the acknowledged pointer effect durable BEFORE the fallible status write.
with (work/'pointer-restore-ack.json').open('x') as destination:
    json.dump(ack,destination,sort_keys=True);destination.write('\n')
    destination.flush();os.fsync(destination.fileno())
write_status(client,bucket=bucket,status=dict(status='rolled_back',release_id=expected,
    input_kind='seed_v5',display_only=True,live_release=restored,
    live_release_basis='legacy_pointer_restored',
    restored_pointer_sha256=digest))
with (work/'status-restored.json').open('x') as destination:
    json.dump(dict(status='rolled_back',from_release=expected,live_release=restored),destination)
    destination.write('\n');destination.flush();os.fsync(destination.fileno())
print(json.dumps(ack,sort_keys=True))
PY_ROLLBACK

PREVIOUS_APPLICATION=$(cat "$WINDOW/previous-application-commit.txt")
LANDED_APPLICATION=$(cat "$WINDOW/landed-application-commit.txt")
test -f "$WINDOW/post-data-rollback/pointer-restore-ack.json"
test -f "$WINDOW/post-data-rollback/status-restored.json"
test -z "$(git -C "$LANDING" status --porcelain)"
git -C "$LANDING" fetch origin main
test "$(git -C "$LANDING" rev-parse origin/main)" = "$LANDED_APPLICATION"
git -C "$LANDING" switch -c rollback/engine-first-after-data-20261028 "$LANDED_APPLICATION"
git -C "$LANDING" restore --source="$PREVIOUS_APPLICATION" --staged --worktree -- .
git -C "$LANDING" commit -m 'Restore the previous application after guarded data rollback' \
  -m 'The public pointer was restored conditionally from its saved exact bytes. Restore the paired runtime/application without deleting retained releases or raw data.'
test "$(gh api "repos/$REPO/git/ref/heads/main" --jq .object.sha)" = "$LANDED_APPLICATION"
gh variable set DOCSPEC_RUNTIME_ARTIFACT --repo "$REPO" --body "$(cat "$WINDOW/previous-runtime-artifact.json")"
case "$(cat "$WINDOW/previous-account-present.txt")" in
  true) gh variable set CLOUDFLARE_ACCOUNT_ID --repo "$REPO" --body "$(cat "$WINDOW/previous-account-id.txt")" ;;
  false) gh variable delete CLOUDFLARE_ACCOUNT_ID --repo "$REPO" ;;
  *) exit 1 ;;
esac
git -C "$LANDING" push origin HEAD:refs/heads/main
ROLLED_BACK_APPLICATION=$(git -C "$LANDING" rev-parse HEAD)
printf '%s\n' "$ROLLED_BACK_APPLICATION" > "$WINDOW/rollback-application-commit.txt"
gh variable get DOCSPEC_RUNTIME_ARTIFACT --repo "$REPO" > "$WINDOW/post-data-rollback/runtime-readback.json"
jq -S . "$WINDOW/post-data-rollback/runtime-readback.json" > "$WINDOW/post-data-rollback/runtime-canonical.json"
cmp "$WINDOW/post-data-rollback/runtime-canonical.json" "$WINDOW/previous-canonical.json"
PREVIOUS_PIPELINE_REVISION=$(cat "$WINDOW/previous-pipeline-revision.txt")
git -C "$LANDING" rev-parse --verify "$PREVIOUS_APPLICATION^{commit}" >/dev/null
gh workflow enable deploy-pages.yml --repo "$REPO"
# Preserve B's run receipts; the maintained helper writes into a fresh namespace.
(
  WINDOW="$ROLLBACK_WINDOW/post-data-rollback/pages"
  mkdir "$WINDOW"
  LANDED_APPLICATION="$ROLLED_BACK_APPLICATION"
  dispatch_and_watch deploy-pages.yml --raw-field code_revision="$ROLLED_BACK_APPLICATION" \
    --raw-field pipeline_revision="$PREVIOUS_PIPELINE_REVISION"
)
# Restore each recorded managed workflow's enabled/disabled state only AFTER Pages.
while IFS=$'\t' read -r workflow_id previous_state; do
  case "$previous_state" in
    active) gh workflow enable "$workflow_id" --repo "$REPO" ;;
    disabled_manually|disabled_inactivity) gh workflow disable "$workflow_id" --repo "$REPO" ;;
    *) exit 1 ;;
  esac
done < <(jq -r '.[] | [.id,.state] | @tsv' "$WINDOW/managed-workflows-before.json")
```

Stop if main advances, runtime readback differs, Pages fails, a receipt is missing or workflow state is unrecognized. The saved pre-window pipeline revision supplies the prior site data. The paired application/runtime restore precedes Pages because its existing workflow requires code revision to match main. Preserve the original B receipts in their namespace. New archive capture remains disabled.
