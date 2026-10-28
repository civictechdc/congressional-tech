# Owner raw-safety checklist

Run in this order: **rescue import or verified copy off this disk → B15 → B1 → bodies/provenance locks → B0 → receipt lock → M1 smoke**. All commands below are owner actions, prepared locally and never run against live services by release. Keep the rescue batch and every private backup. The 35-snapshot batch currently has no independent copy.

Packages start from shared `origin/main` `7411f5b7`, with separate branches/worktrees. No fetch or change to the live checkout was needed. Main's runner predates the new offline native prerequisite: run `uv sync --locked` in each release worktree; these packages require no new native runtime for their Python checks. The M1 probe is a separate optimized native artifact.

## Prepare one owner shell and private evidence directory

Use `bash`, with credentials already exported by the owner. Do not enable shell tracing. Supply raw-object `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `CLOUDFLARE_ACCOUNT_ID` (`R2_ENDPOINT_URL` may override the object endpoint). Lock configuration additionally needs `CLOUDFLARE_API_TOKEN` with R2 bucket-configuration edit permission. Supply `B1_R2_ACCESS_KEY_ID` and `B1_R2_SECRET_ACCESS_KEY` for B1 scratch-only object access, and the separate `DOCSPEC_M1_*` credentials for M1. No command below opens a credential file.

```sh
set +x
set -euo pipefail
export SAFE_WORK="${SAFE_WORK:?Set a fresh private durable evidence directory}"
umask 077
mkdir "$SAFE_WORK"
export B15=/Users/mikewolfd/Work/wt/ct-b15-weekly-raw
export B1=/Users/mikewolfd/Work/wt/ct-release-b1
export B0=/Users/mikewolfd/Work/wt/ct-release-b0
export M1=/Users/mikewolfd/Work/wt/ct-release-m1
export RESCUE=/Users/mikewolfd/Work/ct-raw-rescue/pipeline-data
export REPO=civictechdc/congressional-tech
r2() {
  AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
    aws --endpoint-url "${R2_ENDPOINT_URL:-https://$CLOUDFLARE_ACCOUNT_ID.r2.cloudflarestorage.com}" \
      --region auto "$@"
}
inventory() {
  r2 s3api list-objects-v2 --bucket congressional-tech-raw --prefix "$1" \
    --query 'Contents[].{key:Key,size:Size,etag:ETag}' --output json |
    jq '. // []' > "$2"
}
checkpoint() {
  inventory bodies/ "$SAFE_WORK/$1-bodies.json"
  inventory receipts/ "$SAFE_WORK/$1-receipts.json"
}
unchanged() {
  jq -e --slurpfile after "$2" '
    ($after[0] | INDEX(.key)) as $new |
    all(.[]; . as $old | $new[$old.key] == $old)' "$1"
}
cf_locks() {
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/r2/buckets/$1/lock" "${@:2}"
}
```

`checkpoint before-N` / `checkpoint after-N`, then `unchanged before-N-bodies.json after-N-bodies.json` and the equivalent receipts check prove every earlier key retains its size and ETag. Use them around rescue, the first B15 run, and the first patched legacy writer run. Concurrent additions are allowed. B0's documented receipt replacements are the only exception. These bulk listings do not re-hash historical body contents.

## 1. Rescue import, or copy off this disk first

**Changes:** the import only creates missing bodies and its registered receipt. Let any running rescue pass finish and pause its scheduler so the batch stays fixed during copying/import; the count guard stops on a changed batch. A copy only writes the independent destination. Neither changes the original rescue batch.

```sh
cd "$B15"
uv sync --locked
.venv/bin/python -I -m congress_api.cli.pipeline_raw --rescue-batch "$RESCUE" --dry-run \
  > "$SAFE_WORK/rescue-plan.json"
jq -e '.snapshots == 35 and .files == 2135 and .bodies == 226 and .missing == 0' \
  "$SAFE_WORK/rescue-plan.json"
