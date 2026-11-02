"""Regenerate a published release's run inputs from its own published input record.

    release_input_custody.py collect --release ID --input-digest D --mirror ROOT --out DIR [--threads 16]
    release_input_custody.py verify --captures PARQUET --counts COUNTS.json --work DIR

`collect` reads only the public origin: the release's input record and receipt list (canonical digest
checked), one HEAD per receipt (ETag, size), GETs of the provenance record files the record names, and
GETs of receipts absent from the mirror. Every GET of a single-PUT object must match its ETag MD5 and
size before it lands. Every receipt gets a byte qualification, since batch writers bind each selected file:
a single-PUT receipt's mirror MD5 must equal its ETag; a multipart (opaque) one needs a second copy, the
origin's bytes hashed while streaming, equal to the mirror file's SHA-256 and size. Writes receipt-inventory.json
(rows for cxb_capture_source_counts.py --files and --receipt-inventory), source-qualifications.json,
provenance.json (selective-spec pins) and manifest.json. No credentials; never writes remotely.

`verify` runs the production capture guard (capture_backfill_guard.validate_generation) over a captures
parquet with the independent counts, so per-receipt counts are compared both ways by the same code the
backfill uses. Cost: O(R) HEADs plus one local read of every receipt;
origin bytes only for missing or opaque receipts and provenance files.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import md5, sha256
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ORIGIN = 'https://congressional-data.spicygov.ai/'
AGENT = 'congressional-tech-measure/1'  # The CDN refuses Python's default agent.
RELEASES = 'viewer-publications/releases/'
KINDS = ('recoveries', 'reviews', 'unreadable')


def _request(key, method='GET', *, opener=urlopen, attempts=5):
    for attempt in range(attempts):
        try:
            return opener(Request(ORIGIN + key, method=method, headers={'User-Agent': AGENT}), timeout=120)
        except HTTPError:
            raise  # A status is an answer; only transport failures are retried.
        except (URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def single_put(etag):
    from congress_shared.storage import single_put_md5
    try:
        return single_put_md5(etag)
    except ValueError:
        return None


def head(key, *, opener=urlopen):
    with _request(key, 'HEAD', opener=opener) as response:
        return dict(key=key, etag=response.headers['ETag'], size=int(response.headers['Content-Length']))


def fetch(key, target, *, opener=urlopen, expected=None):
    """Stream one object to target; refuse unless size and any single-PUT MD5 match its ETag."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.partial')
    digests = dict(md5=md5(), sha256=sha256())
    with _request(key, opener=opener) as response, partial.open('wb') as out:
        etag, size = response.headers['ETag'], int(response.headers['Content-Length'])
        count = 0
        while chunk := response.read(1 << 20):
            count += len(chunk)
            out.write(chunk)
            for digest in digests.values():
                digest.update(chunk)
    checksum = single_put(etag)
    if count != size or (checksum is not None and digests['md5'].hexdigest() != checksum) or (
            expected is not None and (single_put(expected) or expected) != (checksum or etag)):
        partial.unlink()
        raise ValueError('Origin object failed its ETag or size check: ' + key)
    partial.replace(target)
    return dict(key=key, path=str(target.resolve()), etag=etag, size=size, sha256=digests['sha256'].hexdigest())


def origin_sha256(key, *, opener=urlopen):
    digest = sha256()
    count = 0
    with _request(key, opener=opener) as response:
        while chunk := response.read(1 << 20):
            count += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), count


def _file_sha256(path):
    from hashlib import file_digest
    with Path(path).open('rb') as source:
        return file_digest(source, 'sha256').hexdigest()


def _file_digests(path):
    """SHA-256 and MD5 in one read of the file."""
    digests = sha256(), md5()
    with Path(path).open('rb') as source:
        while chunk := source.read(1 << 20):
            for digest in digests:
                digest.update(chunk)
    return tuple(digest.hexdigest() for digest in digests)


def input_record(release, digest, *, opener=urlopen):
    """The release's input record and its receipt keys, verified by canonical digest."""
    from viewer_publication.receipt_pins import read_receipt_list
    prefix = RELEASES + release + '/inputs/'
    with _request(prefix + digest + '.json', opener=opener) as response:
        raw = response.read()
        checksum = single_put(response.headers['ETag'])
    if checksum is not None and md5(raw).hexdigest() != checksum:
        raise ValueError('Input record differs from its ETag')
    record = json.loads(raw)
    if record.get('input_digest') != digest:
        raise ValueError('Input record identity differs from its key')
    with _request(prefix + 'receipts/' + record['receipt_keys_sha256'] + '.json.gz', opener=opener) as response:
        keys = read_receipt_list(record['receipt_keys_sha256'], response.read())
    return record, keys


