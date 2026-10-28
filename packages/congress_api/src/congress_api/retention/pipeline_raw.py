"""Keep every pipeline-data snapshot in raw: create-only bodies, then one receipt.

The weekly job force-pushes ``pipeline-data`` as one orphan commit so git never
accumulates history. Raw keeps the versions instead ([[ARCHITECTURE]] §7.1-7.2,
[[DATA-MODEL]] §5.1-5.2): each file's bytes go to ``bodies/sha256/<aa>/<sha>``
with one create-only PUT, where a 412 means the body already exists, and a
receipt with one line per file follows the bodies.
"""
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import uuid4
from urllib.parse import quote

from congress_api.retention.body_files import CHUNK, file_digest

FAMILY = 'pipeline-data'
SKIP_PREFIXES = ('committee-explorer/',)  # Build output, rebuilt from the records.
REPOSITORY = 'https://github.com/civictechdc/congressional-tech'
BRANCH = 'pipeline-data'
RECEIPT_LINES = 50_000
RESCUE_RUN_ID = 'pipeline-data-rescue-20261027'
MEDIA_TYPES = {
    '.json': 'application/json', '.jsonl': 'application/x-ndjson', '.xml': 'application/xml',
    '.html': 'text/html', '.htm': 'text/html', '.csv': 'text/csv', '.md': 'text/markdown',
    '.txt': 'text/plain', '.gz': 'application/gzip',
}
COMPRESSIBLE = {'application/json', 'application/x-ndjson', 'application/xml'}


@dataclass(frozen=True)
class SnapshotFile:
    """One file of one snapshot commit, with the values its source already records."""
    commit: str
    committed_at: str
    path: str
    git_blob_sha: str
    size: int
    source: Path
    sha256: str | None = None


def media_type(path):
    return MEDIA_TYPES.get(Path(path).suffix.lower(), 'application/octet-stream')


def compressible(media):
    return media.startswith('text/') or media in COMPRESSIBLE


def body_key(sha256):
    return f'bodies/sha256/{sha256[:2]}/{sha256}'


def new_run_id(now=None):
    """The raw writers' run-ID form; the random part keeps every run's ID unused."""
    now = now or datetime.now(timezone.utc)
    return now.strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:12]


def utc(timestamp):
    return datetime.fromisoformat(timestamp).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _git(directory, *args):
    return subprocess.run(['git', '-C', str(directory), *args], check=True,
                          capture_output=True).stdout


def checkout_files(directory):
    """The files of a checkout's HEAD commit, as git recorded them."""
    directory = Path(directory)
    commit = _git(directory, 'rev-parse', 'HEAD').decode().strip()
    committed_at = utc(_git(directory, 'show', '-s', '--format=%cI', 'HEAD').decode().strip())
    for entry in _git(directory, 'ls-tree', '-r', '-l', '-z', 'HEAD').split(b'\0'):
        if not entry:
            continue
        meta, path = entry.decode().split('\t', 1)
        mode, kind, blob, size = meta.split()
        if kind != 'blob' or mode not in {'100644', '100755'}:
            raise ValueError(f'Unsupported snapshot entry {mode} {kind}: {path}')
        yield SnapshotFile(commit, committed_at, path, blob, int(size), directory / path)


def rescue_files(batch):
    """The files of a content-addressed rescue batch; never writes to it."""
    batch = Path(batch)
    commits = {}
    with (batch / 'commits.jsonl').open() as source:
        for line in source:
            row = json.loads(line)
            commits[row['commit']] = utc(row['committed_at'])
    with (batch / 'files.jsonl').open() as source:
        for line in source:
            row = json.loads(line)
            yield SnapshotFile(row['commit'], commits[row['commit']], row['path'],
                               row['git_blob_sha'], row['size'],
                               batch / 'blobs' / row['sha256'], row['sha256'])


def selected(files):
    kept, skipped = [], 0
    for item in files:
        if item.path.startswith(SKIP_PREFIXES):
            skipped += 1
        else:
            kept.append(item)
    return kept, skipped


def stored_body(item, scratch):
    """Read a file once: its identity, git blob ID and the bytes R2 will store.

    Compressible files are gzipped into ``scratch``; others upload from their source.
    """
    encoded = compressible(media_type(item.path))
    sha256, blob, md5 = hashlib.sha256(), hashlib.sha1(b'blob %d\0' % item.size), hashlib.md5()
    size = 0
    with contextlib.ExitStack() as stack:
        source = stack.enter_context(item.source.open('rb'))
        if encoded:
            destination = stack.enter_context(scratch.open('wb'))
            md5_destination = _Md5Writer(destination, md5)
            writer = stack.enter_context(gzip.GzipFile(
                filename='', fileobj=md5_destination, mode='wb', compresslevel=6, mtime=0))
        while chunk := source.read(CHUNK):
            size += len(chunk)
            sha256.update(chunk)
            blob.update(chunk)
            if encoded:
                writer.write(chunk)
            else:
                md5.update(chunk)
    sha256 = sha256.hexdigest()
    if (size, blob.hexdigest(), sha256) != (item.size, item.git_blob_sha, item.sha256 or sha256):
        raise ValueError(f'{item.commit}:{item.path} does not match its recorded identity')
    stored = scratch if encoded else item.source
    return sha256, md5, stored, stored.stat().st_size, encoded


