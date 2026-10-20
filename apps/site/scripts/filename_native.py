"""Stable viewer assets derived from one exact selected native catalog."""
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from collections import OrderedDict

from congress_api.retention.derived_files import file_identity, copy_checked
from congress_api.retention.immutable_metadata import encoded
from filename_compression import DEFAULT_COMPRESSION_POLICY, validate_compression


class ViewerAssets:
    """Use the existing immutable release path, addressed by complete bytes."""
    def __init__(self, root, *, read_asset=None, max_node_bytes=1 << 20):
        self.root, self.read_asset = Path(root), read_asset
        self.max_node_bytes = max_node_bytes
        self.identities = {}
        self.state = None
        self.reads = self.writes = self.written_bytes = self.metadata_writes = 0
        self._nodes = OrderedDict()

    def put_file(self, source, *, name):
        if name not in ('filenames.parquet', 'documents.parquet', 'details.parquet', 'observations.bin',
                        'observation_rows.bin', 'observation_index.json'):
            raise ValueError('Unknown bounded viewer asset kind')
        identity = file_identity(source)
        digest = identity['sha256']
        relative = f'releases/{digest[:32]}/{digest[32:]}/viewer-v2/{name}'
        # The producer deletes its temporary source after this call. An owned
        # copy keeps the destination inode/custody independent of that unlink.
        destination = self.root / relative
        if destination.is_symlink():raise ValueError('Immutable viewer assets cannot be symlinks')
        if destination.exists():
            proof = file_identity(destination)
            if proof != identity:raise ValueError('Conflicting immutable viewer asset')
        else:
            with Path(source).open('rb') as stream:
                proof = (self.state.publish_asset(stream,destination,identity=identity,key=relative)
                    if self.state else copy_checked(stream, destination, size=identity['bytes'],
                                     expected=identity, key=relative, exclusive=True))
            self.writes += 1
            self.written_bytes += proof['bytes']
            self.metadata_writes += int(name.endswith('.json'))
        self.identities[relative] = proof
        if self.state:self.state.remember(relative,proof)
        return dict(path=relative, sha256=digest, bytes=proof['bytes'])

    def put_node(self, value):
        raw = encoded(value)
        if len(raw) > self.max_node_bytes:
            raise ValueError('Viewer metadata page exceeds the byte budget')
        digest = sha256(raw).hexdigest()
        relative = f'releases/{digest[:32]}/{digest[32:]}/viewer-v2/page.json'
        path = self.root / relative
        if path.is_symlink():raise ValueError('Immutable viewer assets cannot be symlinks')
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            if self.state:
                from io import BytesIO
                self.state.publish_asset(BytesIO(raw),path,identity=dict(bytes=len(raw),sha256=digest),key=relative)
            else:
                with path.open('xb') as stream:
                    stream.write(raw)
            self.writes += 1
            self.metadata_writes += 1
            self.written_bytes += len(raw)
        proof = file_identity(path)
        if proof['sha256'] != digest or proof['bytes'] != len(raw):
            raise ValueError('Conflicting immutable viewer metadata page')
        self.identities[relative] = proof
        if self.state:self.state.remember(relative,proof)
        return dict(path=relative, sha256=digest, bytes=len(raw))

    def read_node(self, reference):
        digest = reference.get('sha256')
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in '0123456789abcdef' for char in digest)
                or reference.get('path') != f'releases/{digest[:32]}/{digest[32:]}/viewer-v2/page.json'
                or type(reference.get('bytes')) is not int or not 0 < reference['bytes'] <= self.max_node_bytes):
            raise ValueError('Invalid immutable viewer page reference')
        raw = self._nodes.get(reference['path'])
        if raw is None:
            path = self.root / reference['path']
            raw = path.read_bytes() if path.is_file() else self.read_asset(reference['path']) if self.read_asset else None
            self.reads += 1
        if raw is None or len(raw) != reference['bytes'] or sha256(raw).hexdigest() != digest:
            raise ValueError('Viewer metadata page identity differs')
        self._nodes[reference['path']] = raw
        self._nodes.move_to_end(reference['path'])
        if len(self._nodes) > 16:
            self._nodes.popitem(last=False)
        return json.loads(raw)


def browse_key(row):
    """Match the maintained filename ordering, with null filenames last."""
    name, document = row.get('filename'), row.get('document_id')
    if not isinstance(document, str) or not document or name is not None and not isinstance(name, str):
        raise ValueError('Browse rows require a stable document ID and filename')
    return [name is None, name or '', document]


def browse_flags(rows=None, children=None):
    """Bounded counts let default browsing skip unrelated payload pages."""
    counts = {}
    for item in rows if rows is not None else children:
        values = {str(item.get('_flags', 0)): 1} if rows is not None else item['flags']
        for flag, count in values.items():
            if not flag.isdecimal() or not 0 <= int(flag) < 64 or type(count) is not int or count < 1:
                raise ValueError('Invalid browse flags')
            counts[flag] = counts.get(flag, 0) + count
    return counts


def build_page_levels(leaves, combine, fanout):
    """Carry bounded child groups upward without collecting all leaf refs."""
    levels = []
    def push(level, value):
        if len(levels) <= level:
            levels.append([])
        levels[level].append(value)
        if len(levels[level]) == fanout:
            merged, levels[level] = combine(levels[level]), []
            push(level + 1, merged)
    for leaf in leaves:
        push(0, leaf)
    level = 0
    while level < len(levels):
        if levels[level]:
            values, levels[level] = levels[level], []
            if not any(levels[level + 1:]):
                return values[0] if len(values) == 1 else combine(values)
            push(level + 1, combine(values))
        level += 1
    return None


