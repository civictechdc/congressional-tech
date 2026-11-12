"""Nightly runs discover the receipts captures lacks instead of reading a pinned inventory (ct-ud0b)."""
import hashlib
from io import BytesIO
from pathlib import Path

import pytest

from congress_api.lake import daily
from congress_api.lake.receipt_inventory import R2ReceiptStore, copy_receipts
from congress_api.retention.body_store import BodyStore, LocalAdapter
from test_daily_producers import native_fixture, spec


def test_daily_discovers_new_receipts_by_family_and_then_finds_none(tmp_path):
    value, engine, store = native_fixture(tmp_path, 2)
    for sidecar in (tmp_path / 'raw/receipts').rglob('*.qualification.json'):
        sidecar.unlink()
    keys = sorted(row['key'] for row in value['receipt_inventory'])
    value = dict(value, receipt_inventory=[], receipt_families=['documents'])
    first = daily.produce_daily(value, engine=engine, raw_store=store)
    assert first['status'] == 'completed' and first['discovered_receipts'] == 2
    assert first['new_receipt_keys'] == keys and first['receipt_keys'] == keys
    copied = Path(value['work']) / 'receipts' / keys[0]
    assert copied.is_file() and copied.with_name(copied.name + '.qualification.json').is_file()
    second = daily.produce_daily(dict(value, work=str(tmp_path / 'second')), engine=engine, raw_store=store)
    assert second['status'] == 'completed' and second['discovered_receipts'] == 0 and second['new_receipt_keys'] == []


def test_daily_discovers_late_receipt_planted_in_older_day_prefix(tmp_path):
    """ct-mt88: after daily ingests a newer day prefix, a late receipt written into a recent older day prefix is discovered."""
    import shutil
    value, engine, store = native_fixture(tmp_path, 2)
    for sidecar in (tmp_path / 'raw/receipts').rglob('*.qualification.json'):
        sidecar.unlink()
    sources = sorted((tmp_path / 'raw/receipts/documents').rglob('*.jsonl*'))
    assert len(sources) == 2
    newer_dir = tmp_path / 'raw/receipts/documents/2026-11-08'
    older_dir = tmp_path / 'raw/receipts/documents/2026-10-31'
    newer_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(sources[0]), str(newer_dir / sources[0].name))
    late_bytes = sources[1].read_bytes()
    late_name = sources[1].name
    sources[1].unlink()

    spec_val = dict(value, receipt_inventory=[], receipt_families=['documents'])
    first = daily.produce_daily(spec_val, engine=engine, raw_store=store)
    assert first['status'] == 'completed' and first['discovered_receipts'] == 1
    assert first['new_receipt_keys'] == [f'receipts/documents/2026-11-08/{sources[0].name}']

    older_dir.mkdir(parents=True, exist_ok=True)
    (older_dir / late_name).write_bytes(late_bytes)
    second = daily.produce_daily(dict(spec_val, work=str(tmp_path / 'second')), engine=engine, raw_store=store)
    assert second['status'] == 'completed' and second['discovered_receipts'] == 1
    assert second['new_receipt_keys'] == [f'receipts/documents/2026-10-31/{late_name}']


def test_discovery_takes_no_pinned_inventory(tmp_path):
    value = dict(spec(tmp_path), receipt_families=['documents'], receipt_inventory=[dict(key='receipts/documents/x')])
    with pytest.raises(ValueError, match='take no pinned inventory'):
        daily.produce_daily(value, engine=None, raw_store=BodyStore(LocalAdapter(tmp_path / 'durable')))


class Bucket:
    """list_objects_v2 one item per page, and get_object honoring If-Match."""
    def __init__(self, objects):
        self.objects = objects
        self.requests = []

    def list_objects_v2(self, *, Bucket, Prefix, Delimiter=None, ContinuationToken=None):
        self.requests.append((Prefix, Delimiter, ContinuationToken))
        if Delimiter:
            names = sorted({Prefix + k[len(Prefix):].split('/', 1)[0] + '/' for k in self.objects
                            if k.startswith(Prefix) and '/' in k[len(Prefix):]})
            items = [dict(Prefix=n) for n in names]
            field = 'CommonPrefixes'
        else:
            items = [dict(Key=k, Size=len(v), ETag='"' + hashlib.md5(v).hexdigest() + '"')
                     for k, v in sorted(self.objects.items()) if k.startswith(Prefix)]
            field = 'Contents'
        start = int(ContinuationToken or 0)
        page = {field: items[start:start + 1], 'IsTruncated': start + 1 < len(items)}
        if page['IsTruncated']:
            page['NextContinuationToken'] = str(start + 1)
        return page

    def get_object(self, *, Bucket, Key, IfMatch):
        assert IfMatch.startswith('"')
        return dict(Body=BytesIO(self.objects[Key]))


def test_r2_receipts_page_through_listings_and_copy_with_their_md5(tmp_path):
    objects = {'receipts/documents/2026-10-30/a.jsonl.gz': b'one', 'receipts/documents/2026-10-31/b.jsonl.gz': b'two'}
    store = R2ReceiptStore(Bucket(objects), 'raw')
    assert list(store.prefixes('receipts/documents/')) == ['receipts/documents/2026-10-30/', 'receipts/documents/2026-10-31/']
    rows = list(store.files('receipts/documents/'))
    assert [r['key'] for r in rows] == sorted(objects)
    [copied, _] = copy_receipts(store, rows, tmp_path / 'copies')
    assert Path(copied['path']).read_bytes() == b'one'
    assert hashlib.sha256(b'one').hexdigest() in Path(copied['qualification']).read_text()


def test_a_copy_that_differs_from_its_listed_md5_refuses(tmp_path):
    objects = {'receipts/documents/2026-10-31/b.jsonl.gz': b'two'}
    store = R2ReceiptStore(Bucket(objects), 'raw')
    [row] = store.files('receipts/documents/')
    objects[row['key']] = b'tw0'
    with pytest.raises(ValueError, match='differs from its listed MD5 or size'):
        copy_receipts(store, [row], tmp_path / 'copies')
    assert not (tmp_path / 'copies' / row['key']).exists()
    with pytest.raises(ValueError, match='single-PUT MD5'):
        copy_receipts(store, [dict(row, etag='"abc-2"')], tmp_path / 'multipart')


def test_multipart_copy_uses_actual_part_size_and_rejects_changed_bytes(tmp_path):
    key = 'receipts/documents/2026-10-31/legacy.jsonl'
    parts = [b'a' * ((5 << 20) + 37), b'final']
    original = b''.join(parts)
    composite = hashlib.md5(b''.join(hashlib.md5(part).digest() for part in parts)).hexdigest()
    row = dict(key=key, size=len(original), etag=f'"{composite}-2"')

    class MultipartBucket(Bucket):
        def head_object(self, *, Bucket, Key, IfMatch, PartNumber):
            assert Key == key and IfMatch == row['etag'] and PartNumber == 1
            return dict(ContentLength=len(parts[0]), PartsCount=2, ETag=IfMatch)

    bucket = MultipartBucket({key: original})
    store = R2ReceiptStore(bucket, 'raw')
    path = tmp_path / 'receipt'
    digest, size = store.copy(row, path)
    assert digest == hashlib.sha256(original).hexdigest() and size == len(original)
    assert path.read_bytes() == original

    bucket.objects[key] = original[:-1] + b'X'
    bad = tmp_path / 'changed'
    with pytest.raises(ValueError, match='differs from its listed MD5 or size'):
        store.copy(row, bad)
    assert not bad.exists()