```

If credentials or the live import are not ready, copy the entire batch to an independent mounted disk **before proceeding to B15**:

```sh
: "${RESCUE_BACKUP:?Set a new directory on an independent mounted disk}"
test ! -e "$RESCUE_BACKUP"
ditto "$RESCUE" "$RESCUE_BACKUP"
.venv/bin/python -I - "$RESCUE" "$RESCUE_BACKUP" <<'PY'
import hashlib, json, pathlib, sys
source, backup = map(pathlib.Path, sys.argv[1:])
for name in ('commits.jsonl','files.jsonl'):
    assert (source/name).read_bytes() == (backup/name).read_bytes(), name
rows = [json.loads(x) for x in (backup/'files.jsonl').read_text().splitlines()]
for digest in {r['sha256'] for r in rows}:
    with (backup/'blobs'/digest).open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest() == digest, digest
assert len((backup/'commits.jsonl').read_text().splitlines()) == 35
print('Independent copy verified: 35 snapshots and every recorded source blob')
PY
```

For the import now, commit the actual UTC date and keep the resulting **exact application commit** for same-day retries:

```sh
cd "$B15"
test -z "$(git status --porcelain)"
.venv/bin/python -I - <<'PY'
import datetime,json,pathlib
p=pathlib.Path('model/registries/import-runs.json')
rows=json.loads(p.read_text())
for row in rows:
    if row['run_id']=='pipeline-data-rescue-20261027':
        row['date']=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
p.write_text(json.dumps(rows,indent=2)+'\n')
PY
git add model/registries/import-runs.json
if ! git diff --cached --quiet; then
  git commit -m 'Record actual rescued snapshot import date' \
    -m 'Pin the registered rescue run to the UTC date used for its owner import.'
fi
git rev-parse HEAD > "$SAFE_WORK/rescue-application-commit.txt"
checkpoint before-rescue
.venv/bin/python -I -m congress_api.cli.pipeline_raw \
  --rescue-batch "$RESCUE" --bucket congressional-tech-raw > "$SAFE_WORK/rescue-result.json"
checkpoint after-rescue
unchanged "$SAFE_WORK/before-rescue-bodies.json" "$SAFE_WORK/after-rescue-bodies.json"
unchanged "$SAFE_WORK/before-rescue-receipts.json" "$SAFE_WORK/after-rescue-receipts.json"
```

**Verify:** download the exact receipt named by the result, check every source identity and referenced body against the plan and listing:

```sh
RECEIPT_KEY=$(jq -er '.receipts | select(length == 1) | .[0]' "$SAFE_WORK/rescue-result.json")
r2 s3api get-object --bucket congressional-tech-raw --key "$RECEIPT_KEY" \
  "$SAFE_WORK/rescue-receipt.gz" > "$SAFE_WORK/rescue-receipt-metadata.json"
.venv/bin/python -I - "$RESCUE" "$SAFE_WORK" <<'PY'
import datetime,gzip,json,pathlib,sys
from urllib.parse import quote
batch,work=map(pathlib.Path,sys.argv[1:])
rows=[json.loads(x) for x in (batch/'files.jsonl').read_text().splitlines()
      if not json.loads(x)['path'].startswith('committee-explorer/')]
commits={r['commit']:r['committed_at'] for r in map(json.loads,(batch/'commits.jsonl').read_text().splitlines())}
lines=[json.loads(x) for x in gzip.decompress((work/'rescue-receipt.gz').read_bytes()).splitlines()]
listing={r['key']:r for r in json.loads((work/'after-rescue-bodies.json').read_text())}
assert len(lines)==len(rows)==2135
for row,line in zip(rows,lines):
    cap,=line['captures']; sha=row['sha256']
    assert line['run_id']=='pipeline-data-rescue-20261027' and line['mode']=='fetch'
    assert line['url']=='https://github.com/civictechdc/congressional-tech/raw/'+row['commit']+'/'+quote(row['path'],safe='/')
    assert line['retrieved_at']==datetime.datetime.fromisoformat(commits[row['commit']]).astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    assert (cap['sha256'],cap['bytes'],cap['git_blob_sha'])==(sha,row['size'],row['git_blob_sha'])
    obj=listing[f"bodies/sha256/{sha[:2]}/{sha}{cap['stored_suffix']}"]
    if 'stored_md5' in cap:
        assert (obj['size'],obj['etag'].strip('"'))==(cap['stored_bytes'],cap['stored_md5'])