class BrowsePages:
    """Filename ordering over immutable bounded browse pages, not row offsets.

    Leaves retain document/source identities and browse fields. Branches retain
    subtree counts and inclusive key bounds. Only changed paths are rewritten;
    this is derived serving data, never catalog publication authority.
    """
    def __init__(self, assets, *, leaf_rows=64, branch_children=16):
        if type(leaf_rows) is not int or leaf_rows < 2 or type(branch_children) is not int or branch_children < 2:
            raise ValueError('Browse page budgets must be at least two')
        self.assets, self.leaf_rows, self.branch_children = assets, leaf_rows, branch_children

    def _leaf(self, rows):
        if not rows or len(rows) > self.leaf_rows:
            raise ValueError('Invalid browse leaf size')
        keys = [browse_key(row) for row in rows]
        if any(a >= b for a, b in zip(keys, keys[1:])):
            raise ValueError('Browse keys must be unique and ordered')
        reference = self.assets.put_node(dict(version=1, kind='browse-leaf', records=rows))
        return dict(reference, rows=len(rows), first=keys[0], last=keys[-1], height=0, flags=browse_flags(rows=rows))

    def _branch(self, children):
        if (not children or len(children) > self.branch_children
                or any(a['last'] >= b['first'] or a['height'] != b['height'] for a, b in zip(children, children[1:]))):
            raise ValueError('Invalid browse branch order or size')
        reference = self.assets.put_node(dict(version=1, kind='browse-branch', children=children))
        return dict(reference, rows=sum(child['rows'] for child in children), first=children[0]['first'],
                    last=children[-1]['last'], height=children[0]['height'] + 1, flags=browse_flags(children=children))

    def read(self, reference):
        node = self.assets.read_node(reference)
        if node.get('version') != 1:
            raise ValueError('Unsupported browse page')
        if node.get('kind') == 'browse-leaf':
            rows = node.get('records', [])
            keys = [browse_key(row) for row in rows]
            if not 0 < len(rows) <= self.leaf_rows or any(a >= b for a, b in zip(keys, keys[1:])):
                raise ValueError('Invalid selected browse leaf')
            basis = dict(rows=len(rows), first=keys[0], last=keys[-1], height=0, flags=browse_flags(rows=rows))
        elif node.get('kind') == 'browse-branch':
            children = node.get('children', [])
            if (not 0 < len(children) <= self.branch_children or any(
                    a['last'] >= b['first'] or a['height'] != b['height'] for a, b in zip(children, children[1:]))):
                raise ValueError('Invalid selected browse branch')
            basis = dict(rows=sum(child['rows'] for child in children), first=children[0]['first'],
                         last=children[-1]['last'], height=children[0]['height'] + 1, flags=browse_flags(children=children))
        else:
            raise ValueError('Unknown browse page kind')
        if any(reference.get(key) != value for key, value in basis.items()):
            raise ValueError('Browse page count or bounds differ')
        return node

    def _groups(self, ordered_rows):
        pending, previous = [], None
        for row in ordered_rows:
            key = browse_key(row)
            if previous is not None and key <= previous:
                raise ValueError('Browse seed input must have unique ordered keys')
            previous = key
            if pending and (len(pending) == self.leaf_rows or len(encoded(
                    dict(version=1, kind='browse-leaf', records=[*pending, row]))) > self.assets.max_node_bytes):
                yield pending
                pending = []
            pending.append(row)
        if pending:
            yield pending

    def build(self, ordered_rows):
        return build_page_levels((self._leaf(group) for group in self._groups(ordered_rows)),
                                 self._branch, self.branch_children)

    def change(self, root, *, remove, add):
        def changed(reference, key, value):
            if reference is None:
                if value is None:
                    raise ValueError('Retired browse document is missing')
                return [self._leaf([value])]
            node = self.read(reference)
            if node['kind'] == 'browse-leaf':
                rows = {tuple(browse_key(row)): row for row in node['records']}
                if value is None:
                    if tuple(key) not in rows:
                        raise ValueError('Retired browse document is missing')
                    del rows[tuple(key)]
                else:
                    if tuple(key) in rows:
                        raise ValueError('Prepared browse document already exists')
                    rows[tuple(key)] = value
                ordered = [rows[key] for key in sorted(rows)]
                return [self._leaf(group) for group in self._groups(ordered)]
            children = list(node['children'])
            position = next((i for i, child in enumerate(children) if key <= child['last']), len(children) - 1)
            children[position:position + 1] = changed(children[position], key, value)
            return [self._branch(children[start:start + self.branch_children])
                    for start in range(0, len(children), self.branch_children)]
        for value in remove:
            values = changed(root, browse_key(value), None)
            root = self._branch(values) if len(values) > 1 else values[0] if values else None
        for value in add:
            values = changed(root, browse_key(value), value)
            root = self._branch(values) if len(values) > 1 else values[0]
        while root and root['height'] and len((node := self.read(root))['children']) == 1:
            root = node['children'][0]
        return root

    def page(self, root, *, offset, limit):
        if type(offset) is not int or offset < 0 or type(limit) is not int or limit < 1:
            raise ValueError('Invalid browse page bounds')
        def walk(reference, start, count):
            node = self.read(reference)
            if node['kind'] == 'browse-leaf':
                yield from node['records'][start:start + count]
                return
            for child in node['children']:
                if start >= child['rows']:
                    start -= child['rows']
                    continue
                take = min(count, child['rows'] - start)
                yield from walk(child, start, take)
                count -= take
                if count == 0:
                    break
                start = 0
        return list(walk(root, offset, limit)) if root and offset < root['rows'] else []

    def find(self, root, filename, document_id):
        key = browse_key(dict(filename=filename, document_id=document_id))
        reference = root
        while reference is not None:
            node = self.read(reference)
            if node['kind'] == 'browse-leaf':
                return next((row for row in node['records'] if browse_key(row) == key), None)
            reference = next((child for child in node['children'] if child['first'] <= key <= child['last']), None)
        return None


