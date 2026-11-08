"""Select one public archive release and hold the files it names, checked against its manifest.

The pointer names the release; the manifest's content digest is the release identity, and
every file is kept only when its sha256 and size equal the manifest's entry. A local release
directory (``manifest.json`` beside its files) is read in place under the same checks.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from congress_api.retention.body_store import validate_record

PUBLIC_POINTER = 'https://congressional-data.spicygov.ai/viewer-publications/manifest.json'
HEX = re.compile('[0-9a-f]{64}')
RELEASE_FILE_BYTES = 128 << 20


def file_identity(path, entry):
    """Refuse a file whose bytes differ from its manifest entry."""
    with Path(path).open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
        size = source.tell()
    if (digest, size) != (entry['sha256'], entry['size']):
        raise ValueError('Release file identity or size differs from the manifest')


def download(session, url, path, limit):
    if urlsplit(url).scheme != 'https':
        raise ValueError('Release URLs must use HTTPS')
    validate_record(url)
    with session.get(url, stream=True, allow_redirects=False, timeout=(15, 120), headers={'Cache-Control': 'no-cache'}) as response:
        response.raise_for_status()
        size = 0
        with Path(path).open('xb') as out:
            for chunk in response.iter_content(chunk_size=1 << 20):
                size += len(chunk)
                if size > limit:
                    raise ValueError('Release download exceeds its byte allowance')
                out.write(chunk)
    return Path(path)


def open_release(*, work, release_root=None, pointer=None, session=None):
    """Return ``(release_id, manifest, fetch)``; ``fetch(name)`` gives a verified local path.

    Reads the pointer and manifest once. ``fetch`` downloads (or locates) one named file
    and refuses a missing, unbounded or altered one.
    """
    if (release_root is None) == (pointer is None):
        raise ValueError('Select a public pointer or a local release root')
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    if pointer:
        if session is None:
            import requests
            session = requests.Session()
        selected = json.loads(download(session, pointer, work / 'pointer.json', 1 << 20).read_text())
        release_id = selected.get('release_id')
        if not isinstance(release_id, str) or not HEX.fullmatch(release_id):
            raise ValueError('Invalid public release pointer')
        base = urljoin(pointer, f'releases/{release_id}/')
        manifest = json.loads(download(session, urljoin(base, 'manifest.json'), work / 'manifest.json', 2 << 20).read_text())
    else:
        release_root = Path(release_root).resolve()
        manifest = json.loads((release_root / 'manifest.json').read_text())
        release_id = manifest.get('release_id')
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or manifest.get('release_id') != release_id or not HEX.fullmatch(release_id or ''):
        raise ValueError('Unsupported release manifest or identity')
    files = manifest.get('files')
    if not isinstance(files, list) or any(not isinstance(row, dict) or not all(key in row for key in ('name', 'sha256', 'size', 'rows')) for row in files):
        raise ValueError('Invalid release file manifest')
    if len({row['name'] for row in files}) != len(files):
        raise ValueError('Duplicate release file name')
    actual = hashlib.sha256(json.dumps([1, [[row[k] for k in ('name', 'sha256', 'size', 'rows')] for row in files]],
                                       ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    if actual != release_id:
        raise ValueError('Release manifest content identity differs')
    entries = {row['name']: row for row in files}

    def fetch(name):
        entry = entries.get(name)
        if (entry is None or not isinstance(entry['sha256'], str) or not HEX.fullmatch(entry['sha256'])
                or type(entry['size']) is not int or not 0 <= entry['size'] <= RELEASE_FILE_BYTES):
            raise ValueError(f'Release {release_id} omits a bounded {name}')
        if pointer:
            path = download(session, urljoin(base, name), work / name, entry['size'])
        else:
            path = (release_root / name).resolve()
            if not path.is_relative_to(release_root):
                raise ValueError('Release input escapes its root')
        file_identity(path, entry)
        return path

    return release_id, manifest, fetch


def release_meetings(release, *, work, scope):
    """Meetings in scope from a release (an https pointer or a local release directory).

    Replaces the weekly ``congress_meetings.jsonl.gz`` snapshot for ``gpo-match`` and
    ``congress-committees`` (ct-0mqc). Refuses, never returns empty: an unreachable,
    altered or meeting-less release would otherwise drop every Congress.gov link,
    event-ID match and Congress number from their output without a failure.
    """
    from congress_api.retention.meetings import read_release_meetings
    is_url = str(release).startswith(('https://', 'http://'))
    try:
        release_id, _, fetch = open_release(work=work, pointer=str(release) if is_url else None,
                                            release_root=None if is_url else release)
        meetings = list(read_release_meetings(fetch('meetings.parquet'), fetch('committees.parquet'), scope=scope))
    except (OSError, ValueError, KeyError) as error:
        raise ValueError(f'No usable meetings source at {release}: {error}') from error
    if not meetings:
        raise ValueError(f'Release {release_id} at {release} holds no meetings in scope')
    return meetings