assert len({line['url'].split('/raw/')[1].split('/')[0] for line in lines})==35
print('Verified all 2135 receipt lines, 35 snapshot commits and referenced body objects')
PY
```

Rerunning the import on the same UTC date, unchanged batch and exact clean application commit is idempotent. It verifies storage and keeps existing receipt bytes, including original creating facts; it can finish a partial import. Do not change the date/commit to force a retry after midnight: the date guard deliberately stops. Keep the independent copy and arrange a reviewed continuation. **Stop:** interrupt the CLI; completed raw objects remain. Never remove the original batch or existing raw objects to retry.

## 2. B15: secrets, push, merge, enable, first run

**Changes:** GitHub gets the reviewed branch and secrets; merging makes both snapshot-producing workflows preserve raw before pushing. Install secrets **before merging** because the merge itself triggers publication. The names are `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`; enter their values at the secure prompts. `CLOUDFLARE_ACCOUNT_ID` is already public workflow configuration.

```sh
cd "$B15"
gh secret set R2_ACCESS_KEY_ID --repo "$REPO"
gh secret set R2_SECRET_ACCESS_KEY --repo "$REPO"
checkpoint before-b15
git push origin release/b15-weekly-raw
gh pr create --repo "$REPO" --base main --head release/b15-weekly-raw \
  --title 'Preserve pipeline snapshots before every publication' \
  --body 'B15 raw preservation for both workflows, local failure matrix and SDK loopback passed. See docs/measurements/engine-first-20261027/b15/RELEASE.md.'
gh pr merge release/b15-weekly-raw --repo "$REPO" --merge
gh workflow enable publish-explorer.yml --repo "$REPO"
gh workflow enable update-data.yml --repo "$REPO"
gh workflow run publish-explorer.yml --ref main --repo "$REPO"
gh workflow run update-data.yml --ref main --repo "$REPO"
gh run list --repo "$REPO" --workflow update-data.yml --limit 5
gh run list --repo "$REPO" --workflow publish-explorer.yml --limit 5
```

**Verify:** select the new run IDs from those lists and run `gh run watch RUN_ID --exit-status --repo "$REPO"` for any merge-triggered publication, the explicitly dispatched publication, collection and its downstream publication. A workflow disabled at merge time does not receive the merge trigger; the explicit publication dispatch covers that case. Require all four collection save steps and the publication save to preserve raw successfully. Each step's JSON summary names its raw receipt. Finish:

```sh
checkpoint after-b15
unchanged "$SAFE_WORK/before-b15-bodies.json" "$SAFE_WORK/after-b15-bodies.json"
unchanged "$SAFE_WORK/before-b15-receipts.json" "$SAFE_WORK/after-b15-receipts.json"
# Set this from one successful snapshot save's JSON summary (not from its Git ref alone).
: "${B15_RECEIPT_KEY:?Set the exact new raw receipt key from the save step}"
r2 s3api get-object --bucket congressional-tech-raw --key "$B15_RECEIPT_KEY" \
  "$SAFE_WORK/b15-receipt.gz" > "$SAFE_WORK/b15-receipt-metadata.json"
.venv/bin/python -I - "$SAFE_WORK" "$B15_RECEIPT_KEY" <<'PY'
import gzip,json,pathlib,sys
work=pathlib.Path(sys.argv[1]); old={r['key'] for r in json.loads((work/'before-b15-receipts.json').read_text())}
assert sys.argv[2] not in old
listing={r['key']:r for r in json.loads((work/'after-b15-bodies.json').read_text())}
lines=[json.loads(x) for x in gzip.decompress((work/'b15-receipt.gz').read_bytes()).splitlines()]
assert lines and all(x['mode']=='fetch' and x['run_id']!='pipeline-data-rescue-20261027' for x in lines)
commits=set()
for line in lines:
    commits.add(line['url'].split('/raw/')[1].split('/')[0])
    cap,=line['captures']; sha=cap['sha256']
    obj=listing[f"bodies/sha256/{sha[:2]}/{sha}{cap['stored_suffix']}"]
    if 'stored_md5' in cap:
        assert (obj['size'],obj['etag'].strip('"'))==(cap['stored_bytes'],cap['stored_md5'])