class NativeSourceAssets:
    """Render only changed hash-routed source leaves through maintained helpers."""
    def __init__(self, snapshot, assets, *, policy, metrics, compression_policy=DEFAULT_COMPRESSION_POLICY):
        from congress_api.retention.partition_routing import RoutingPages
        from congress_api.retention.catalog_dependency_storage import CatalogDependencyStorage
        self.dependencies = CatalogDependencyStorage.for_snapshot(snapshot)
        self.snapshot, self.assets = snapshot, assets
        self.policy, self.metrics = policy, metrics
        self.compression = validate_compression(compression_policy)
        selected = snapshot.selection['dependency']
        self.max_rows, self.max_bytes = selected['max_rows'], selected['max_arrow_bytes']
        root = selected['source_root']
        namespace = root['key'].split('/')[2] if root is not None else None
        if namespace is not None and not namespace.endswith('-sources'):
            raise ValueError('Selected catalog source routing namespace differs')
        self.routes = RoutingPages(snapshot.store, namespace) if namespace is not None else None
        if self.routes:
            self.routes.objects.max_cache_entries = 4

    def render(self, root, previous=None, *, prefix=''):
        if self.assets.state and root is not None:
            return self.assets.state.run('source-route:'+root['sha256'],
                lambda:self._render(root,previous,prefix=prefix))
        return self._render(root,previous,prefix=prefix)

    def _render(self, root, previous=None, *, prefix=''):
        if root is None:
            return None
        if previous is not None and previous.get('native_sha256') == root['sha256']:
            self.metrics['source_subtrees_reused'] = self.metrics.get('source_subtrees_reused', 0) + 1
            return previous
        node = self.routes._read(root, prefix)
        old = self.assets.read_node(previous) if previous is not None else {}
        if old and (old.get('kind') not in ('source-branch', 'source-leaf') or old.get('prefix') != prefix):
            raise ValueError('Previous viewer source routing basis differs')
        if 'children' in node:
            children = {char: self.render(child, old.get('children', {}).get(char), prefix=prefix + char)
                        for char, child in sorted(node['children'].items())}
            stats = dict(rows=sum(child['stats']['rows'] for child in children.values()),
                         bytes=sum(child['stats']['bytes'] for child in children.values()), facets={})
            for child in children.values():
                for field, counts in child['stats']['facets'].items():
                    target = stats['facets'].setdefault(field, {})
                    for item, count in counts.items():
                        target[item] = target.get(item, 0) + count
            value = dict(version=1, kind='source-branch', prefix=prefix, children=children,
                         native_sha256=root['sha256'], stats=stats)
        else:
            source = self.render_source(node['value'])
            stats = dict(rows=source['rows'], bytes=sum(item['bytes'] for item in source['files'].values()),
                         facets=source.pop('facets'))
            value = dict(version=1, kind='source-leaf', prefix=prefix, native_sha256=root['sha256'],
                         source=source, stats=stats)
        return dict(self.assets.put_node(value), native_sha256=root['sha256'], stats=stats)

    def render_source(self, release):
        import pyarrow as pa
        import pyarrow.parquet as pq
        from filename_budget import bounded_batches
        from filename_json_stream import ObservationCounts
        from filename_observations import publish_observations
        from filename_details import publish_details
        schema = self.snapshot.schemas['filenames']
        values = self.dependencies.read_source_leaf(self.snapshot.selection['dependency'], release)
        if values.nbytes > self.max_bytes or len(values) > self.max_rows:
            raise ValueError('Selected native source leaf exceeds its retained bounds')
        records = values['source_values'].combine_chunks()
        table = pa.Table.from_arrays([records.field(name) for name in schema.names], schema=schema)
        if (table['source_id'].to_pylist() != values['source_id'].to_pylist()
                or len(set(table['source_id'].to_pylist())) != len(table)):
            raise ValueError('Selected native source leaf identity differs')
        self.metrics['native_source_leaves_read'] = self.metrics.get('native_source_leaves_read', 0) + 1
        self.metrics['native_source_rows_read'] = self.metrics.get('native_source_rows_read', 0) + len(table)
        with tempfile.TemporaryDirectory(prefix='viewer-source-leaf-') as folder:
            folder = Path(folder)
            path = folder / 'filenames.parquet'
            pq.write_table(table, path, compression=self.compression.codec, compression_level=self.compression.level,
                           row_group_size=self.compression.row_group_size)
            files = {'filenames': dict(self.assets.put_file(path, name='filenames.parquet'), rows=len(table))}
            # These are real bounded physical files. No logical-table export or
            # pretend Parquet metadata is introduced at the consumer boundary.
            with pq.ParquetFile(path) as source, ObservationCounts(source) as counts:
                if 'source_occurrences' in schema.names:
                    publish_observations(source, folder, counts=counts, policy=self.policy, metrics=self.metrics)
                    observation_files = [('observations', 'observations.bin'),
                        ('observation_rows', 'observation-rows.bin'), ('observation_index', 'observation-index.json')]
                else:
                    for _ in range(len(table)):
                        counts.append(0)
                    counts.seal(len(table))
                    observation_files = []
                result = publish_details(source, folder / 'details.parquet', observation_counts=counts,
                                         policy=self.policy, metrics=self.metrics, compression_policy=self.compression)
                for name, filename in [*observation_files, ('details', 'details.parquet')]:
                    files[name] = self.assets.put_file(folder / filename, name=name +
                        ('.parquet' if name == 'details' else '.json' if name == 'observation_index' else '.bin'))
                files['details']['rows'] = result['rows']
                facets = {field: {} for field in ('congress', 'document_family', 'document_kind', 'format')}
                columns = [field for field in facets if field in schema.names]
                for batch in bounded_batches(source, columns=columns, policy=self.policy,
                        metrics=self.metrics, stage='native source facets'):
                    for row in batch.to_pylist():
                        for field, values in row.items():
                            for value in values or []:
                                value = value.lower() if field == 'format' else value
                                if value:
                                    facets[field][value] = facets[field].get(value, 0) + 1
                # Existing row/batch admission also governs verification below.
                fields = [name for name in ('filename', 'source_id', 'document_id') if name in schema.names]
                counted = sum(len(batch) for batch in bounded_batches(source, columns=fields,
                    policy=self.policy, metrics=self.metrics, stage='native source leaf verification'))
                if counted != len(table):
                    raise ValueError('Viewer source leaf row count differs')
            return dict(rows=len(table), files=files, facets=facets)


