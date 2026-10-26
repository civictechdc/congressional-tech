"""Keep every version of the source records on the `pipeline-data` branch.

`.github/scripts/save-pipeline-data.sh` replaces that branch with an orphan commit on
every push, so each older snapshot survives only as an unreferenced commit that GitHub
still serves by SHA. GitHub's events API names those SHAs for a few weeks (at most 300
events or 90 days). This script reads them and stores each distinct source file once,
content-addressed by SHA-256, until B15 moves these fetches into the fetcher and one
import run moves this batch into raw.

Idempotent: re-run it at least weekly; it skips commits already recorded.
Usage: python -I rescue_pipeline_data.py <data_dir>
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

REPO = 'civictechdc/congressional-tech'
REF = 'refs/heads/pipeline-data'
SKIP_PREFIXES = ('committee-explorer/',)  # build output, rebuilt from the sources
PAUSE = 0.25  # at most 4 requests a second


def gh(path, raw=False):
    time.sleep(PAUSE)
    args = ['gh', 'api', path]
    if raw:
        args += ['-H', 'Accept: application/vnd.github.raw']
    out = subprocess.run(args, check=True, capture_output=True).stdout
    return out if raw else json.loads(out)


def pushed_commits():
    seen = {}
    page = 1
    while True:
        events = gh(f'repos/{REPO}/events?per_page=100&page={page}')
        if not events:
            break
        for event in events:
            payload = event.get('payload', {})
            if event['type'] == 'PushEvent' and payload.get('ref') == REF:
                seen.setdefault(payload['head'], event['created_at'])
        page += 1
        if page > 3:  # the API serves at most 300 events
            break
    head = gh(f'repos/{REPO}/git/ref/heads/pipeline-data')['object']['sha']
    seen.setdefault(head, None)
    return seen


def append(path, row):
    with open(path, 'a') as file:
        file.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')


def main(data_dir):
    data = pathlib.Path(data_dir)
    blobs = data / 'blobs'
    blobs.mkdir(parents=True, exist_ok=True)
    commits_path, files_path = data / 'commits.jsonl', data / 'files.jsonl'
    done = set()
    if commits_path.exists():
        done = {json.loads(line)['commit'] for line in commits_path.read_text().splitlines()}
    by_git_sha = {}
    if files_path.exists():
        for line in files_path.read_text().splitlines():
            row = json.loads(line)
            by_git_sha[row['git_blob_sha']] = row['sha256']
    new_commits = new_blobs = 0
    for commit, pushed_at in sorted(pushed_commits().items(), key=lambda item: item[1] or '~'):
        if commit in done:
            continue
        meta = gh(f'repos/{REPO}/git/commits/{commit}')
        tree = gh(f'repos/{REPO}/git/trees/{meta["tree"]["sha"]}?recursive=1')
        if tree.get('truncated'):
            raise SystemExit(f'tree truncated for {commit}; fetch it by subtree')
        for entry in tree['tree']:
            if entry['type'] != 'blob' or entry['path'].startswith(SKIP_PREFIXES):
                continue
            sha256 = by_git_sha.get(entry['sha'])
            if sha256 is None:
                body = gh(f'repos/{REPO}/git/blobs/{entry["sha"]}', raw=True)
                git_sha = hashlib.sha1(b'blob %d\0' % len(body) + body).hexdigest()
                if git_sha != entry['sha'] or len(body) != entry['size']:
                    raise SystemExit(f'blob mismatch for {entry["path"]} in {commit}')
                sha256 = hashlib.sha256(body).hexdigest()
                target = blobs / sha256
                if not target.exists():
                    tmp = target.with_suffix('.tmp')
                    tmp.write_bytes(body)
                    os.replace(tmp, target)
                    new_blobs += 1
                by_git_sha[entry['sha']] = sha256
            append(files_path, dict(commit=commit, path=entry['path'], git_blob_sha=entry['sha'],
                                    size=entry['size'], sha256=sha256))
        append(commits_path, dict(commit=commit, pushed_at=pushed_at, tree=meta['tree']['sha'],
                                  committed_at=meta['committer']['date'], message=meta['message'],
                                  recorded_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
        new_commits += 1
    print(json.dumps(dict(new_commits=new_commits, new_blobs=new_blobs,
                          stored_blobs=len(list(blobs.iterdir())))))


if __name__ == '__main__':
    main(sys.argv[1])
