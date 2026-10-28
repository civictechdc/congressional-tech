# Lead runtime, main and data switch window

Status: runtime `885e8c3` is qualified locally. A remains blocked on the frozen landing’s final local CI-environment full run and this revised checklist’s review. A covers runtime upload, main landing and variables after local qualification. Hosted validation is a separate CI-health follow-up. The full seed packet is accepted; B remains stopped until this local driver and rollback review closes. A does not require seed publication. Both blocks stop at their own readiness guards.

Only the lead executes these outward commands. B0 receipt rewriting and R2 bucket locks remain deferred to a supervised owner window; this block runs neither. The artifact is an ordinary `linux-amd64` build from `885e8c3c2a971a0c11b16ff9ca5a69e8ecb79c26`: 227161600 bytes, SHA-256 `bd337f62a9f98e23da834a04159d59b41860a14a718e91dc8728480cc1094edd`. Linux qualification evidence: 159 passed on application `553a8383`; the three affected cases passed on application `a27a3351` after the approved worker repair (3 passed in 157.29s). Initial failures and both source-specific logs remain in the packet; this does not claim all 163 tests passed on one source. The checks use amd64 Python 3.12.13 and real native model/group/export plus runtime setup. The unchanged 120-second bounded-metadata fanout assertion timed out under QEMU; hosted native amd64 execution remains unverified. The lead made hosted CI a separate health follow-up; never raise this timeout or claim that boundary passed. The immutable packet includes the exact descriptor, rollback descriptor, cross recipe and qualification evidence.

Current variable readback is the previous `c949c6762f001845d2933e55cb9d7cf237e80810` runtime: 220,185,776 bytes, SHA-256 `c14bfbd12b6ad958e9fa8cd8d2bc57feb014ef12431a9826ec078c631fdafd33`, bucket `congressional-tech-runtime`. Its complete JSON is in `rollback-runtime-artifact.json` in the packet. The application pin and variable must change together. Keep publishing, capture and Pages workflows paused during the window. Disabling a workflow preserves running jobs; the drain check below stops until every existing job finishes. Keep them paused after A and through B’s local seed publication, then restore the old capture and update jobs after Pages succeeds. The new capture stays disabled until the raw rebuild passes its release checks. A hosted check queued before the variable changes may need a rerun afterwards.

B15 must already be on main before recording the rollback application commit. That preserves raw-before-push behavior even if the integration landing is rolled back. All Git operations below use the landing worktree, never the pinned rescue worktree.

The lead also confirms that no local v6 publisher or opaque wrapper is running.
The process gate covers the maintained CLI names; workflow pauses do not drain
local commands. Let each publisher's owner finish or stop it safely before this window.

## A: upload, land main and set variables

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

pause_and_drain() {
  local revision="$1" stage="$2" evidence workflow_id state
  git -C "$LANDING" cat-file -e "$revision^{commit}"
  evidence=$(mktemp -d "$WINDOW/drain-$stage.XXXXXX")
  jq -r '.[].path' "$WINDOW/managed-workflows-before.json" > "$evidence/candidates.txt"
  printf '%s\n' .github/workflows/capture-archive.yml .github/workflows/archive-jobs.yml >> "$evidence/candidates.txt"
  # Deliberately deleted workflows have no workflow ID on the landed main.
  git -C "$LANDING" ls-tree -r --name-only "$revision" -- .github/workflows \
    > "$evidence/source-paths.txt"
  jq -Rn --rawfile candidates "$evidence/candidates.txt" --rawfile source "$evidence/source-paths.txt" \
    '($source|split("\n")) as $present | $candidates|split("\n")|map(select(length>0))|unique|map(select(. as $p|$present|index($p)))' \
    > "$evidence/expected-paths.json"
  gh workflow list --all --repo "$REPO" --json id,path,state > "$evidence/workflows.json"
  jq --slurpfile expected "$evidence/expected-paths.json" \
    '[.[]|select(.path as $p|$expected[0]|index($p))]' "$evidence/workflows.json" > "$evidence/managed.json"
  jq -e --slurpfile expected "$evidence/expected-paths.json" \
    '([.[].path]|sort)==($expected[0]|sort) and all(.[];(.id|type=="number") and .id>0 and (.state=="active" or .state=="disabled_manually" or .state=="disabled_inactivity" or .state=="disabled_fork"))' \
    "$evidence/managed.json" > /dev/null
  jq -r '.[]|select(.state=="active")|.id' "$evidence/managed.json" > "$evidence/active-ids.txt"
  while IFS= read -r workflow_id; do
    gh workflow disable "$workflow_id" --repo "$REPO"
  done < "$evidence/active-ids.txt"
  jq -r '.[].id' "$evidence/managed.json" > "$evidence/ids.txt"
  while IFS= read -r workflow_id; do
    for state in queued in_progress requested waiting pending; do
      gh run list --all --workflow "$workflow_id" --repo "$REPO" --status "$state" --limit 1 \
        --json databaseId,status,url > "$evidence/$workflow_id-$state.json"
      test "$(jq length "$evidence/$workflow_id-$state.json")" -eq 0
    done
  done < "$evidence/ids.txt"
}