class NativeComponents:
    """Stage changed component metadata, then read each changed physical pin once."""
    def __init__(self, snapshot, assets, browse, db, *, viewer, policy, metrics, compression_policy=DEFAULT_COMPRESSION_POLICY):
        from congress_api.retention.partition_routing import RoutingPages
        self.snapshot, self.assets, self.browse, self.db = snapshot, assets, browse, db
        self.viewer, self.policy, self.metrics = viewer, policy, metrics
        self.compression = validate_compression(compression_policy)
        self.routes = RoutingPages(snapshot.store, 'catalog-component-selection-v2')
        self.routes.objects.max_cache_entries = 4
        db.executescript('''
            CREATE TABLE IF NOT EXISTS components(id TEXT PRIMARY KEY,reference TEXT,page TEXT,proof TEXT,record TEXT,entry TEXT);
            CREATE TABLE IF NOT EXISTS retired(id TEXT PRIMARY KEY,record TEXT);
            CREATE TABLE IF NOT EXISTS chunks(name TEXT PRIMARY KEY,label TEXT,pin TEXT,schema TEXT);
            CREATE TABLE IF NOT EXISTS views(name TEXT,component TEXT,rows INTEGER,PRIMARY KEY(name,component));
            CREATE TABLE IF NOT EXISTS stats(id TEXT PRIMARY KEY,n INTEGER,saved INTEGER,api INTEGER,video INTEGER);
            CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chunk_assets(name TEXT PRIMARY KEY,reference TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS member_ids(id TEXT,source_order INTEGER,source_id TEXT UNIQUE,
                                    PRIMARY KEY(id,source_order));
        ''')

    def _stage(self, value):
        result = self.db.execute('INSERT INTO plans(body) VALUES (?)', (encoded(value).decode(),))
        return dict(plan=result.lastrowid)

    def _retire(self, component, entry):
        key = entry['key']
        self.db.execute('INSERT INTO retired VALUES (?,?)', (component, encoded(dict(
            document_id=component, filename=None if key[0] else key[1])).decode()))

    def _retire_tree(self, reference):
        if reference is None:
            return
        node = self.assets.read_node(reference)
        if node['kind'] == 'component-leaf':
            for component, entry in node['members'].items():
                self._retire(component, entry)
        else:
            for child in node['children'].values():
                self._retire_tree(child)

    def plan(self, root, previous=None, *, prefix=''):
        if root is None:
            self._retire_tree(previous)
            return None
        if previous is not None and previous.get('native_sha256') == root['sha256']:
            self.metrics['component_subtrees_reused'] = self.metrics.get('component_subtrees_reused', 0) + 1
            return previous
        node = self.routes._read(root, prefix)
        old = self.assets.read_node(previous) if previous is not None else {}
        if old and (old.get('kind') not in ('component-branch', 'component-leaf') or old.get('prefix') != prefix):
            raise ValueError('Previous viewer component routing differs')
        if 'children' in node:
            if old.get('kind') == 'component-leaf':
                # A native routing split does not retire all old logical members.
                # Pass its bounded old membership through every affected child.
                old_members = old['members']
            else:
                old_members = None
            children = {}
            old_characters = {self._hash(key)[len(prefix)] for key in old_members} if old_members else set()
            for char in sorted(set(node['children']) | set(old.get('children', {})) | old_characters):
                child_previous = old.get('children', {}).get(char)
                if old_members is not None:
                    # This temporary in-process value owns no publication path.
                    subset = {key: value for key, value in old_members.items()
                              if self._hash(key).startswith(prefix + char)}
                    child_previous = self._old_members(prefix + char, subset) if subset else None
                children[char] = self.plan(node['children'].get(char), child_previous, prefix=prefix + char)
            return self._stage(dict(kind='component-branch', prefix=prefix, native_sha256=root['sha256'],
                        children={char: value for char, value in children.items() if value is not None}))
        previous_members = old.get('members', {})
        if old.get('kind') == 'component-branch':
            raise ValueError('Native component routing unexpectedly collapsed a branch')
        members = {}
        for component, reference in self.snapshot.components._members(prefix, node['value']).items():
            entry = previous_members.get(component)
            if entry and entry['native_ref'] == reference:
                members[component] = entry
                continue
            if entry:
                self._retire(component, entry)
            self.db.execute('INSERT INTO components(id,reference,page) VALUES (?,?,?)',
                (component, encoded(reference).decode(), encoded(reference['page']).decode()))
            members[component] = dict(pending=component)
        for component in set(previous_members) - set(members):
            self._retire(component, previous_members[component])
        return self._stage(dict(kind='component-leaf', prefix=prefix, native_sha256=root['sha256'], members=members))

    @staticmethod
    def _hash(key):
        from congress_api.retention.partition_routing import key_hash
        return key_hash(key)

    def _old_members(self, prefix, members):
        return self.assets.put_node(dict(version=1, kind='component-leaf', prefix=prefix, members=members))

    def _task(self,name,action):
        return self.assets.state.run(name,action) if self.assets.state else action()

    def prepare(self):
        self._task('component-registration',self._register_chunks)
        for row in self.db.execute('SELECT * FROM chunks ORDER BY label,name'):
            self._task('component-chunk:'+row[0],lambda row=row:self._prepare_chunk(*row))
        self._task('component-entries',self._prepare_entries)

    def _register_chunks(self):
        from congress_api.retention.catalog_batches import CatalogComponentReader
        reader = CatalogComponentReader(self.snapshot.store)
        for component, raw_reference in self.db.execute('SELECT id,reference FROM components ORDER BY page,id'):
            reference = json.loads(raw_reference)
            proof = reader.read(reference)
            if proof['component'] != component:
                raise ValueError('Selected viewer component identity differs')
            self.db.execute('UPDATE components SET proof=? WHERE id=?',
                            (encoded(dict(validation=proof['validation'])).decode(), component))
            self.db.execute('INSERT INTO stats VALUES (?,0,0,0,0)', (component,))
            for label in ('filenames', 'documents'):
                table = proof['tables'][label]
                for chunk in table['chunks']:
                    raw_pin = encoded(chunk['release']).decode()
                    old = self.db.execute('SELECT pin,schema,label FROM chunks WHERE name=?', (chunk['name'],)).fetchone()
                    if old and old != (raw_pin, table['schema'], label):
                        raise ValueError('Mixed physical native viewer chunk metadata')
                    self.db.execute('INSERT OR IGNORE INTO chunks VALUES (?,?,?,?)',
                                    (chunk['name'], label, raw_pin, table['schema']))
                    self.db.execute('INSERT INTO views VALUES (?,?,?)', (chunk['name'], component, chunk['rows']))

    def _prepare_chunk(self,name,label,raw_pin,schema_text):
        from congress_api.retention.catalog_partitions import CatalogTable
        from congress_api.retention.catalog_publication import _component_schema
        from congress_api.retention.saved_responses import FIELDS,saved_response
        import pyarrow as pa
        schema = _component_schema(dict(schema=schema_text))
        members = list(self.db.execute('SELECT component,rows FROM views WHERE name=? ORDER BY component', (name,)))
        physical = schema.append(pa.field('_catalog_order', pa.int64(), nullable=False))
        table = CatalogTable(physical, [(name, json.loads(raw_pin))], native=self.snapshot.native,
            views={name: dict(components=[key for key, _ in members], rows=sum(count for _, count in members))})
        self.metrics['native_component_chunks_read'] = self.metrics.get('native_component_chunks_read', 0) + 1
        columns = (list(dict.fromkeys(['source_id', 'document_id', 'source_url', '_catalog_order', *[field for field in FIELDS
            if field in schema.names]])) if label == 'filenames' else
            [field for field in dict.fromkeys([*self.viewer.LIST_COLUMNS, 'document_kind_source']) if field in schema.names])
        size, document_batches = 0, []
        for batch in table.iter_batches():
            size += batch.nbytes
            if size > self.policy.row_arrow_bytes:
                raise ValueError('Native viewer component chunk exceeds its Arrow byte bound')
            if label == 'documents':
                document_batches.append(batch.select(schema.names))
            for row in batch.select(columns).to_pylist():
                component = row['document_id']
                if label == 'filenames':
                    self.db.execute('INSERT INTO member_ids VALUES (?,?,?)',
                                    (component, row['_catalog_order'], row['source_id']))
                    self.db.execute('UPDATE stats SET n=n+1,saved=saved+?,api=api+?,video=video+? WHERE id=?',
                        (int(saved_response(row)), int(bool(self.viewer.api_reference(row.get('source_url')))),
                         int(bool(self.viewer.video_reference(row.get('source_url')))), component))
                else:
                    self.db.execute('UPDATE components SET record=? WHERE id=?', (encoded(row).decode(), component))
        if label == 'documents':
            import pyarrow.parquet as pq
            with tempfile.TemporaryDirectory(prefix='viewer-document-chunk-') as folder:
                path = Path(folder) / 'documents.parquet'
                exported = pa.Table.from_batches(document_batches, schema=schema)
                pq.write_table(exported, path, compression=self.compression.codec, compression_level=self.compression.level,
                               row_group_size=self.compression.row_group_size)
                reference = dict(self.assets.put_file(path, name='documents.parquet'), rows=len(exported))
                self.db.execute('INSERT INTO chunk_assets VALUES (?,?)', (name, encoded(reference).decode()))
    def _prepare_entries(self):
        for component, raw_reference, raw_proof, raw_record in self.db.execute(
                'SELECT id,reference,proof,record FROM components ORDER BY id'):
            if raw_record is None:
                raise ValueError('Selected native component has no document record')
            proof, row = json.loads(raw_proof), json.loads(raw_record)
            count, saved, api, video = self.db.execute('SELECT n,saved,api,video FROM stats WHERE id=?', (component,)).fetchone()
            if count != proof['validation']['counts']['source_rows']:
                raise ValueError('Selected viewer component source count differs')
            api_only, video_only = api == count, video == count
            document = row.get('record_role') == ['document'] and not api_only and not video_only
            flags = dict(document=document, api=api_only, video=video_only, retained=bool(saved))
            document_files = self.db.execute('SELECT reference FROM chunk_assets JOIN views USING(name) WHERE component=?',
                                             (component,)).fetchall()
            if len(document_files) != 1:
                raise ValueError('Selected component must have one exact document row partition')
            entry = dict(document_file=json.loads(document_files[0][0]), native_ref=json.loads(raw_reference), key=browse_key(row), source_id=row['source_id'],
                         body_key=row.get('body_key'), source_ids_sha256=proof['validation']['source_ids_sha256'],
                         source_rows=count, flags=flags, members=self._members(component, count))
            browse = {key: value for key, value in row.items() if key not in
                      {'body_key', 'extension', 'recovered_filename', 'response_result'}}
            browse.setdefault('document_kind_source', None)
            browse.update(source_count=count, retained=bool(saved), _flags=(int(bool(saved)) | (2 if document else 0) |
                (4 if not row.get('document_kind') else 0) | (8 if not row.get('document_family') else 0) |
                (16 if api_only else 0) | (32 if video_only else 0)))
            self.db.execute('UPDATE components SET entry=?,record=? WHERE id=?',
                            (encoded(entry).decode(), encoded(browse).decode(), component))

    def finish(self, planned):
        if planned is None or 'path' in planned:
            return planned
        raw, = self.db.execute('SELECT body FROM plans WHERE id=?', (planned['plan'],)).fetchone()
        node = dict(version=1, **json.loads(raw))
        if node['kind'] == 'component-branch':
            node['children'] = {char: self.finish(value) for char, value in node['children'].items()}
            stats = {key: sum(child['stats'][key] for child in node['children'].values())
                     for key in ('entries', 'source_rows', 'documents', 'api', 'video')}
        else:
            members = {}
            for component, entry in node['members'].items():
                if 'pending' in entry:
                    raw, = self.db.execute('SELECT entry FROM components WHERE id=?', (component,)).fetchone()
                    entry = json.loads(raw)
                members[component] = entry
            node['members'] = members
            stats = dict(entries=len(members), source_rows=sum(entry['source_rows'] for entry in members.values()),
                         documents=sum(entry['flags']['document'] for entry in members.values()),
                         api=sum(entry['flags']['api'] for entry in members.values()),
                         video=sum(entry['flags']['video'] for entry in members.values()))
        node['stats'] = stats
        return dict(self.assets.put_node(node), native_sha256=node['native_sha256'], stats=stats)

    def _members(self, component, count):
        from congress_api.retention.catalog_validation import catalog_source_ids_digest
        digest = catalog_source_ids_digest(key for key, in self.db.execute(
            'SELECT source_id FROM member_ids WHERE id=? ORDER BY source_id', (component,)))
        raw, = self.db.execute('SELECT proof FROM components WHERE id=?', (component,)).fetchone()
        if digest != json.loads(raw)['validation']['source_ids_sha256']:
            raise ValueError('Derived viewer membership differs from the selected proof')
        keys = (key for key, in self.db.execute(
            'SELECT source_id FROM member_ids WHERE id=? ORDER BY source_order', (component,)))
        if count <= 64:
            return dict(ids=list(keys), rows=count)
        def leaves():
            pending = []
            for key in keys:
                pending.append(key)
                if len(pending) == 64:
                    yield dict(self.assets.put_node(dict(version=1, kind='member-leaf', ids=pending)), rows=len(pending))
                    pending = []
            if pending:
                yield dict(self.assets.put_node(dict(version=1, kind='member-leaf', ids=pending)), rows=len(pending))
        def combine(children):
            return dict(self.assets.put_node(dict(version=1, kind='member-branch', children=children)),
                        rows=sum(child['rows'] for child in children))
        return dict(root=build_page_levels(leaves(), combine, 16), rows=count)

    def ordered_records(self):
        # SQLite binary text order matches the maintained Arrow filename order.
        # Document ID is the deterministic tie breaker after a source regrouping.
        self.db.execute('CREATE TEMP TABLE ordered_records(id TEXT PRIMARY KEY,filename TEXT,record TEXT)')
        for component, raw in self.db.execute('SELECT id,record FROM components'):
            value = json.loads(raw)
            self.db.execute('INSERT INTO ordered_records VALUES (?,?,?)', (component, value['filename'], raw))
        yield from (json.loads(raw) for raw, in self.db.execute(
            'SELECT record FROM ordered_records ORDER BY filename IS NULL,filename,id'))