assert len(commits)==1
print('Snapshot reached raw; receipt snapshot commit:',next(iter(commits)))
PY
```

For the latest save, compare that printed commit to `gh api repos/civictechdc/congressional-tech/git/ref/heads/pipeline-data --jq .object.sha` before another save overwrites the ref. Earlier saves retain their exact snapshot commit and file identities in raw. Repeat the receipt check for the other successful saves. Local tests prove failure blocks push; only these hosted runs qualify GitHub setup/secrets and actual R2 delivery.

**Stop:** `gh workflow disable update-data.yml --repo "$REPO"` and `gh workflow disable publish-explorer.yml --repo "$REPO"`; cancel active runs with `gh run cancel RUN_ID --repo "$REPO"`. Disabled workflows do not cancel already-running jobs. Keep their raw bodies/receipts.

## 3. B1: qualify lock behavior on a dedicated scratch bucket

**Changes:** creates disposable scratch objects and multipart uploads; no raw object is probed. Set a fresh bucket name, and use a scratch credential that allows ordinary writes/deletes so the lock itself explains the denials.

```sh
cd "$B1"
uv sync --locked
export B1_BUCKET="cx-engine-first-lock-probe-$(date -u +%Y%m%d%H%M%S)"
jq -n --arg name "$B1_BUCKET" '{name:$name}' > "$SAFE_WORK/b1-bucket.json"
curl --fail-with-body --silent --show-error -X POST \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H 'Content-Type: application/json' \
  --data-binary @"$SAFE_WORK/b1-bucket.json" \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/r2/buckets" \
  > "$SAFE_WORK/b1-bucket-created.json"
jq -e '.success' "$SAFE_WORK/b1-bucket-created.json"
cat > "$SAFE_WORK/b1-lock.json" <<'JSON'
{"rules":[{"id":"engine-first-bodies","enabled":true,"prefix":"bodies/","condition":{"type":"Indefinite"}}]}
JSON
cf_locks "$B1_BUCKET" -X PUT -H 'Content-Type: application/json' \
  --data-binary @"$SAFE_WORK/b1-lock.json" > "$SAFE_WORK/b1-lock-put.json"
jq -e '.success == true' "$SAFE_WORK/b1-lock-put.json"
cf_locks "$B1_BUCKET" > "$SAFE_WORK/b1-lock-readback.json"
jq -e '.success and any(.result.rules[]; .prefix=="bodies/" and .enabled and .condition.type=="Indefinite")' \
  "$SAFE_WORK/b1-lock-readback.json"
.venv/bin/python -I -m congress_api.cli.raw_lock_probe --bucket "$B1_BUCKET"
R2_ACCESS_KEY_ID="$B1_R2_ACCESS_KEY_ID" R2_SECRET_ACCESS_KEY="$B1_R2_SECRET_ACCESS_KEY" \
  .venv/bin/python -I -m congress_api.cli.raw_lock_probe --bucket "$B1_BUCKET" --execute \
  > "$SAFE_WORK/b1-result.json"
jq -e '.safe_to_lock == true and .statuses == .expected' "$SAFE_WORK/b1-result.json"
```

**Verify:** supply the scratch access keys through the two `B1_R2_*` environment names before the execute command; its temporary assignments preserve the parent shell's raw credentials for later steps. The **412 must be `create_existing` at the same `bodies/lock-probe/…` key after `create=200`**, meaning the conditional PUT was evaluated rather than rejected by the lock first. Require overwrite/delete 403, multipart initiation/fresh completion 200 and existing-key completion 403, plus CLI exit zero. A 409, 403 instead of 412, incomplete result or credential denial stops raw locking; B3/ARCH §7.1 must be reviewed if the duplicate create is not 412. [B1 details](b1/RELEASE.md).

**Stop:** interrupt the probe and retain all output; do not apply raw locks on failure. Leave its locked objects alone. M1 uses a different bucket with no lock on its table prefix.

## 4. Lock bodies and provenance, then read back

**Changes:** only raw bucket configuration. First record every `provenance/` object outside the timestamp-record convention. Do not rename, delete or rewrite exceptions.

```sh
inventory provenance/ "$SAFE_WORK/provenance-before-lock.json"
jq '[.[] | select(.key | test("^provenance/[^/]+/[0-9]{8}T[0-9]{6}Z[^/]*\\.jsonl$") | not)]' \
  "$SAFE_WORK/provenance-before-lock.json" > "$SAFE_WORK/provenance-exceptions.json"
