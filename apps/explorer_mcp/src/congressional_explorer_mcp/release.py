"""Acquire exact release files once; select atomically and serve without network."""
from contextlib import contextmanager
import fcntl
from hashlib import sha256, file_digest
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from .models import ExplorerError

PUBLICATION = 'https://congressional-data.spicygov.ai/viewer-publications/manifest.json'
CONTROL_BYTES = 32 << 20
NAME = re.compile(r'(?:[a-z_]+|(?:detail|sources)-[0-9]{5})\.(?:parquet|json)')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def stamp(path):
    stat = Path(path).stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


@contextmanager
def opened(location):
    if str(location).startswith(('https://', 'http://')):
        with urlopen(Request(str(location), headers={'User-Agent': 'CongressExplorerMCP/0.2.0'}), timeout=30) as stream:
            if urlsplit(stream.url).netloc != urlsplit(str(location)).netloc:
                raise ExplorerError('Publication redirected to a different host')
            yield stream
    else:
        with Path(location).expanduser().open('rb') as stream:
            yield stream


def control(location):
    with opened(location) as stream:
        data = stream.read(CONTROL_BYTES + 1)
    if len(data) > CONTROL_BYTES:
        raise ExplorerError('Release control exceeds 32 MiB')
    return json.loads(data)


def beside(location, relative):
    if str(location).startswith(('https://', 'http://')):
        return urljoin(str(location), relative)
    return str(Path(location).expanduser().absolute().parent / relative)


def resolve(location):
    manifest = control(location)
    if 'files' not in manifest:
        identity = manifest.get('release_id', '')
        if not re.fullmatch('[a-f0-9]{64}', identity):
            raise ExplorerError('Expected an archive release pointer; legacy catalogs are unsupported')
        location = beside(location, f'releases/{identity}/manifest.json')
        manifest = control(location)
        if manifest.get('release_id') != identity:
            raise ExplorerError('Pointer and release differ')
    if manifest.get('schema_version') != 1:
        raise ExplorerError('Expected archive schema_version=1; legacy catalogs are unsupported')
    identity = [1, [[item[key] for key in ('name', 'sha256', 'size', 'rows')] for item in manifest['files']]]
    if sha256(encoded(identity)).hexdigest() != manifest.get('release_id'):
        raise ExplorerError('Release identity differs from its file list')
    names, groups = set(), {}
    for item in manifest['files']:
        name = item['name']
        if (not NAME.fullmatch(name) or name in names or name == 'documents.parquet'
                or not re.fullmatch('[a-f0-9]{64}', item['sha256'])
                or any(type(item[key]) is not int or item[key] < 0 for key in ('size', 'rows'))):
            raise ExplorerError('Invalid or duplicate release file')
        names.add(name)
        table = item.get('shard') or name.removesuffix('.parquet')
        if name.endswith('.parquet'):
            groups.setdefault(table, []).append(item)
        if item.get('shard'):
            interval = item.get('row_range')
            if (table not in ('detail', 'sources') or not re.fullmatch(table + r'-[0-9]{5}\.parquet', name)
                    or not isinstance(interval, list) or len(interval) != 2
                    or any(type(n) is not int for n in interval) or interval[0] < 0
                    or interval[1] <= interval[0] or interval[1] - interval[0] != item['rows']):
                raise ExplorerError('Invalid shard range')
        elif item.get('row_range') is not None or '-' in name:
            raise ExplorerError('Missing shard declaration')
    for table, files in groups.items():
        if any(item.get('shard') for item in files):
            end = 0
            for item in sorted(files, key=lambda item: item.get('row_range') or [-1]):
                if not item.get('shard') or item['row_range'][0] != end:
                    raise ExplorerError('Mixed, overlapping or incomplete shards')
                end = item['row_range'][1]
    required = {'list', 'detail', 'links', 'urls', 'sources', 'recoveries', 'url_state'}
    if not required <= groups.keys() or not {'schema.json', 'capture_scope.json'} <= names:
        raise ExplorerError('Release lacks required archive tables or controls')
    if sum(i['rows'] for i in groups['list']) != sum(i['rows'] for i in groups['detail']):
        raise ExplorerError('Document list and detail counts differ')
    return location, manifest, groups