def public_component(assets, root, document_id):
    """Resolve one stable document against the exact public component root."""
    from congress_api.retention.partition_routing import key_hash
    digest, current, prefix = key_hash(document_id), root, ''
    while current is not None:
        node = assets.read_node(current)
        if node.get('prefix') != prefix:
            raise ValueError('Viewer component routing prefix differs')
        if node.get('kind') == 'component-leaf':
            return node['members'].get(document_id)
        if node.get('kind') != 'component-branch':
            raise ValueError('Unknown viewer component page')
        char = digest[len(prefix)]
        prefix += char
        current = node['children'].get(char)
    return None


def native_requirements(viewer, policy, compression=DEFAULT_COMPRESSION_POLICY):
    """Compute reuse requirements once, separately from native operation names."""
    from dataclasses import asdict
    import inspect
    import pyarrow
    from congress_api.retention import saved_responses, docspec, catalog_partitions
    files = [Path(__file__).with_name(name) for name in
             ('filename_observations.py', 'filename_details.py', 'filename_budget.py', 'filename_json_stream.py', 'filename_compression.py', 'filename_renderer_state.py')]
    files += [Path(__file__), *[Path(module.__file__) for module in (saved_responses, docspec, catalog_partitions)]]
    return dict(renderer='native-viewer-v1', policy=asdict(policy), compression=compression._asdict(), pyarrow=pyarrow.__version__,
        implementation=sha256(encoded(dict(
            owners=[inspect.getsource(owner) for owner in (NativeSourceAssets, NativeComponents, BrowsePages,
                                                           browse_key, build_page_levels,
                                                           viewer.api_reference, viewer.video_reference)],
            files={str(path.name): sha256(path.read_bytes()).hexdigest() for path in files}))).hexdigest())