class _Md5Writer:
    """Hash the stored (compressed) bytes as they are written: R2's ETag is their MD5."""

    def __init__(self, destination, md5):
        self.destination, self.md5 = destination, md5

    def write(self, data):
        self.md5.update(data)
        return self.destination.write(data)

    def flush(self):
        self.destination.flush()


def receipt_line(item, *, run_id, writer, sha256, outcome, stored=None, suffix=''):
    """One [[DATA-MODEL]] §5.2 fetch line for one snapshot file."""
    # A git filename is a path, never a URL query or fragment. Keep local source
    # paths out of the public record and encode URL punctuation in git names.
    path = quote(item.path, safe='/')
    url = f'{REPOSITORY}/raw/{item.commit}/{path}'
    capture = dict(
        pointer=['content', 'body'], attempt=0, complete=True, context_url=url,
        member_path=None, entry_index=None, expansion=None, sha256=sha256, bytes=item.size,
        media_type=media_type(item.path), sniffed_format=None, sniff_version=None, intact=None,
        stored_suffix=suffix, fidelity='saved-record', git_blob_sha=item.git_blob_sha,
    )
    if stored:
        capture.update(stored_md5=stored[0], stored_bytes=stored[1])
    return dict(
        run_id=run_id, mode='fetch', family=FAMILY,
        requested_url=f'{REPOSITORY}/raw/{BRANCH}/{path}', url=url,
        retrieved_at=item.committed_at, http_status=None, provider_status=None,
        outcome=outcome, transport='git', response_headers={}, redirects=[], prior_attempts=[],
        source_context=dict(observations=[]), writer=writer, captures=[capture],
    )


def receipt_keys(run_id, count, day):
    return [f'receipts/{FAMILY}/{day}/{run_id}-{seq:06d}.jsonl.gz'
            for seq in range(1, -(-count // RECEIPT_LINES) + 1)]


def plan(files):
    """Counts and body keys, with no network; hashes only files without a recorded SHA-256."""
    kept, skipped = selected(files)
    bodies = {item.sha256 or file_digest(item.source): item for item in kept}
    return dict(snapshots=len({item.commit for item in kept}), files=len(kept), skipped=skipped,
                file_bytes=sum(item.size for item in kept), bodies=len(bodies),
                body_bytes=sum(item.size for item in bodies.values()),
                missing=sum(not item.source.is_file() for item in bodies.values()),
                compressible=sum(compressible(media_type(item.path)) for item in bodies.values()),
                body_keys=sorted(map(body_key, bodies)))


def archive(store, files, *, writer, run_id=None, day=None):
    """Store each distinct body once, then the run's receipt; returns a summary."""
    if (set(writer) != {'job', 'commit', 'lockfile_digest'}
            or any(not isinstance(value, str) for value in writer.values())
            or not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?', writer['job'])
            or not re.fullmatch(r'[0-9a-f]{40}', writer['commit'])
            or not re.fullmatch(r'[0-9a-f]{64}', writer['lockfile_digest'])):
        raise ValueError('Invalid public receipt writer identity')
    run_id = run_id or new_run_id()
    kept, skipped = selected(files)
    lines, known, created = [], {}, 0
    with tempfile.TemporaryDirectory(prefix='pipeline-raw-') as scratch:
        scratch = Path(scratch) / 'body'
        for item in kept:
            if item.sha256 in known:
                lines.append(receipt_line(item, run_id=run_id, writer=writer,
                                          sha256=item.sha256, outcome='unchanged',
                                          suffix=known[item.sha256].suffix))
                continue
            sha256, md5, stored_path, stored_bytes, encoded = stored_body(item, scratch)
            if sha256 in known:
                outcome, stored = 'unchanged', None
            else:
                result = store.raw.put_prepared(
                    body_key(sha256), stored_path, media_type(item.path),
                    encoding='gzip' if encoded else None,
                    expected_md5=md5.hexdigest(), expected_size=stored_bytes)
                fresh = result.outcome == 'stored'
                known[sha256] = result
                created += fresh
                outcome, stored = ('stored', (result.md5, result.size)) if fresh \
                    else ('unchanged', None)
            lines.append(receipt_line(item, run_id=run_id, writer=writer, sha256=sha256,
                                      outcome=outcome, stored=stored, suffix=known[sha256].suffix))
            scratch.unlink(missing_ok=True)
    day = day or datetime.now(timezone.utc).date().isoformat()
    keys = receipt_keys(run_id, len(lines), day)
    for index, key in enumerate(keys):
        payload = ''.join(json.dumps(line, ensure_ascii=False, separators=(',', ':')) + '\n'
                          for line in lines[index * RECEIPT_LINES:(index + 1) * RECEIPT_LINES])
        # A 412 here means a reused run ID: R2Store.put raises, failing the run.
        store.put(key, gzip.compress(payload.encode(), mtime=0), immutable=True)
    return dict(run_id=run_id, files=len(lines), skipped=skipped, bodies=len(known),
                created=created, existing=len(known) - created, receipts=keys)
