"""Select exact native catalog components with the existing conditional selector."""
import base64
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pyarrow as pa

from .catalog_batches import CatalogComponentReader, SelectedCatalogTable, same_logical_catalog_schema, can_read_catalog_schema
from .catalog_publication import MANIFEST_KEY
from .catalog_validation import CatalogReferenceCheck, catalog_reference_requirements
from .immutable_metadata import MetadataObjects, encoded
from .partition_routing import RoutingPages, key_hash
from .write_recovery import reconcile_lost_acknowledgment


class CatalogComponents:
    """Route bounded logical member references; native physical pins stay shared."""
    def __init__(self, store):
        self.routes = RoutingPages(store, 'catalog-component-selection-v2')
        self.routes.objects.max_cache_entries = 16

    def _members(self, prefix, value):
        members = value.get('members', {}) if value is not None else {}
        if (not isinstance(members, dict) or len(members) > 64
                or any(not name or not key_hash(name).startswith(prefix)
                       or not isinstance(ref, dict) or ref.get('component') != name or 'page' not in ref
                       for name, ref in members.items())):
            raise ValueError('Invalid selected catalog component leaf')
        return members

    def lookup(self, root, component):
        prefix, value = self.routes.lookup(root, component)
        return self._members(prefix, value).get(component)

    def items(self, root):
        for prefix, value in self.routes.leaf_items(root):
            yield from sorted(self._members(prefix, value).items())

    def apply(self, root, *, retired, prepared):
        """Rewrite affected reference leaves only, including bulk initial adoption.

        Changed member metadata is staged on disk. Recursive hash-prefix splits
        collect at most 64 member references per leaf; the routing owner consumes
        those leaves as a stream and retains at most 16 child references.
        """
        with TemporaryDirectory(prefix='catalog-components-') as directory, closing(
                sqlite3.connect(Path(directory) / 'changes.sqlite')) as db:
            db.executescript('''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192;
                CREATE TABLE changes(name TEXT PRIMARY KEY,prefix TEXT,reference TEXT,retired INTEGER);
                CREATE INDEX changed_prefixes ON changes(prefix);
                CREATE TABLE members(name TEXT PRIMARY KEY,digest TEXT,reference TEXT);
                CREATE INDEX member_hashes ON members(digest);''')
            for component, reference in retired:
                prefix, value = self.routes.lookup(root, component)
                if self._members(prefix, value).get(component) != reference:
                    raise ValueError('Retired catalog component differs from selected ownership')
                try:
                    db.execute('INSERT INTO changes VALUES (?,?,NULL,1)', (component, prefix))
                except sqlite3.IntegrityError as error:
                    raise ValueError('Repeated retired catalog component') from error
            for component, reference in prepared:
                if reference.get('component') != component or 'page' not in reference:
                    raise ValueError('Prepared catalog component reference differs')
                prefix, value = self.routes.lookup(root, component)
                prior = db.execute('SELECT retired,reference FROM changes WHERE name=?', (component,)).fetchone()
                if ((prior and prior[1] is not None)
                        or self._members(prefix, value).get(component) is not None and not prior):
                    raise ValueError('Prepared catalog component collides with selected ownership')
                if prior:
                    db.execute('UPDATE changes SET reference=? WHERE name=?', (encoded(reference).decode(), component))
                else:
                    db.execute('INSERT INTO changes VALUES (?,?,?,0)', (component, prefix, encoded(reference).decode()))

            def leaves(prefix):
                count, = db.execute('SELECT count(*) FROM members WHERE digest LIKE ?', (prefix + '%',)).fetchone()
                if not count:
                    yield prefix, None
                    return
                if count <= 64:
                    members = {name: json.loads(ref) for name, ref in db.execute(
                        'SELECT name,reference FROM members WHERE digest LIKE ? ORDER BY name', (prefix + '%',))}
                    value = dict(members=members)
                    if len(encoded(dict(version=1, prefix=prefix, value=value))) <= self.routes.objects.max_bytes:
                        yield prefix, value
                        return
                if len(prefix) == 64:
                    raise ValueError('Catalog component references exceed a bounded leaf')
                for char in '0123456789abcdef':
                    yield from leaves(prefix + char)

            result = root
            for prefix, in db.execute('SELECT DISTINCT prefix FROM changes ORDER BY prefix'):
                db.execute('DELETE FROM members')
                # Prefixes were resolved against the captured root. Replacing a
                # sibling leaf cannot change another leaf's original membership.
                # Resolve a representative changed key to retrieve this one leaf.
                key, = db.execute('SELECT name FROM changes WHERE prefix=? LIMIT 1', (prefix,)).fetchone()
                found, value = self.routes.lookup(root, key)
                if found != prefix:
                    raise ValueError('Catalog component routing basis differs')
                db.executemany('INSERT INTO members VALUES (?,?,?)',
                    ((name, key_hash(name), encoded(ref).decode())
                     for name, ref in self._members(prefix, value).items()))
                for name, reference in db.execute('SELECT name,reference FROM changes WHERE prefix=?', (prefix,)):
                    db.execute('DELETE FROM members WHERE name=?', (name,))
                    if reference is not None:
                        db.execute('INSERT INTO members VALUES (?,?,?)', (name, key_hash(name), reference))
                result = self.routes.replace_stream(result, prefix, leaves(prefix))
            return result