def _reachable_assets(assets, roots):
    """Keep only newly built reachable objects; old immutable assets remain refs."""
    reached, visited = set(), set()
    def walk(value):
        if isinstance(value, dict):
            if {'path', 'bytes', 'sha256'} <= value.keys():
                path = value['path']
                if path in visited:
                    return
                visited.add(path)
                if path not in assets.identities:
                    return  # The previous qualified publication owns this asset.
                reached.add(path)
                if path.endswith('/page.json'):
                    walk(assets.read_node(value))
                return
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(roots)
    discarded = set(assets.identities) - reached
    if assets.state:
        assets.state.discard(assets,discarded)
    else:
        for path in discarded:
            (assets.root / path).unlink()
            del assets.identities[path]


def publication_basis(manifest):
    """The selected serving roots and their exact catalog identity."""
    return {name: manifest[name] for name in
            ('version', 'source_manifest', 'source_identity', 'source_selection', 'requirements', 'roots', 'files')} | {
                'info': {name: value for name, value in manifest['info'].items() if name != 'publication_version'}}


def validate_publication(assets, manifest):
    """Check bounded retained proof, without revisiting immutable old payloads."""
    if manifest.get('version') != 6:
        raise ValueError('Expected a stable viewer publication')
    if assets.read_node(manifest['proof']) != dict(version=1, kind='viewer-proof', publication=publication_basis(manifest)):
        raise ValueError('Viewer roots differ from their retained selection proof')
    selected = assets.read_node(manifest['source_selection'])
    identity = manifest['source_identity']
    if (identity.get('selector_sha256') != sha256(encoded(manifest['source_manifest'])).hexdigest()
            or manifest['source_manifest'] != dict(version=2, selection=identity['selected_ref'])
            or manifest['source_selection']['sha256'] != identity['selected_ref']['sha256']):
        raise ValueError('Viewer native selection identity differs')
    roots, counts = manifest['roots'], selected['counts']
    for name, native in (('sources', selected['dependency']['source_root']), ('components', selected['components'])):
        if (roots[name].get('native_sha256') if roots[name] else None) != (native['sha256'] if native else None):
            raise ValueError('Viewer root differs from the selected native root')
    if (manifest['info']['rows'] != counts['source_rows'] or manifest['info']['entries'] != counts['document_rows']
            or (roots['browse']['rows'] if roots['browse'] else 0) != counts['document_rows']
            or (roots['sources']['stats']['rows'] if roots['sources'] else 0) != counts['source_rows']
            or (roots['components']['stats']['entries'] if roots['components'] else 0) != counts['document_rows']
            or (roots['components']['stats']['source_rows'] if roots['components'] else 0) != counts['source_rows']):
        raise ValueError('Viewer counts differ from the selected native catalog')
    return selected


def write_inventory(assets):
    """Keep the startup manifest constant-size; each inventory page has <=64 refs."""
    items, head, count = sorted(assets.identities.items()), None, 0
    for start in range(0, len(items), 64):
        group = items[start:start + 64]
        head = assets.put_node(dict(version=1, kind='asset-inventory', previous=head,
            assets=[dict(path=path, bytes=proof['bytes'], sha256=proof['sha256']) for path, proof in group]))
        count += len(group)
    return dict(head=head, count=count)