assert_no_local_publishers() {
  local stage="$1" local_probe_status
  if pgrep -f '[p]ublish[-_]viewer[-_]r2|[p]ublish_local_preparation[.]py|[p]ublish-filename-viewer[.]py' \
    > "$WINDOW/local-v6-publisher-$stage-pids.txt"; then
    echo 'A local v6 publisher is active; stop and retain its recorded PIDs.'
    return 1
  else
    local_probe_status=$?
    test "$local_probe_status" -eq 1
  fi
}

# Public operator helpers; no credentials are written here.
declare -f dispatch_and_watch pause_and_drain assert_no_local_publishers > "$WINDOW/operator-functions.sh"
printf 'export WINDOW=%q LANDING=%q REPO=%q\n' "$WINDOW" "$LANDING" "$REPO" > "$WINDOW/operator-context.sh"

# Lead only: refresh the target before its local merge; release never fetched.
git -C "$LANDING" fetch origin main
test -z "$(git -C "$LANDING" status --porcelain)"
QUALIFIED_LANDING=86253c4191415a441cb3c3e77b0c38ce9b9ad4f7
git -C "$LANDING" merge-base --is-ancestor "$QUALIFIED_LANDING" HEAD
# Only the final handoff notes, this ticket closure and the exact reviewed operator test blob may follow the tested application code.
git -C "$LANDING" diff --quiet "$QUALIFIED_LANDING" HEAD -- . \
  ':(exclude)codex-release2/window.md' \
  ':(exclude)codex-release2/final-report.md' ':(exclude).tickets/clef2-7kpa.md' \
  ':(exclude).github/tests/test_release_window.py'
test "$(git -C "$LANDING" rev-parse HEAD:.github/tests/test_release_window.py)" = 08bb4a3c510c132b3d8e9a76fefe480cce47d5b5
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
pause_and_drain "$PREVIOUS_APPLICATION" before-A
assert_no_local_publishers before-A

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

