"""Release input custody against a fake origin: every byte path is checked, nothing is trusted by name."""
import gzip
from hashlib import md5
import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('release_input_custody', ROOT / 'scripts/measure/release_input_custody.py')
custody = importlib.util.module_from_spec(spec)
spec.loader.exec_module(custody)

from viewer_publication.receipt_pins import receipt_list

RELEASE, DIGEST = 'a' * 64, 'b' * 64
PREFIX = custody.RELEASES + RELEASE + '/inputs/'


class Response(io.BytesIO):
    def __init__(self, body, etag):
        super().__init__(body)
        self.headers = {'ETag': etag, 'Content-Length': str(len(body))}


def origin(objects, etags=None, served=None):
    etags = etags or {}

    def opener(request, timeout):
        key = request.full_url[len(custody.ORIGIN):]
        body = objects[key]
        etag = etags.get(key, '"' + md5(body).hexdigest() + '"')
        if served is not None:
            served.append((request.get_method(), key))
        response = Response(b'' if request.get_method() == 'HEAD' else body, etag)
        response.headers['Content-Length'] = str(len(body))
        return response
    return opener


def world(tmp_path, *, opaque=False):
    receipts = {'receipts/documents/2026-10-01/a.jsonl.gz': gzip.compress(b'{"record":{}}\n', mtime=0),
                'receipts/house/2026-10-02/b.jsonl.gz': gzip.compress(b'{"record":{}}\n{"record":{}}\n', mtime=0)}
    unreadable = b'{"decision":1}\n'
    provenance = [dict(key='provenance/unreadable/x.jsonl', etag='"' + md5(unreadable).hexdigest() + '"'),
                  dict(key='provenance/recoveries/accepted-1.json', etag='"' + 'c' * 32 + '"')]
    digest, payload = receipt_list(receipts)
    record = dict(input_digest=DIGEST, receipt_keys_sha256=digest, provenance=provenance)
    objects = dict(receipts, **{PREFIX + DIGEST + '.json': json.dumps(record).encode(),
                                PREFIX + 'receipts/' + digest + '.json.gz': payload,
                                'provenance/unreadable/x.jsonl': unreadable})
    mirror = tmp_path / 'mirror'
    local = mirror / 'receipts/documents/2026-10-01/a.jsonl.gz'
    local.parent.mkdir(parents=True)
    local.write_bytes(receipts['receipts/documents/2026-10-01/a.jsonl.gz'])
    etags = {'receipts/documents/2026-10-01/a.jsonl.gz': '"' + 'd' * 32 + '-2"'} if opaque else {}
    return objects, etags, mirror


def test_collect_fetches_missing_receipts_and_pins_record_provenance_only(tmp_path):
    objects, etags, mirror = world(tmp_path)
    served = []
    manifest = custody.collect(release=RELEASE, input_digest=DIGEST, mirror=mirror, out=tmp_path / 'out',
                               threads=2, opener=origin(objects, etags, served))
    assert manifest['receipts_fetched'] == ['receipts/house/2026-10-02/b.jsonl.gz']
    assert (mirror / 'receipts/house/2026-10-02/b.jsonl.gz').read_bytes() == objects['receipts/house/2026-10-02/b.jsonl.gz']
    inventory = json.loads((tmp_path / 'out/receipt-inventory.json').read_text())
    assert [r['key'] for r in inventory] == ['receipts/documents/2026-10-01/a.jsonl.gz',
                                             'receipts/house/2026-10-02/b.jsonl.gz']
    assert all(Path(r['path']).stat().st_size == r['size'] for r in inventory)
    provenance = json.loads((tmp_path / 'out/provenance.json').read_text())
    assert [r['key'] for r in provenance['unreadable']] == ['provenance/unreadable/x.jsonl']
    assert provenance['recoveries'] == [] and provenance['reviews'] == []
    # The accepted.json backup is identity metadata: never fetched.
    assert ('GET', 'provenance/recoveries/accepted-1.json') not in served
    bindings = json.loads((tmp_path / 'out/source-qualifications.json').read_text())
    assert set(bindings) == {r['path'] for r in inventory}


def test_each_batch_filter_binds_every_receipt_it_selects(tmp_path):
    # capture_backfill narrows the bindings to a batch's paths; source_pins needs every one bound.
    from congress_api.lake.receipt_metadata import source_pins
    objects, etags, mirror = world(tmp_path, opaque=True)
    custody.collect(release=RELEASE, input_digest=DIGEST, mirror=mirror, out=tmp_path / 'out',
                    threads=1, opener=origin(objects, etags))
    inventory = json.loads((tmp_path / 'out/receipt-inventory.json').read_text())
    bindings = json.loads((tmp_path / 'out/source-qualifications.json').read_text())
    for row in inventory:
        batch = {p: a for p, a in bindings.items() if p == row['path']}
        pins = source_pins(files=[dict(path=row['path'])], qualifications=batch)
        assert (pins[0]['size'], pins[0]['path']) == (row['size'], row['path'])


def test_a_single_put_mirror_copy_that_differs_from_its_etag_refuses(tmp_path):
    objects, etags, mirror = world(tmp_path)
    local = mirror / 'receipts/documents/2026-10-01/a.jsonl.gz'
    data = bytearray(local.read_bytes())
    data[-1] ^= 1
    local.write_bytes(bytes(data))
    with pytest.raises(ValueError, match='MD5 differs'):
        custody.collect(release=RELEASE, input_digest=DIGEST, mirror=mirror, out=tmp_path / 'out',
                        threads=1, opener=origin(objects, etags))


def test_a_corrupt_origin_body_never_lands_in_the_mirror(tmp_path):
    objects, etags, mirror = world(tmp_path)
    etags['receipts/house/2026-10-02/b.jsonl.gz'] = '"' + 'e' * 32 + '"'
    with pytest.raises(ValueError, match='ETag or size'):
        custody.collect(release=RELEASE, input_digest=DIGEST, mirror=mirror, out=tmp_path / 'out',
                        threads=1, opener=origin(objects, etags))
    assert not list(mirror.rglob('b.jsonl.gz*'))


def test_an_opaque_etag_is_qualified_by_the_origin_copy(tmp_path):
    objects, etags, mirror = world(tmp_path, opaque=True)
    manifest = custody.collect(release=RELEASE, input_digest=DIGEST, mirror=mirror, out=tmp_path / 'out',
                               threads=1, opener=origin(objects, etags))
    assert manifest['receipts_opaque'] == ['receipts/documents/2026-10-01/a.jsonl.gz']
    bindings = json.loads((tmp_path / 'out/source-qualifications.json').read_text())
    from congress_api.lake.receipt_metadata import source_pins
    pins = source_pins(files=[dict(path=p) for p in bindings], qualifications=bindings)
    assert pins[0]['size'] == (mirror / 'receipts/documents/2026-10-01/a.jsonl.gz').stat().st_size


def test_an_opaque_mirror_copy_that_differs_from_origin_refuses(tmp_path):
    objects, etags, mirror = world(tmp_path, opaque=True)
    local = mirror / 'receipts/documents/2026-10-01/a.jsonl.gz'
    data = bytearray(local.read_bytes())
    data[-1] ^= 1
    local.write_bytes(bytes(data))
    with pytest.raises(ValueError, match='bytes differ'):
        custody.collect(release=RELEASE, input_digest=DIGEST, mirror=mirror, out=tmp_path / 'out',
                        threads=1, opener=origin(objects, etags))