def _schema(text):
    try:
        return pa.ipc.read_schema(pa.BufferReader(base64.b64decode(text, validate=True)))
    except (TypeError, ValueError, pa.ArrowException) as error:
        raise ValueError('Invalid selected logical catalog schema') from error


class NativeCatalogSnapshot:
    """An exact logical selection; table scans never construct a full pair file."""
    def __init__(self, store, selector, selected_bytes, version, *, native=None):
        self.store, self.manifest, self.version, self.native = store, selector, version, native
        self.identity = dict(selector_sha256=sha256(selected_bytes).hexdigest(), selected_ref=selector['selection'])
        self.selection = MetadataObjects(store, 'catalog-selections-v2', max_cache_entries=4).read(selector['selection'])
        value = self.selection
        if (value.get('version') != 2 or not isinstance(value.get('requirements'), dict)
                or not value['requirements'] or not isinstance(value.get('dependency'), dict)):
            raise ValueError('Invalid selected native catalog')
        self.schemas = {label: _schema(value['schemas'][label]) for label in ('filenames', 'documents')}
        CatalogReferenceCheck(self.schemas['filenames'], self.schemas['documents'])
        for label in ('source_rows', 'document_rows'):
            if type(value['counts'].get(label)) is not int or value['counts'][label] < 0:
                raise ValueError('Invalid selected native catalog row count')
        self.components = CatalogComponents(store)

    @property
    def filenames_path(self):
        raise ValueError('Selected native catalog requires table("filenames"); it has no complete-file path')

    @property
    def documents_path(self):
        raise ValueError('Selected native catalog requires table("documents"); it has no complete-file path')

    def component_ref(self, document_id):
        return self.components.lookup(self.selection['components'], document_id)

    def table(self, label, *, max_ordered_bytes, native=None):
        client = native or self.native
        if client is None:
            raise ValueError('Native catalog table reads require the configured native client')
        count = {'filenames': 'source_rows', 'documents': 'document_rows'}[label]
        return SelectedCatalogTable(self.schemas[label], lambda: self.components.items(self.selection['components']),
            store=self.store, native=client, label=label, rows=self.selection['counts'][count],
            max_ordered_bytes=max_ordered_bytes)

    def changes_since(self, identity):
        """Yield exact old/new scopes since a retained selection identity.

        Only immutable selection/proof metadata is read. A disposable position
        index reverses the ancestry walk without retaining history in memory.
        """
        from .catalog_scope import read_catalog_scope
        objects = MetadataObjects(self.store, 'catalog-selections-v2', max_cache_entries=4)
        with TemporaryDirectory(prefix='catalog-changes-') as directory, closing(
                sqlite3.connect(Path(directory) / 'changes.sqlite')) as db:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                'CREATE TABLE changes(position INTEGER PRIMARY KEY,body TEXT); '
                'CREATE TABLE seen(identity TEXT PRIMARY KEY);')
            current, selected, position = self.identity, self.selection, 0
            while current != identity:
                marker = encoded(current).decode()
                try:
                    db.execute('INSERT INTO seen VALUES (?)', (marker,))
                except sqlite3.IntegrityError as error:
                    raise ValueError('Catalog scope ancestry contains a cycle') from error
                reference = selected['scope']
                proof = read_catalog_scope(self.store, reference)
                if proof['dependency_after'] != selected['dependency'] or proof['schemas'] != selected['schemas']:
                    raise ValueError('Catalog scope differs from the selected dependency/schema basis')
                before = proof['base']
                body = dict(before=before, after=current, scope_reference=reference, scope=proof)
                db.execute('INSERT INTO changes VALUES (?,?)', (position, encoded(body).decode()))
                position += 1
                if before == identity:
                    break
                if before.get('selected_ref') is None:
                    raise ValueError('Catalog cursor is not an ancestor of this native selection')
                expected_selector = encoded(dict(version=2, selection=before['selected_ref']))
                if before.get('selector_sha256') != sha256(expected_selector).hexdigest():
                    raise ValueError('Catalog scope ancestry selector binding differs')
                selected = objects.read(before['selected_ref'])
                current = before
            for body, in db.execute('SELECT body FROM changes ORDER BY position DESC'):
                yield json.loads(body)

    def _surviving_changed_components(self, identity):
        from .catalog_scope import iterator_scope_components
        with TemporaryDirectory(prefix='catalog-changed-members-') as directory, closing(
                sqlite3.connect(Path(directory) / 'members.sqlite')) as db:
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                             'CREATE TABLE members(component TEXT PRIMARY KEY,reference TEXT);')
            for change in self.changes_since(identity):
                for component, _ in iterator_scope_components(self.store, change['scope'], 'retired'):
                    db.execute('DELETE FROM members WHERE component=?', (component,))
                for component, reference in iterator_scope_components(self.store, change['scope'], 'prepared'):
                    db.execute('INSERT OR REPLACE INTO members VALUES (?,?)', (component, encoded(reference).decode()))
            for component, reference in db.execute('SELECT component,reference FROM members ORDER BY component'):
                reference = json.loads(reference)
                if self.component_ref(component) != reference:
                    raise ValueError('Folded catalog change differs from the current component selection')
                yield component, reference

    def changed_sources_since(self, identity, *, max_ordered_bytes):
        """Read only latest surviving changed components, not obsolete versions."""
        reader = CatalogComponentReader(self.store)
        rows = sum(reader.read(reference)['validation']['counts']['source_rows']
                   for _, reference in self._surviving_changed_components(identity))
        return SelectedCatalogTable(self.schemas['filenames'],
            lambda: self._surviving_changed_components(identity), store=self.store, native=self.native,
            label='filenames', rows=rows, max_ordered_bytes=max_ordered_bytes)

    def changed_sources(self, change, *, which='prepared', max_ordered_bytes):
        """Read one scope's exact selected or retired source members only."""
        from .catalog_scope import read_catalog_scope, iterator_scope_components
        if which not in {'prepared', 'retired'}:
            raise ValueError('Catalog source changes must be prepared or retired')
        proof = read_catalog_scope(self.store, change['scope_reference'])
        if proof != change['scope'] or proof['base'] != change['before']:
            raise ValueError('Catalog source change differs from its retained scope')
        label = 'filenames'
        return SelectedCatalogTable(_schema(proof['schemas'][label]),
            lambda: iterator_scope_components(self.store, proof, which), store=self.store,
            native=self.native, label=label, rows=proof['counts'][which + '_source_rows'],
            max_ordered_bytes=max_ordered_bytes)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        pass  # Each scan owns and closes its temporary metadata index.