# Release enables A only after the completed local CI-environment full run.
touch "$WINDOW/window-a-complete"
```

The push is normal and fast-forward only; it never forces main. If main changed in a way that changes the landing tree, the command stops before pushing. If protection rejects the push, stop and use the lead's approved merge method; do not force or bypass protection. No data upload, public pointer flip, capture activation or legacy deletion is part of this block.

## B: accepted seed, controller, then Pages

The accepted immutable packet is `codex-coord/shared/seed-publish-2ebf773d/`. After A, copy its `publish.json` to `$WINDOW/accepted-publish-spec.json` and its `accepted-seed-manifest.json` to the same basename under `$WINDOW`. Exact copy commands: `cp -n "$SEED_PACKET/publish.json" "$WINDOW/accepted-publish-spec.json"` and `cp -n "$SEED_PACKET/accepted-seed-manifest.json" "$WINDOW/accepted-seed-manifest.json"`, with `SEED_PACKET` set to that absolute packet path. Verify SHA-256 respectively `127f93ad7a4d981132c4e552b932a9801176d318d1ef6391f08a6bad5c23aa0b` and `06bcc6f1f0f65b89cba5713ab0e5ed7577d0c6f8e8cb1299956e82a5da95f8e8`. Build the final source with `npm --prefix apps/site run build` before launch; its output path is pinned by the spec. The manifest reconciles 1,241,157 inputs: 936,580 listed, 281,200 merged and 23,377 reasoned exclusions (1.88%). Engine accepted the fifty-document comparison, canary, phone/desktop/404 checks and emulated targets.

The seed is display-only (`seed: v5 catalog 596f08fa`); raw rebuilding remains separate. The lead supplies existing DOCSPEC credentials through the environment without printing them. Keep the A shell, or restore its public context and helper files. The first block launches once and returns; the second block only polls, then deploys Pages after acceptance. Poll again while running; an uncertain or failed attempt requires inspection, never a new launch.

```sh
set +x
set -euo pipefail
WINDOW_B_READY=0
test "$WINDOW_B_READY" -eq 1
test -e "$WINDOW/window-a-complete"
test -s "$WINDOW/accepted-seed-manifest.json"
test -s "$WINDOW/accepted-publish-spec.json"
test -s "$WINDOW/previous-pipeline-revision.txt"
test "$(shasum -a 256 "$WINDOW/accepted-publish-spec.json" | cut -d ' ' -f 1)" = 127f93ad7a4d981132c4e552b932a9801176d318d1ef6391f08a6bad5c23aa0b
test "$(shasum -a 256 "$WINDOW/accepted-seed-manifest.json" | cut -d ' ' -f 1)" = 06bcc6f1f0f65b89cba5713ab0e5ed7577d0c6f8e8cb1299956e82a5da95f8e8
source "$WINDOW/operator-functions.sh"
LANDED_APPLICATION=$(cat "$WINDOW/landed-application-commit.txt")
export LANDED_APPLICATION
cd "$LANDING"
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = "$LANDED_APPLICATION"
test "$(gh api "repos/$REPO/git/ref/heads/main" --jq .object.sha)" = "$LANDED_APPLICATION"
pause_and_drain "$LANDED_APPLICATION" before-B
assert_no_local_publishers before-B
export R2_ACCESS_KEY_ID="${DOCSPEC_S3_ACCESS_KEY_ID:?}"
export R2_SECRET_ACCESS_KEY="${DOCSPEC_S3_SECRET_ACCESS_KEY:?}"
export CLOUDFLARE_ACCOUNT_ID=174055408ff1560e60601c4d12c561c4
export LOCAL_PUBLISH_WINDOW="$WINDOW"
# Fresh paths make this a single attempt. Do not rerun this launch block.
test ! -e "$WINDOW/local-publish-runner.py"
test ! -e "$WINDOW/local-publish-launcher.json"
test ! -e "$WINDOW/local-publish"
test ! -e "$WINDOW/data-activation-started"
cat > "$WINDOW/local-publish-runner.py" <<'PY_LOCAL_PUBLISH'
from pathlib import Path
from hashlib import sha256
import json, os, subprocess
from congress_shared.custody import write_atomic_json
from congress_shared.storage import connect_r2
from viewer_publication.archive_publish import STATUS, _read, read_pointer
from viewer_publication.archive_publish_job import load_spec
from viewer_publication.archive_gate import validate_receipt

w=Path(os.environ['LOCAL_PUBLISH_WINDOW']).resolve()
spec_path=w/'accepted-publish-spec.json'
manifest_path=w/'accepted-seed-manifest.json'
spec_raw=spec_path.read_bytes(); manifest_raw=manifest_path.read_bytes()
manifest=json.loads(manifest_raw); expected=manifest['release_id']
if manifest.get('origin',{}).get('kind')!='seed_v5' or manifest['origin'].get('display_only') is not True:
    raise ValueError('Expected the accepted display-only seed manifest')
spec=load_spec(spec_path)
if spec.get('model_kind')!='seed_v5' or spec.get('bucket')!='congressional-tech-raw':
    raise ValueError('Expected the accepted seed publication binding')
landed=(w/'landed-application-commit.txt').read_text().strip()
if subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()!=landed:
    raise ValueError('Local application differs from the landed revision')
if subprocess.check_output(['git','status','--porcelain'],text=True).strip():
    raise ValueError('Local application must be clean')