def iterator_inventory(assets, inventory):
    """Yield new asset refs and the bounded inventory pages themselves."""
    current, count, visited = inventory['head'], 0, set()
    if type(inventory['count']) is not int or inventory['count'] < 0:
        raise ValueError('Invalid viewer inventory count')
    while current:
        if current['path'] in visited:
            raise ValueError('Repeated viewer inventory page')
        visited.add(current['path'])
        yield current
        node = assets.read_node(current)
        if node.get('version') != 1 or node.get('kind') != 'asset-inventory' or not 0 < len(node['assets']) <= 64:
            raise ValueError('Invalid viewer inventory page')
        for ref in node['assets']:
            path, digest = ref['path'], ref['sha256']
            if (not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest)
                    or path not in [f'releases/{digest[:32]}/{digest[32:]}/viewer-v2/{name}' for name in
                        ('page.json', 'filenames.parquet', 'documents.parquet', 'details.parquet', 'observations.bin',
                         'observation_rows.bin', 'observation_index.json')]
                    or type(ref['bytes']) is not int or ref['bytes'] < 0 or path in visited):
                raise ValueError('Invalid or repeated viewer inventory asset')
            visited.add(path)
            count += 1
            if count > inventory['count']:
                raise ValueError('Viewer inventory exceeds its declared count')
            yield ref
        current = node.get('previous')
    if count != inventory['count']:
        raise ValueError('Viewer inventory count differs')


def publish_selected(snapshot, target, *, viewer, previous=None, read_asset=None, review_identities=None,
                     prior_review_binding=None, compression_policy=DEFAULT_COMPRESSION_POLICY,
                     renderer_upgrade=False, resume_upgrade=False, decoded_policy, stage_timings=None, stage_event=None, memory_metrics=None):
    """Prepare stable assets from one selected snapshot; never select publication."""
    from contextlib import closing, ExitStack
    from datetime import datetime, timezone
    import sqlite3
    import time
    from congress_api.retention.viewer_inventory import PreparedManifest
    if previous is not None and prior_review_binding is not None:
        raise ValueError('Prior review binding is only for initial file-catalog adoption')
    validate_compression(compression_policy)
    requirements = native_requirements(viewer, decoded_policy, compression_policy)
    if previous is not None and previous.get('version') != 6:
        raise ValueError('Native viewer reuse requires a qualified stable publication')
    if resume_upgrade and not renderer_upgrade:
        raise ValueError('Renderer upgrade resume requires explicit renderer_upgrade')
    if renderer_upgrade and (previous is None or previous.get('requirements') == requirements):
        raise ValueError('Renderer upgrade requires a prior publication with changed rendering rules')
    if previous is not None and previous.get('requirements') != requirements and not renderer_upgrade:
        raise ValueError('Viewer rendering rules changed; an explicit qualified upgrade is required')
    target = Path(target)
    if target.is_symlink() or target.exists() and (not target.is_dir() or any(target.iterdir()) and not resume_upgrade):
        raise ValueError('Viewer output must be a fresh empty directory')
    target.mkdir(parents=True, exist_ok=True)
    assets = ViewerAssets(target, read_asset=read_asset)
    if previous:
        validate_publication(assets, previous)
    pages = BrowsePages(assets)
    metrics = memory_metrics if memory_metrics is not None else {}
    timings = stage_timings if stage_timings is not None else {}
    started = time.perf_counter()
    state = None
    def stage(name, operation):
        if stage_event:
            stage_event(dict(event='stage_started', stage=name))
        before = time.perf_counter()
        result = state.run('stage:'+name,operation) if state else operation()
        timings[name] = time.perf_counter() - before
        if stage_event:
            stage_event(dict(event='stage_completed', stage=name, seconds=timings[name]))
        return result
    old = previous.get('roots', {}) if previous and not renderer_upgrade else {}
    with ExitStack() as owned:
        if renderer_upgrade:
            from filename_renderer_state import RendererState
            import filename_review_binding as review_binding
            review_inputs = review_binding.load_identities(review_identities) if review_identities is not None else None
            binding = dict(version=1,source=snapshot.identity,previous=sha256(encoded(previous)).hexdigest(),
                requirements=requirements,reviews=review_inputs)
            state=owned.enter_context(RendererState(target,binding,resume=resume_upgrade,event=stage_event,
                cache_kib=decoded_policy.sqlite_cache_kib))
            assets.state=state;state.restore(assets);db=state.db
            finished=state.result('finished')
            if finished is not None:
                manifest=json.loads(finished[0]);validate_publication(assets,manifest)
                return PreparedManifest(manifest,assets.identities)
        else:
            directory=owned.enter_context(tempfile.TemporaryDirectory(prefix='native-viewer-'))
            db=owned.enter_context(closing(sqlite3.connect(Path(directory)/'components.sqlite')))
            db.executescript(f'PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; '
                             f'PRAGMA cache_size=-{decoded_policy.sqlite_cache_kib};')
        components = NativeComponents(snapshot, assets, pages, db, viewer=viewer,
                                      policy=decoded_policy, metrics=metrics, compression_policy=compression_policy)
        planned = stage('component_scope', lambda: components.plan(snapshot.selection['components'], old.get('components')))
        stage('component_preparation', components.prepare)
        component_root = stage('component_metadata', lambda: components.finish(planned))
        source_root = stage('source_preparation', lambda: NativeSourceAssets(snapshot, assets,
            policy=decoded_policy, metrics=metrics, compression_policy=compression_policy).render(snapshot.selection['dependency']['source_root'], old.get('sources')))
        changed, = db.execute('SELECT count(*) FROM components').fetchone()
        retired, = db.execute('SELECT count(*) FROM retired').fetchone()
        def browse():
            if not previous or renderer_upgrade:
                return pages.build(components.ordered_records())
            if not changed and not retired:
                return old.get('browse')
            return pages.change(old.get('browse'), remove=(json.loads(raw) for raw, in db.execute(
                'SELECT record FROM retired ORDER BY id')), add=components.ordered_records())
        browse_root = stage('browse_preparation', browse)
        counts = snapshot.selection['counts']
        component_stats = component_root['stats'] if component_root else dict(entries=0, source_rows=0, documents=0, api=0, video=0)
        source_stats = source_root['stats'] if source_root else dict(rows=0, bytes=0, facets={})
        if (component_stats['entries'] != counts['document_rows'] or component_stats['source_rows'] != counts['source_rows']
                or source_stats['rows'] != counts['source_rows'] or (browse_root['rows'] if browse_root else 0) != counts['document_rows']):
            raise ValueError('Prepared viewer roots differ from the exact selected catalog counts')
        catalog_id = snapshot.schemas['filenames'].metadata[b'catalog_id'].decode()
        info = dict(catalog_id=catalog_id, rows=counts['source_rows'], entries=counts['document_rows'],
            documents=component_stats['documents'], capture_records=counts['document_rows'] - component_stats['documents'],
            api_reference_groups=component_stats['api'], video_reference_groups=component_stats['video'],
            fields=snapshot.schemas['filenames'].names, document_fields=snapshot.schemas['documents'].names,
            facets={field: sorted(source_stats['facets'].get(field, {})) for field in viewer.FILTERS},
            bytes=source_stats['bytes'], generation=snapshot.identity['selected_ref']['sha256'][:32],
            house_naming_version=snapshot.schemas['filenames'].metadata.get(b'house_naming_version', b'unknown').decode())
        roots = dict(sources=source_root, components=component_root, browse=browse_root)
        def node(value, prior=None):
            raw = encoded(value)
            return prior if prior and prior['bytes'] == len(raw) and prior['sha256'] == sha256(raw).hexdigest() else assets.put_node(value)
        files = {}
        if review_identities is not None:
            import filename_review_binding as binding
            identities = review_inputs if state else binding.load_identities(review_identities)
            prior_binding = assets.read_node(previous['files']['review_binding']) if previous and previous['files'].get('review_binding') else prior_review_binding
            placement = binding.bind_selected(catalog_id, identities,
                lambda document: public_component(assets, component_root, document), previous=prior_binding)
            files['review_binding'] = node(placement, previous['files'].get('review_binding') if previous else None)
        selection = node(snapshot.selection, previous.get('source_selection') if previous else None)
        manifest = dict(version=6, published_at=state.created if state else datetime.now(timezone.utc).isoformat(),
            info=info, source_manifest=snapshot.manifest, source_identity=snapshot.identity,
            requirements=requirements, roots=roots, files=files, source_selection=selection)
        manifest['proof'] = node(dict(version=1, kind='viewer-proof', publication=publication_basis(manifest)),
                                 previous.get('proof') if previous else None)
        validate_publication(assets, manifest)
        stage('inventory', lambda: _reachable_assets(assets, [roots, files, selection, manifest['proof']]))
        manifest['inventory'] = write_inventory(assets)
        uploads = set(assets.identities)
        # These two bounded controls preserve offline/restart custody even when
        # their unchanged remote assets need no upload in this publication.
        for reference in (selection, manifest['proof']):
            if reference['path'] not in assets.identities:
                assets.put_node(assets.read_node(reference))
        if previous:
            manifest['reuse_base'] = dict(catalog_id=previous['info']['catalog_id'],
                manifest_identity=sha256(encoded(previous)).hexdigest(), source_identity=previous['source_identity'])
        (target / 'manifest.json').write_bytes(encoded(manifest))
        assets.identities['manifest.json'] = file_identity(target / 'manifest.json')
        if state:
            state.remember('manifest.json',assets.identities['manifest.json'])
            state.run('finished',lambda:dict(manifest))
        timings['total_seconds'] = time.perf_counter() - started
        metrics['new_asset_files'] = len(uploads)
        metrics['new_asset_bytes'] = sum(assets.identities[path]['bytes'] for path in uploads)
        metrics['retained_control_bytes'] = sum(proof['bytes'] for path, proof in assets.identities.items()
                                                if path not in uploads and path != 'manifest.json')
        metrics['output_writes'] = assets.writes + 1  # Includes the final manifest.
        metrics['output_bytes_written'] = assets.written_bytes + (target / 'manifest.json').stat().st_size
        metrics['output_metadata_writes'] = assets.metadata_writes + 1
        metrics['metadata_reads'] = assets.reads
        return PreparedManifest(manifest, assets.identities)