def provenance_kind(key):
    parts = key.split('/')
    if len(parts) == 3 and parts[0] == 'provenance' and parts[1] in KINDS and parts[2].endswith('.jsonl') and parts[2][:-6]:
        return parts[1]
    return None


def collect(*, release, input_digest, mirror, out, threads=16, opener=urlopen):
    mirror, out = Path(mirror).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    record, keys = input_record(release, input_digest, opener=opener)
    with ThreadPoolExecutor(threads) as pool:
        heads = list(pool.map(lambda key: head(key, opener=opener), keys))
    fetched, opaque, qualifications = [], [], {}
    inventory = []
    for row in heads:
        path = mirror / row['key']
        if not path.is_file():
            fetched.append(fetch(row['key'], path, opener=opener, expected=row['etag'])['key'])
        if path.stat().st_size != row['size']:
            raise ValueError('Mirror receipt size differs from origin: ' + row['key'])
        checksum = single_put(row['etag'])
        local, local_md5 = _file_digests(path)
        if checksum is None:
            # Opaque ETag: an independent copy's bytes must equal the mirror's.
            remote, size = origin_sha256(row['key'], opener=opener)
            if (remote, size) != (local, row['size']):
                raise ValueError('Mirror receipt bytes differ from origin: ' + row['key'])
            note = 'origin GET sha256 equals mirror sha256; ETag ' + row['etag']
            opaque.append(row['key'])
        elif local_md5 != checksum:
            raise ValueError('Mirror receipt MD5 differs from its ETag: ' + row['key'])
        else:
            note = 'mirror MD5 equals single-PUT ETag ' + row['etag']
        # Every receipt gets an authority: batch writers bind each selected file exactly.
        authority = out / 'qualifications' / (sha256(row['key'].encode()).hexdigest() + '.json')
        authority.parent.mkdir(parents=True, exist_ok=True)
        authority.write_text(json.dumps(dict(path=str(path.resolve()), sha256=local, size=row['size'],
            producer='release_input_custody.py', note=note), sort_keys=True) + '\n')
        qualifications[str(path.resolve())] = str(authority)
        inventory.append(dict(key=row['key'], path=str(path.resolve()), size=row['size'], etag=row['etag']))
    provenance = {kind: [] for kind in KINDS}
    for item in record.get('provenance', []):
        kind = provenance_kind(item['key'])
        if kind is None:
            continue  # Backups and other raw provenance stay identity metadata, as in the model job.
        row = fetch(item['key'], out / item['key'], opener=opener, expected=item['etag'])
        provenance[kind].append({k: row[k] for k in ('key', 'path', 'sha256', 'size')})
    files = dict(receipt_inventory=inventory, source_qualifications=qualifications, provenance=provenance)
    pins = {}
    for name, value in files.items():
        path = out / (name.replace('_', '-') + '.json')
        path.write_text(json.dumps(value, indent=1, sort_keys=True) + '\n')
        pins[name] = dict(path=str(path), sha256=_file_sha256(path), size=path.stat().st_size)
    manifest = dict(release_id=release, input_digest=input_digest, origin=ORIGIN, receipts=len(inventory),
        receipts_fetched=fetched, receipts_opaque=opaque, provenance={k: len(v) for k, v in provenance.items()},
        files=pins, command=sys.argv)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    return manifest


def verify(*, captures, counts, work, engine_config):
    from congress_api.lake.capture_backfill_guard import GenerationViolation, validate_generation
    from docspec_client.client import NativeDatasets
    with NativeDatasets.from_config(engine_config) as engine:
        try:
            return validate_generation(engine=engine, work=work, pin=str(Path(captures).resolve()),
                                       counts=json.loads(Path(counts).read_text()))
        except GenerationViolation as error:
            return error.report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('collect')
    for name in ('release', 'input-digest', 'mirror', 'out'):
        one.add_argument('--' + name, required=True)
    one.add_argument('--threads', type=int, default=16)
    two = commands.add_parser('verify')
    for name in ('captures', 'counts', 'work'):
        two.add_argument('--' + name, required=True)
    two.add_argument('--engine-config', default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    args = parser.parse_args(argv)
    if args.command == 'collect':
        result = collect(release=args.release, input_digest=args.input_digest, mirror=args.mirror,
                         out=args.out, threads=args.threads)
    else:
        result = verify(captures=args.captures, counts=args.counts, work=args.work, engine_config=args.engine_config)
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    return 0 if args.command == 'collect' or result.get('status') == 'validated' else 1


if __name__ == '__main__':
    raise SystemExit(main())