cat "$SAFE_WORK/provenance-exceptions.json"
cf_locks congressional-tech-raw > "$SAFE_WORK/raw-lock-before.json"
jq -e '.success and (.result.rules | type == "array")' "$SAFE_WORK/raw-lock-before.json"
jq '{rules: ((.result.rules | map(select(.id!="engine-first-bodies" and .id!="engine-first-provenance"))) + [
  {id:"engine-first-bodies",enabled:true,prefix:"bodies/",condition:{type:"Indefinite"}},
  {id:"engine-first-provenance",enabled:true,prefix:"provenance/",condition:{type:"Indefinite"}}
])}' "$SAFE_WORK/raw-lock-before.json" > "$SAFE_WORK/raw-lock-next.json"
cat "$SAFE_WORK/raw-lock-next.json"
```

Record the reason for every exception in `$SAFE_WORK/provenance-exceptions-reviewed.txt`; check the complete existing rule list before the next block. An existing rule covering `receipts/` would prevent B0; stop for the owner to resolve it. Keep bucket-configuration changes serialized through this procedure because the API replaces the whole rule list. The generated configuration retains existing unrelated rules.

```sh
test -s "$SAFE_WORK/provenance-exceptions-reviewed.txt"
cf_locks congressional-tech-raw -X PUT -H 'Content-Type: application/json' \
  --data-binary @"$SAFE_WORK/raw-lock-next.json" > "$SAFE_WORK/raw-lock-put.json"
jq -e '.success' "$SAFE_WORK/raw-lock-put.json"
cf_locks congressional-tech-raw > "$SAFE_WORK/raw-lock-readback.json"
jq -e '.success and (.result.rules as $rules | all(["bodies/","provenance/"][];
  . as $prefix | any($rules[]; .prefix==$prefix and .enabled and .condition.type=="Indefinite")))' \
  "$SAFE_WORK/raw-lock-readback.json"
```

**Verify:** both exact prefixes have enabled `Indefinite` rules; confirm all earlier unrelated rules remain. **Stop:** do not PUT until B1 and the provenance review pass; on failed readback stop all following work and inspect configuration. Do not remove a raw lock to make a writer succeed.

Bucket-lock fields and GET/PUT routes were checked against [Cloudflare's API](https://developers.cloudflare.com/api/resources/r2/subresources/buckets/subresources/locks/methods/update/) and [bucket-lock documentation](https://developers.cloudflare.com/r2/buckets/bucket-locks/).

## 5. B0: deploy old writers, drain, rewrite, rescan, then lock receipts

**Changes:** deployment applies the public-receipt policy at both legacy writer emission points. The cleanup makes only the two approved privacy edits to old receipts, keeps durable originals on the owner's disk, replaces with `If-Match`, reads back, and adds verification records under `provenance/verification/`. Bodies never change. Historical scan: 2,289 receipts, 887 changed; use the live inventory as current authority.

```sh
cd "$B0"
uv sync --locked
git push origin release/b0-old-writers
gh pr create --repo "$REPO" --base main --head release/b0-old-writers \
  --title 'Protect public receipts and release the one-time cleanup' \
  --body 'Shared privacy repair for running capture/recovery writers, durable originals, conditional rewrite and complete rescan. See B0 README.'