work=Path(spec['work'])
if work.exists() or work.is_symlink():raise ValueError('Publication work already exists')
evidence=w/'local-publish'
evidence.mkdir(exist_ok=False)
parent=os.open(evidence.parent,os.O_RDONLY)
try:os.fsync(parent)
finally:os.close(parent)
binding=dict(landed_application=landed,release_id=expected,spec_path=str(spec_path),
    spec_sha256=sha256(spec_raw).hexdigest(),manifest_sha256=sha256(manifest_raw).hexdigest(),
    work=str(work),model_output=spec['_model']['output'],model_scratch=spec['_model']['scratch'])
def durable(path,value):
    if path.exists() or path.is_symlink():raise ValueError('Evidence already exists: '+str(path))
    write_atomic_json(path,value,fsync=True,fsync_dir=True)
durable(evidence/'process.json',dict(pid=os.getpid(),pgid=os.getpgrp()))
durable(evidence/'binding.json',binding)
# This is the maintained --execute implementation. Probe stdout remains diagnostic.
controller_code='''import sys
from viewer_publication.archive_publish_job import execute,load_spec
from congress_shared.custody import write_atomic_json
result=execute(load_spec(sys.argv[1]))
write_atomic_json(sys.argv[2],result,fsync=True,fsync_dir=True)
raise SystemExit(2 if result.get('status') in {'pending','backfill_required'} else 0)
'''
with (evidence/'controller.stdout.log').open('xb') as out,(evidence/'stderr.log').open('xb') as err:
    completed=subprocess.run(['.venv/bin/python','-I','-c',controller_code,
        str(spec_path),str(evidence/'controller-result.json')],stdout=out,stderr=err,check=False)
    out.flush();os.fsync(out.fileno());err.flush();os.fsync(err.fileno())
durable(evidence/'exit.json',dict(returncode=completed.returncode))
if completed.returncode:raise SystemExit('Controller failed; retain evidence and inspect before any further effect')
if spec_path.read_bytes()!=spec_raw or manifest_path.read_bytes()!=manifest_raw:
    raise ValueError('Approved local binding changed during publication')
result=json.loads((evidence/'controller-result.json').read_text())
if (result.get('status')!='published' or result.get('release_id')!=expected
        or result.get('live_release')!=expected
        or result.get('live_release_basis')!='conditional_flip_acknowledged'):
    raise ValueError('Local controller did not acknowledge this seed publication')
if (Path(spec['_model']['output'])/'manifest.json').read_bytes()!=manifest_raw:
    raise ValueError('Rebuilt seed manifest differs from the approved candidate')
for name in ['contract','canary']:
    validate_receipt(json.loads((work/(name+'.json')).read_text()),release_id=expected,
        name=name,manifest_origin=manifest['origin'])
outgoing=(work/'outgoing-pointer.json').read_bytes()
response=json.loads((work/'outgoing-pointer.response.json').read_text())
if (not isinstance(response.get('etag'),str) or not response['etag'].strip()
        or response.get('sha256')!=sha256(outgoing).hexdigest() or response.get('bytes')!=len(outgoing)):
    raise ValueError('Outgoing pointer response does not bind its exact bytes and ETag')
client=connect_r2(bucket=spec['bucket'],retries={'total_max_attempts':1})
pointer,etag=read_pointer(client,bucket=spec['bucket'],evidence=evidence/'observed-published-pointer.json')
raw,_=_read(client,spec['bucket'],STATUS)
with (evidence/'observed-status.json').open('xb') as f:
    f.write(raw);f.flush();os.fsync(f.fileno())
status=json.loads(raw)
if (pointer!={'release_id':expected,'previous_release_id':None}
        or status.get('status')!='published' or status.get('live_release')!=expected
        or status.get('release_id')!=expected
        or status.get('live_release_basis')!='conditional_flip_acknowledged'
        or status.get('input_kind')!='seed_v5' or status.get('display_only') is not True):
    raise ValueError('Public pointer/status no longer identifies this accepted seed')