def atomic_json(path, value):
    with NamedTemporaryFile(dir=path.parent, prefix='.selection-', suffix='.partial', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def retain(location, item, objects, previous):
    target = objects / item['sha256']
    if target.is_symlink():
        raise ExplorerError('Cache object is a symlink')
    if target.exists():
        # The owned immutable object was already verified. A changed custody
        # stamp is an error, not permission to silently trust or replace it.
        if previous is not None:
            if stamp(target) != previous:
                raise ExplorerError('Prepared file changed; choose a fresh data directory')
        else:
            with target.open('rb') as stream:
                if target.stat().st_size != item['size'] or file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                    raise ExplorerError('Incomplete or corrupt cached object')
        return target
    with NamedTemporaryFile(dir=objects, prefix='.download-', suffix='.partial', delete=False) as output:
        temporary = Path(output.name)
        try:
            digest, size = sha256(), 0
            with opened(location) as source:
                while block := source.read(1 << 20):
                    size += len(block)
                    if size > item['size']:
                        raise ExplorerError('Release file exceeds declared size')
                    digest.update(block); output.write(block)
            if size != item['size'] or digest.hexdigest() != item['sha256']:
                raise ExplorerError('Release file checksum or size differs')
            output.flush(); os.fsync(output.fileno())
            os.chmod(temporary, 0o444)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return target


def prepare(data_dir, publication=PUBLICATION, *, archive_origin=None):
    root = Path(data_dir).expanduser().absolute()
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'prepare.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ExplorerError('Another prepare owns this data directory') from error
        return _prepare(root, publication, archive_origin)


def _prepare(root, publication, archive_origin):
    objects = root / 'objects'; objects.mkdir(exist_ok=True)
    # The exclusive prepare lock proves no active writer owns these temporary
    # files. Readers use immutable digest names, never these partial namespaces.
    for partial in [*objects.glob('.download-*.partial'), *root.glob('.selection-*.partial')]:
        partial.unlink()
    selected = root / 'selection.json'
    previous = json.loads(selected.read_bytes()) if selected.exists() else {}
    if previous and previous.get('version') != 1:
        raise ExplorerError('Legacy selections are unsupported; choose a new data directory')
    location, manifest, groups = resolve(publication)
    origin = archive_origin or (urljoin(str(publication), '/') if str(publication).startswith(('http://', 'https://')) else None)
    if origin is not None:
        address = urlsplit(origin)
        if (address.scheme not in ('http', 'https') or not address.netloc or address.username
                or address.password or address.query or address.fragment or address.path not in ('', '/')):
            raise ExplorerError('Archive origin must be an HTTP(S) origin without a path, query or credentials')
        origin = origin.rstrip('/')
    if previous.get('release_id') == manifest['release_id'] and previous.get('archive_origin') == origin:
        return load_selection(root)
    files, controls = {}, {}
    for item in manifest['files']:
        path = retain(beside(location, item['name']), item, objects,
                      previous.get('files', {}).get(item['sha256'], {}).get('stamp'))
        files[item['sha256']] = dict(path=str(path), stamp=stamp(path))
        if item['name'].endswith('.json'):
            controls[item['name'].removesuffix('.json')] = control(path)
    tables = {name: [dict(path=files[i['sha256']]['path'], offset=(i.get('row_range') or [0])[0], rows=i['rows'])
                    for i in sorted(items, key=lambda i: (i.get('row_range') or [0])[0])]
              for name, items in groups.items()}
    value = dict(version=1, release_id=manifest['release_id'], manifest=manifest,
                 files=files, tables=tables, controls=controls,
                 archive_origin=origin)
    # Footer counts detect unusable delivery. The producer owns semantic model
    # invariants; preparation does not rebuild or rescan those relationships.
    import duckdb
    with duckdb.connect(config={'threads': 2, 'memory_limit': '512MB'}) as db:
        for parts in tables.values():
            for part in parts:
                rows = db.execute('SELECT num_rows FROM parquet_file_metadata(?)', [part['path']]).fetchall()[0][0]
                if rows != part['rows']:
                    raise ExplorerError('Parquet row count differs from manifest')
    atomic_json(selected, value)
    return value


def load_selection(data_dir):
    path = Path(data_dir).expanduser().absolute() / 'selection.json'
    if not path.exists():
        raise ExplorerError('Run prepare with a current archive release first')
    value = json.loads(path.read_bytes())
    if value.get('version') != 1 or 'release_id' not in value:
        raise ExplorerError('Legacy MCP selections are unsupported; prepare a new archive release')
    for item in value['files'].values():
        if Path(item['path']).is_symlink() or stamp(item['path']) != item['stamp']:
            raise ExplorerError('Prepared file changed; choose a fresh data directory')
    return value