gh pr merge release/b0-old-writers --repo "$REPO" --merge
gh workflow disable capture-raw-sources.yml --repo "$REPO"
gh workflow disable update-data.yml --repo "$REPO"
gh workflow disable publish-explorer.yml --repo "$REPO"
gh run list --repo "$REPO" --status in_progress --limit 100
gh run list --repo "$REPO" --status queued --limit 100
```

Pause local recovery imports and every other raw writer. Cancel/drain listed writer runs using `gh run cancel RUN_ID --repo "$REPO"` and `gh run watch RUN_ID --repo "$REPO"`; the merge-triggered publication must also finish/cancel. A workflow disable alone does not drain jobs. Confirm old revisions are stopped and future jobs use the merged B0 code. Approve the two patterns and examples in `b0/scan.json` before applying the cleanup. The release's focused tests cover both old-writer entry points; first live use still needs before/after raw listings while receipts are unlocked.

```sh
export B0_WORK="$SAFE_WORK/b0"
mkdir "$B0_WORK"
checkpoint before-b0
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw \
  --list-inventory --inventory "$B0_WORK/keys.json" --report "$B0_WORK/listing-before.json"
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw \
  --inventory "$B0_WORK/keys.json" --backup-root "$B0_WORK/originals" --scratch "$B0_WORK/work" \
  --records "$B0_WORK/verification.jsonl" --report "$B0_WORK/rewrite.json" --apply
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw \
  --list-inventory --inventory "$B0_WORK/final-keys.json" --report "$B0_WORK/listing-final.json"
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw \
  --inventory "$B0_WORK/final-keys.json" --backup-root "$B0_WORK/originals" --scratch "$B0_WORK/work" \
  --records "$B0_WORK/verification.jsonl" --report "$B0_WORK/final-rewrite.json" --apply
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw \
  --scan-live --inventory "$B0_WORK/final-keys.json" --mirror-root "$B0_WORK/final-mirror" \
  --report "$B0_WORK/final-scan.json"
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw \
  --list-inventory --inventory "$B0_WORK/lock-keys.json" --report "$B0_WORK/listing-final-readback.json"
checkpoint after-b0
unchanged "$SAFE_WORK/before-b0-bodies.json" "$SAFE_WORK/after-b0-bodies.json"
.venv/bin/python -I - "$B0_WORK" <<'PY'
import json,pathlib,sys
work=pathlib.Path(sys.argv[1]); scan=json.loads((work/'final-scan.json').read_text())
keys=set(json.loads((work/'final-keys.json').read_text()))
records={r['key']:r for r in map(json.loads,(work/'verification.jsonl').read_text().splitlines())}
listing={r['key']:r for r in json.loads((work/'listing-final-readback.json').read_text())}
assert keys==set(json.loads((work/'lock-keys.json').read_text()))
assert scan['counts']=={} and scan['receipts']==len(keys)
assert keys==set(records)==set(listing)
for key in keys:
    record=records[key]; current=listing[key]
    assert record['verified'] is True
    assert (record['etag'],record['size'])==(current['etag'],current['size'])
print('Every final receipt has verified readback; complete scan has zero matches')
PY
```

Keep all writers paused. Require the final receipt listing to match exactly the keys just scanned; if new receipts appeared, repeat final listing/rewrite/scan and coverage checks before locking. Backups and verification logs must remain on durable storage.

```sh
cf_locks congressional-tech-raw > "$SAFE_WORK/receipt-lock-before.json"
jq -e '.success' "$SAFE_WORK/receipt-lock-before.json"
jq '{rules: ((.result.rules | map(select(.id!="engine-first-receipts"))) + [
  {id:"engine-first-receipts",enabled:true,prefix:"receipts/",condition:{type:"Indefinite"}}
])}' "$SAFE_WORK/receipt-lock-before.json" > "$SAFE_WORK/receipt-lock-next.json"
cf_locks congressional-tech-raw -X PUT -H 'Content-Type: application/json' \
  --data-binary @"$SAFE_WORK/receipt-lock-next.json" > "$SAFE_WORK/receipt-lock-put.json"