def locate_source_asset(assets, manifest, source_id):
    """Locate a bounded candidate source asset, without claiming row presence.

    The caller reads its source_id column to prove presence and select that exact
    row. Missing routing children prove absence. No logical-table export occurs.
    """
    from congress_api.retention.partition_routing import key_hash
    if not isinstance(source_id, str) or len(source_id) != 64 or any(
            char not in '0123456789abcdef' for char in source_id):
        raise ValueError('Expected a stable source ID')
    digest, current, prefix = key_hash(source_id), manifest['roots']['sources'], ''
    while current is not None:
        node = assets.read_node(current)
        if node.get('prefix') != prefix:
            raise ValueError('Viewer source routing prefix differs')
        if node.get('kind') == 'source-leaf':
            return node['source']
        if node.get('kind') != 'source-branch':
            raise ValueError('Unknown viewer source page')
        char = digest[len(prefix)]
        prefix += char
        current = node['children'].get(char)
    return None


def component_source_ids(assets, component):
    """Stream complete stable membership in the retained source encounter order."""
    membership = component['members']
    def walk(reference):
        node = assets.read_node(reference)
        if node.get('kind') == 'member-leaf':
            if not 0 < len(node['ids']) <= 64 or len(node['ids']) != reference['rows']:
                raise ValueError('Invalid viewer member leaf')
            yield from node['ids']
        elif node.get('kind') == 'member-branch':
            if (not 0 < len(node['children']) <= 16
                    or sum(child['rows'] for child in node['children']) != reference['rows']):
                raise ValueError('Invalid viewer member branch')
            for child in node['children']:
                yield from walk(child)
        else:
            raise ValueError('Unknown viewer membership page')
    count = 0
    values = membership['ids'] if 'ids' in membership else walk(membership['root'])
    for key in values:
        if not isinstance(key, str) or len(key) != 64 or any(char not in '0123456789abcdef' for char in key):
            raise ValueError('Invalid stable viewer member ID')
        count += 1
        yield key
    if count != membership['rows'] or count != component['source_rows']:
        raise ValueError('Viewer component membership count differs')