def read_native_catalog(store, selected, *, version, native=None):
    selector = json.loads(selected)
    if set(selector) != {'version', 'selection'} or selector.get('version') != 2:
        raise ValueError('Invalid native catalog selector')
    return NativeCatalogSnapshot(store, selector, selected, version, native=native)


def publish_native_catalog(store, scope_reference, *, previous, adoption_reference=None):
    """Admit a durable scope proof, then select its exact combination once."""
    from .catalog_scope import read_catalog_scope, catalog_scope_requirements, iterator_scope_components
    proof = read_catalog_scope(store, scope_reference, requirements=catalog_scope_requirements())
    if proof['base'] != previous.identity:
        raise ValueError('Catalog scope has a different selected base')
    requirements = catalog_reference_requirements()
    if isinstance(previous, NativeCatalogSnapshot):
        base = previous.selection
        root, dependency, counts = base['components'], base['dependency'], base['counts']
    else:
        if previous.manifest is not None or previous.files:
            if adoption_reference is None:
                raise ValueError('Existing file catalog requires qualified explicit native adoption')
            from .catalog_adoption import read_adoption_proof
            read_adoption_proof(store, adoption_reference, previous=previous,
                                scope_reference=scope_reference, scope=proof)
        root, dependency, counts = None, None, dict(source_rows=0, document_rows=0)
    interpretation = previous.selection.get('interpretation') if isinstance(previous, NativeCatalogSnapshot) else None
    if 'interpretation_before' in proof and proof['interpretation_before'] != interpretation:
        raise ValueError('Catalog scope source interpretation basis differs')
    interpretation = proof.get('interpretation_after', interpretation)
    if proof.get('source_update') is not None:
        from .source_update_proof import read_source_update
        source_update = read_source_update(store, proof['source_update'])
        if (source_update['base'] != previous.identity or source_update['before'] != proof.get('interpretation_before')
                or source_update['after'] != proof.get('interpretation_after')):
            raise ValueError('Catalog source interpretation basis differs')
        interpretation = source_update['after']
    if proof['dependency_before'] != dependency:
        raise ValueError('Catalog scope dependency basis differs')
    schemas = {label: _schema(proof['schemas'][label]) for label in ('filenames', 'documents')}
    CatalogReferenceCheck(schemas['filenames'], schemas['documents'])
    complete = proof.get('complete_replacement') is True
    if complete:
        if (proof.get('source_update') is None or source_update.get('purpose') not in {'qualification', 'rule-upgrade'}
                or counts != dict(source_rows=proof['counts']['retired_source_rows'],
                                  document_rows=proof['counts']['retired_document_rows'])):
            raise ValueError('Complete catalog replacement omits selected ownership or source qualification')
    if (isinstance(previous, NativeCatalogSnapshot)
            and base['requirements'] != requirements and not complete):
        raise ValueError('Selected catalog validator requirements changed; revalidation is required')
    if isinstance(previous, NativeCatalogSnapshot) and any(
            not can_read_catalog_schema(previous.schemas[label], schemas[label]) for label in schemas) and not complete:
        raise ValueError('Catalog schema change requires complete semantic revalidation')
    reader = CatalogComponentReader(store, requirements=requirements)

    def admitted():
        for component, reference in iterator_scope_components(store, proof, 'prepared'):
            value = reader.read(reference)
            if value['component'] != component or value['candidate'] != proof['candidate']:
                raise ValueError('Prepared catalog component differs from scope proof')
            if any(not same_logical_catalog_schema(_schema(value['tables'][label]['schema']), schemas[label])
                   for label in schemas):
                raise ValueError('Prepared catalog component schema differs from scope proof')
            yield component, reference

    selected_root = CatalogComponents(store).apply(root,
        retired=iterator_scope_components(store, proof, 'retired'), prepared=admitted())
    new_counts = {label + '_rows': counts[label + '_rows'] - proof['counts']['retired_' + label + '_rows']
                  + proof['counts']['prepared_' + label + '_rows'] for label in ('source', 'document')}
    if any(value < 0 for value in new_counts.values()):
        raise ValueError('Catalog scope produces negative selected counts')
    retained_adoption = adoption_reference or (previous.selection.get('adoption') if isinstance(previous, NativeCatalogSnapshot) else None)
    value = dict(version=2, components=selected_root, dependency=proof['dependency_after'],
                 schemas=proof['schemas'], counts=new_counts, requirements=requirements, scope=scope_reference,
                 adoption=retained_adoption, interpretation=interpretation)
    selected = MetadataObjects(store, 'catalog-selections-v2').put(value)
    payload = encoded(dict(version=2, selection=selected))
    reconcile_lost_acknowledgment(
        lambda: store.put_catalog_manifest(payload, expected_version=previous.version),
        lambda: store.read(MANIFEST_KEY), payload)
    return dict(manifest_key=MANIFEST_KEY, selection=selected,
                catalog_id=schemas['filenames'].metadata[b'catalog_id'].decode(), counts=new_counts)