jq -e '.success' "$SAFE_WORK/receipt-lock-put.json"
cf_locks congressional-tech-raw > "$SAFE_WORK/receipt-lock-readback.json"
jq -e '.success and ([.result.rules[] | select(.enabled and .condition.type=="Indefinite") | .prefix]
  | contains(["bodies/","receipts/","provenance/"]))' "$SAFE_WORK/receipt-lock-readback.json"
```

**Verify:** read all three indefinite rules back before restoring schedules. Download the `provenance_key` from `final-rewrite.json` and compare its per-key verification facts to the durable local log, using the command below. After an intended schedule resumes, checkpoint before/after its first run and require additions only.

```sh
B0_PROVENANCE_KEY=$(jq -er '.provenance_key' "$B0_WORK/final-rewrite.json")
r2 s3api get-object --bucket congressional-tech-raw --key "$B0_PROVENANCE_KEY" \
  "$B0_WORK/verification-raw.jsonl" > "$B0_WORK/verification-raw-metadata.json"
.venv/bin/python -I - "$B0_WORK" <<'PY'
import json,pathlib,sys
work=pathlib.Path(sys.argv[1])
def records(name):
    return {r['key']:r for r in map(json.loads,(work/name).read_text().splitlines())}
assert records('verification-raw.jsonl')==records('verification.jsonl')
print('Raw verification provenance matches durable local records')
PY
```


**Stop:** interrupt cleanup on any backup, sync, race, readback or coverage failure. Keep writers paused, keep backups/logs, rerun the exact inventory with the same `--backup-root` and `--records` to reconcile safely. Do not lock receipts while cleanup is incomplete. Do not delete backups to restart. Restore only the workflows previously enabled, using `gh workflow enable NAME --repo "$REPO"`; restore local import jobs separately.

## 6. M1 smoke in a separate dedicated scratch bucket

**Changes:** only the dedicated Basin scratch bucket/catalog: create `growth`, append days 0–2, verify all columns/rows, race on empty days 3–4, purge the scratch table, and list remaining objects. The `cx-engine-first-lock-probe-` bucket guard stays. Use a **different unlocked scratch bucket** from B1; no raw storage or managed-maintenance trial is involved.

The owner supplies `DOCSPEC_M1_BUCKET`, `DOCSPEC_M1_CATALOG_URI` (ending in that bucket), `DOCSPEC_M1_WAREHOUSE`, `DOCSPEC_M1_S3_ENDPOINT`, `DOCSPEC_M1_CATALOG_TOKEN`, `DOCSPEC_M1_ACCESS_KEY_ID`, `DOCSPEC_M1_SECRET_ACCESS_KEY` in the environment. The script never reads credential values or passes them as command arguments.

```sh
cd "$M1"
uv sync --locked
# Set M1_PROBE and M1_PROBE_SHA256 from m1/RELEASE.md's immutable artifact pin.
: "${M1_PROBE:?Set the optimized probe binary path}"
: "${M1_PROBE_SHA256:?Set the artifact SHA-256}"
.venv/bin/python -I scripts/m1_smoke.py --binary "$M1_PROBE" \
  --binary-sha256 "$M1_PROBE_SHA256" --work "$SAFE_WORK/m1-plan"
.venv/bin/python -I scripts/m1_smoke.py --binary "$M1_PROBE" \
  --binary-sha256 "$M1_PROBE_SHA256" --work "$SAFE_WORK/m1-live" --execute
cat "$SAFE_WORK/m1-live/summary.json" "$SAFE_WORK/m1-live/remaining.json"
```

**Verify:** `observe.json` has `rows_equal=true`, 300 rows; `race.json` has `server_snapshot_conflict=true`, no duplicates, zero repeat work/commits, and at most three retries. All reports identify the same release binary and table; `purge.json` contains the actual post-purge listing, copied to `remaining.json`. Remaining orphans are reported for owner review, never silently deleted. This run qualifies the remote smoke; fake-process tests qualify only the wrapper.

**Stop:** interrupt at any failed step, retain the whole work directory, and report its last action. There is no automatic purge after failure. A new full attempt needs a fresh namespace/work directory; use the saved `plan.json` to identify the failed namespace for a separately reviewed scoped purge. Never remove the bucket guard or point the script at raw.