durable(evidence/'accepted.json',dict(binding,observed_pointer_etag=etag,status='published'))
print(json.dumps(dict(status='published',release_id=expected,evidence=str(evidence)),sort_keys=True))
PY_LOCAL_PUBLISH
# The attempt marker prevents pre-data rollback even if launch acknowledgement is lost.
touch "$WINDOW/data-activation-started"
.venv/bin/python -I - <<'PY_LAUNCH'
from pathlib import Path
from hashlib import sha256
import json,os,subprocess,sys
from congress_shared.custody import write_atomic_json
w=Path(os.environ['LOCAL_PUBLISH_WINDOW'])
record=w/'local-publish-launcher.json'
if record.exists() or record.is_symlink():raise ValueError('A controller launch already exists; inspect its PID/status')
script=w/'local-publish-runner.py'
with script.open('rb') as source:os.fsync(source.fileno())
with (w/'local-publish-driver.stdout.log').open('xb') as out,(w/'local-publish-driver.stderr.log').open('xb') as err:
    process=subprocess.Popen(['/usr/bin/nohup',sys.executable,'-I',str(script)],
        stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
    write_atomic_json(record,dict(pid=process.pid,pgid=process.pid,script_sha256=sha256(script.read_bytes()).hexdigest()),fsync=True,fsync_dir=True)
print(json.dumps(dict(pid=process.pid,pgid=process.pid,status='started_unaccepted')))
PY_LAUNCH
```

The launch returns immediately. Retain both driver logs and local-publish-launcher.json. Inspect the PID and status before continuing. A lost response never authorizes a second controller attempt.

```sh
set +x
set -euo pipefail
# Resume here after a session restart. Never repeat B's launch block.
source "$WINDOW/operator-context.sh"
source "$WINDOW/operator-functions.sh"
LANDED_APPLICATION=$(cat "$WINDOW/landed-application-commit.txt")
export LOCAL_PUBLISH_WINDOW="$WINDOW"
cd "$LANDING"
# Read-only poll: accepted receipt or retained PID/status, never an automatic restart.
.venv/bin/python -I - <<'PY_POLL'
from pathlib import Path
import json,os
w=Path(os.environ['LOCAL_PUBLISH_WINDOW']);e=w/'local-publish'
launcher=json.loads((w/'local-publish-launcher.json').read_text())
try:
    os.kill(launcher['pid'],0)
except ProcessLookupError:
    running=False
else:
    running=True
if (e/'accepted.json').is_file():
    binding=json.loads((e/'binding.json').read_text())
    accepted=json.loads((e/'accepted.json').read_text())
    if accepted!={**binding,'observed_pointer_etag':accepted.get('observed_pointer_etag'),'status':'published'} or not accepted.get('observed_pointer_etag'):
        raise SystemExit('Acceptance does not bind this local publication')
    if running:raise SystemExit('Acceptance exists but driver has not exited; poll again')
    print(json.dumps(dict(status='accepted',release_id=binding['release_id'])))
else:
    state='running_unaccepted' if running else 'stopped_unaccepted'
    raise SystemExit(state+': inspect retained driver/controller logs and exit.json; never automatically repeat publication')
PY_POLL
test -f "$WINDOW/local-publish/accepted.json"
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = "$LANDED_APPLICATION"
test "$(gh api "repos/$REPO/git/ref/heads/main" --jq .object.sha)" = "$LANDED_APPLICATION"
# Controller success includes the accepted local reader, HTTPS canary and conditional flip.
gh api "repos/$REPO/git/ref/heads/pipeline-data" --jq .object.sha > "$WINDOW/pipeline-revision.txt"
PIPELINE_REVISION=$(cat "$WINDOW/pipeline-revision.txt")
gh workflow enable deploy-pages.yml --repo "$REPO"
dispatch_and_watch deploy-pages.yml --raw-field code_revision="$LANDED_APPLICATION" \
  --raw-field pipeline_revision="$PIPELINE_REVISION"
# Preserve existing acquisition until the raw rebuild's separate accepted switch.
gh workflow disable archive-jobs.yml --repo "$REPO"
gh workflow enable capture-raw-sources.yml --repo "$REPO"
gh workflow enable update-data.yml --repo "$REPO"
# capture-archive.yml and the retired filename publisher remain disabled.
```

Hosted checks remain a separate CI-health follow-up. Missing local acceptance, an active or uncertain driver, changed main, or a failed Pages run stops B. Keep archive schedules disabled. Preserve logs, work and local binding; never dispatch a duplicate controller or delete raw objects.

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
LANDED_APPLICATION=$(cat "$WINDOW/landed-application-commit.txt")
# Refuse changed local or remote application state BEFORE any rollback effect.
test -z "$(git -C "$LANDING" status --porcelain)"
test "$(git -C "$LANDING" rev-parse HEAD)" = "$LANDED_APPLICATION"
test "$(gh api "repos/$REPO/git/ref/heads/main" --jq .object.sha)" = "$LANDED_APPLICATION"
test -f "$WINDOW/local-publish/binding.json"
test -f "$WINDOW/local-publish/accepted.json"
source "$WINDOW/operator-functions.sh"
pause_and_drain "$LANDED_APPLICATION" before-rollback
assert_no_local_publishers before-rollback
"$LANDING/.venv/bin/python" -I -c 'import os;from pathlib import Path;from viewer_publication.archive_controller import _publication_directory;_publication_directory(Path(os.environ["ROLLBACK_WINDOW"])/"post-data-rollback",fresh=True)'
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
from congress_shared.custody import write_atomic_json

window=Path(os.environ['ROLLBACK_WINDOW'])
work=window/'post-data-rollback'
binding=json.loads((window/'local-publish/binding.json').read_text())
accepted=json.loads((window/'local-publish/accepted.json').read_text())
if accepted!={**binding,'observed_pointer_etag':accepted.get('observed_pointer_etag'),'status':'published'}:
    raise ValueError('Local publication acceptance differs from its recorded binding')
if binding.get('landed_application')!=(window/'landed-application-commit.txt').read_text().strip():
    raise ValueError('Local publication was not made by this landed application')
evidence=Path(binding['work'])
manifest=json.loads((window/'accepted-seed-manifest.json').read_text())
expected=_sha(manifest['release_id'])
if (binding.get('release_id')!=expected
        or binding.get('manifest_sha256')!=sha256((window/'accepted-seed-manifest.json').read_bytes()).hexdigest()
        or binding.get('spec_sha256')!=sha256((window/'accepted-publish-spec.json').read_bytes()).hexdigest()):
    raise ValueError('Local publication manifest or spec differs from its approved bytes')
origin=manifest.get('origin',{})
if origin.get('kind')!='seed_v5' or origin.get('display_only') is not True:
    raise ValueError('Rollback requires this window\'s accepted display-only seed')
spec=json.loads((window/'accepted-publish-spec.json').read_text())
if spec.get('model_kind')!='seed_v5' or Path(spec['work']).resolve()!=evidence.resolve():
    raise ValueError('Unexpected local publication binding')
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
response=json.loads(saved.with_suffix('.response.json').read_text())
if (not isinstance(response.get('etag'),str) or not response['etag'].strip()
        or response.get('sha256')!=sha256(raw).hexdigest() or response.get('bytes')!=len(raw)):
    raise ValueError('Saved outgoing pointer response does not bind its exact bytes and ETag')
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
write_atomic_json(work/'pointer-restore-ack.json',ack,fsync=True,fsync_dir=True)
write_status(client,bucket=bucket,status=dict(status='rolled_back',release_id=expected,
    input_kind='seed_v5',display_only=True,live_release=restored,
    live_release_basis='legacy_pointer_restored',
    restored_pointer_sha256=digest))
write_atomic_json(work/'status-restored.json',dict(status='rolled_back',from_release=expected,live_release=restored),fsync=True,fsync_dir=True)
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


## CI health follow-up: separate from the local switch gate

The lead’s local-run decision makes hosted validation independent of A and B. Run this separately after A when desired; a failure retains the actual red result for repair and does not authorize claiming healthy CI. The old 36 identities remain a historical comparison. The CI-environment comparison currently found no pre-existing failures, so this health check additionally requires zero observed failures and a successful whole workflow. The existing verifier still checks six completed shards, selected and completed counts, real exits, infrastructure steps and the 30-minute budget. No assertion, skip or workflow conclusion changes. Legacy wrapper limits remain an engine-owned F5 follow-up.

```sh
set -euo pipefail
test -e "$WINDOW/window-a-complete"
dispatch_and_watch validate-explorer.yml --baseline-validation
jq -e '.observed == [] and .new == []' "$WINDOW/hosted-baseline-comparison.json" > /dev/null
test "$(jq -r .conclusion "$WINDOW/hosted-validation-run.json")" = success
```
