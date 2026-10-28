"""Receipt metadata discovery; native keys select work before receipt reads."""
from datetime import date
import json
from pathlib import Path

from congress_api.lake.tables import table_input
from congress_api.retention.body_store import validate_key
from congress_api.retention.provenance import json_input, run_job


METADATA_BYTES=64<<20
ITEM_BYTES=16<<10


def _receipt_key(key):
    validate_key(key)
    if not key.startswith('receipts/'):
        raise ValueError('Receipt inventory requires receipt keys')
    return key


def _existing(work,existing):
    if existing is not None:
        return table_input('existing',existing)
    return json_input(work,'existing',[],receipt_key='Utf8')


def _bounded(rows):
    total=0
    for row in rows:
        encoded=json.dumps(row,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        size=len(encoded.encode())
        total+=size
        if size>ITEM_BYTES or total>METADATA_BYTES:
            raise ValueError('Receipt inventory exceeds the metadata bound')
        yield encoded


def select_receipts(files,existing,*,engine,work):
    """Return sorted missing metadata, without opening or stat'ing receipt paths.

    The native hash anti-join scans inventory and existing keys in O(N+M);
    sorting only the selected inventory costs O(K log K). Metadata is bounded
    to 64 MiB; receipt contents never enter the inventory job.
    """
    rows=[];seen=set()
    for encoded in _bounded(files):
        item=json.loads(encoded)
        key=_receipt_key(item['key'])
        if key in seen:
            raise ValueError('Receipt inventory requires unique keys')
        seen.add(key)
        rows.append(dict(receipt_key=key,metadata_json=encoded))
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    result=run_job(work,engine,inputs=[
        json_input(work,'inventory',rows,receipt_key='Utf8',metadata_json='Utf8'),
        _existing(work,existing)],steps=[],outputs=[],queries=[dict(name='missing',sql='''
            SELECT i.metadata_json FROM inventory i LEFT ANTI JOIN existing e
            ON i.receipt_key=e.receipt_key ORDER BY i.receipt_key''')])
    return [json.loads(row['metadata_json']) for row in result['missing']]


def discover_receipts(adapter,families,*,existing,engine,work,mode='incremental'):
    """List dated prefixes inclusively; only backfill/raw-check list non-dates.

    Adapter.prefixes returns immediate child prefix strings; Adapter.files
    yields file metadata below a selected prefix. Neither operation reads
    contents. A family with no dated existing key starts at every known date.
    """
    if mode not in {'incremental','backfill','raw-check'}:
        raise ValueError('Receipt discovery mode must be incremental, backfill or raw-check')
    rows=[];seen=set();metadata_bytes=0
    for family in families:
        prefix='receipts/'+family+'/'
        validate_key('receipts/'+family+'/sentinel')
        if not family or prefix in seen:
            raise ValueError('Receipt families must be explicit unique relative names')
        seen.add(prefix)
        for child in adapter.prefixes(prefix):
            if not child.startswith(prefix) or not child.endswith('/'):
                raise ValueError('Receipt adapter returned a prefix outside its family')
            segment=child[len(prefix):-1]
            if not segment or '/' in segment:
                raise ValueError('Receipt adapter must return immediate child prefixes')
            try:
                parsed=date.fromisoformat(segment)
                dated=segment if parsed.isoformat()==segment else None
            except ValueError:
                dated=None
            row=dict(family=family,prefix=child,day=dated)
            encoded=next(_bounded([row]))
            metadata_bytes+=len(encoded.encode())
            if metadata_bytes>METADATA_BYTES:
                raise ValueError('Receipt inventory exceeds the metadata bound')
            rows.append(row)
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    selection=work/'prefixes';selection.mkdir()
    full='true' if mode in {'backfill','raw-check'} else 'false'
    result=run_job(selection,engine,inputs=[
        json_input(selection,'prefixes',rows,family='Utf8',prefix='Utf8',day='Utf8'),
        _existing(selection,existing)],steps=[dict(name='watermarks',sql=r'''
            SELECT regexp_replace(receipt_key,'^receipts/(.*)/[^/]+/[^/]+$','\1') AS family,
                max(try_cast(regexp_replace(receipt_key,'^.*/([^/]+)/[^/]+$','\1') AS DATE)) AS newest
            FROM existing WHERE regexp_like(receipt_key,'^receipts/.*/[0-9]{4}-[0-9]{2}-[0-9]{2}/[^/]+$')
            GROUP BY regexp_replace(receipt_key,'^receipts/(.*)/[^/]+/[^/]+$','\1')''')],outputs=[],queries=[dict(name='prefixes',sql=f'''
            SELECT DISTINCT p.prefix FROM prefixes p LEFT JOIN watermarks w ON p.family=w.family
            WHERE {full} OR (p.day IS NOT NULL AND
                (w.newest IS NULL OR cast(p.day AS DATE)>=w.newest)) ORDER BY p.prefix''')])
    def listed():
        for row in result['prefixes']:
            for item in adapter.files(row['prefix']):
                if not item['key'].startswith(row['prefix']):
                    raise ValueError('Receipt adapter returned a file outside its listed prefix')
                yield item
    files=listed()
    return select_receipts(files,existing,engine=engine,work=work/'selection')


class LocalReceiptStore:
    """Read-only local listing/read adapter with the same raw-key boundary."""
    def __init__(self,root):
        self.root=Path(root).resolve()

    def _path(self,key,prefix=False):
        _receipt_key(key.rstrip('/') if prefix else key)
        path=(self.root/key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Local receipt path escapes its root')
        return path

    def prefixes(self,prefix):
        path=self._path(prefix,True)
        if not path.exists():
            return
        for child in path.iterdir():
            if child.is_symlink():
                raise ValueError('Local receipt inventory refuses symbolic links')
            if child.is_dir():
                yield child.relative_to(self.root).as_posix()+'/'

    def files(self,prefix):
        path=self._path(prefix,True)
        for child in path.rglob('*'):
            if child.is_symlink():
                raise ValueError('Local receipt inventory refuses symbolic links')
            if child.is_file():
                yield dict(key=child.relative_to(self.root).as_posix(),
                           path=str(child.resolve()),size=child.stat().st_size)

    def open(self,key):
        return self._path(key).open('rb')
