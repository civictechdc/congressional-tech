"""Offline, bounded Catalog-state comparison; never changes the production reader.

The candidate only packs positional memberships. Both arms run the actual
publisher against the same closed, projected retained-metadata fixture.
"""
from array import array
from bisect import bisect_right
import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
VIEWER = ROOT / 'docs/youtube-coverage/research/scripts/view_document_filenames.py'
CEILING = 2 * 1024**3
OUTPUT_CEILING = 1024**3
DEADLINE = 600


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackedMembers:
    """Experiment-only CSR offsets and row IDs, preserving list-valued access."""
    def __init__(self, entries, groups):
        self.offsets = array('I', [0]) * (groups + 1)
        for group in entries:
            self.offsets[group + 1] += 1
        for group in range(groups):
            self.offsets[group + 1] += self.offsets[group]
        positions = array('I', self.offsets)
        self.rows = array('I', [0]) * len(entries)
        for row, group in enumerate(entries):
            self.rows[positions[group]] = row
            positions[group] += 1

    def __len__(self):
        return len(self.offsets) - 1

    def __getitem__(self, group):
        if not 0 <= group < len(self):
            raise IndexError(group)
        return list(self.rows[self.offsets[group]:self.offsets[group + 1]])


def viewer(arm):
    if arm == 'baseline':
        return load(VIEWER, 'measured_catalog')
    source = VIEWER.read_text()
    original = "self.entry_ids = [entries[key] for key in self.table['document_id'].to_pylist()]"
    compact = "self.entry_ids = array('I', (entries[key] for key in self.table['document_id'].to_pylist()))"
    membership = """self.members = [[] for _ in range(len(self.documents))]
        for row_id, entry in enumerate(self.entry_ids):
            self.members[entry].append(row_id)"""
    assert source.count(original) == source.count(membership) == 1
    spec = importlib.util.spec_from_file_location('measured_catalog', VIEWER)
    module = importlib.util.module_from_spec(spec)
    module.PackedMembers = PackedMembers
    exec(compile(source.replace(original, compact).replace(membership,
        'self.members = PackedMembers(self.entry_ids, len(self.documents))'), str(VIEWER), 'exec'), module.__dict__)
    return module


def fixture(retained, destination):
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    module = viewer('baseline')
    source = retained
    destination.mkdir(parents=True, exist_ok=False)
    retained_manifest = source.parents[1] / 'indexes/catalog.json'
    original_manifest_bytes = retained_manifest.read_bytes()
    original_manifest = json.loads(original_manifest_bytes)
    for item in original_manifest['files'].values():
        path = source.parents[1] / item['key']
        assert path.parent == source and path.stat().st_size == item['bytes'] and digest(path) == item['sha256']
    (destination / 'retained-manifest.json').write_bytes(original_manifest_bytes)
    with pq.ParquetFile(source / 'documents.parquet', pre_buffer=False) as documents:
        columns = [name for name in module.LIST_COLUMNS if name in documents.schema_arrow.names]
        # 31 evenly spaced complete row groups: 31,744 retained document groups.
        groups = [i * (documents.num_row_groups - 1) // 30 for i in range(31)]
        selected = documents.read_row_groups(groups, columns=columns)
    identifiers = selected['document_id']
    chunks = []
    with pq.ParquetFile(source / 'document-filenames.parquet', pre_buffer=False) as filenames:
        observation_type = filenames.schema_arrow.field('source_occurrences').type
        for group in range(filenames.num_row_groups):
            keys = filenames.read_row_group(group, columns=['document_id'])['document_id']
            mask = pc.is_in(keys, value_set=identifiers)
            if pc.any(mask).as_py():
                chunks.append(filenames.read_row_group(group, columns=columns).filter(mask))
    sources = pa.concat_tables(chunks)
    assert set(selected['source_id'].to_pylist()) <= set(sources['source_id'].to_pylist())
    extra_sources, extra_documents = [], []
    urls = [ ['https://api.congress.gov/v3/hearing/119/house/1'],
             ['https://youtu.be/-oNSVIeynzI'],
             ['https://api.congress.gov/v3/bill/119/hr/1', 'https://committee.test/actual.pdf'],
             ['https://youtu.be/-oNSVIeynzI', 'https://committee.test/actual-video.pdf'],
             [None], ['https://committee.test/error'], ['https://committee.test/雪'],
             ['https://committee.test/a', 'https://committee.test/b', 'https://committee.test/c'] ]
    for group, values in enumerate(urls):
        members = []
        for index, url in enumerate(values):
            row = dict.fromkeys(columns)
            row.update(document_id=hashlib.sha256(f'edge-document-{group}'.encode()).hexdigest(),
                source_id=hashlib.sha256(f'edge-source-{group}-{index}'.encode()).hexdigest(),
                filename=f'Edge {group} José 雪.pdf', source_url=url, body_key='edge-body' if group == 7 else None,
                record_role=['document'] if group != 5 else ['error-response'], format=['PDF'],
                document_kind=['statement'] if group == 7 else None, document_family=['statement'] if group == 7 else None)
            members.append(row)
        extra_sources.extend(members)
        extra_documents.append(members[-1])
    sources = pa.concat_tables([sources, pa.Table.from_pylist(extra_sources, schema=sources.schema)])
    selected = pa.concat_tables([selected, pa.Table.from_pylist(extra_documents, schema=selected.schema)])
    # State experiment: omit original large nested observations; the actual
    # publisher still exercises its observation path with typed null values.
    sources = sources.append_column('source_occurrences', pa.nulls(len(sources), type=observation_type))
    selected = selected.append_column('source_occurrences', pa.nulls(len(selected), type=observation_type))
    assert len(selected) <= 32768
    generation = 'c' * 32
    folder = destination / 'catalog-generations' / generation
    folder.mkdir(parents=True)
    (destination / 'indexes').mkdir()
    files = {}
    for name, table, filename in [('documents', selected, 'documents.parquet'),
                                  ('filenames', sources, 'document-filenames.parquet')]:
        path = folder / filename
        pq.write_table(table, path, row_group_size=1024, compression='zstd')
        files[name] = dict(key=str(path.relative_to(destination)), bytes=path.stat().st_size,
                           sha256=digest(path), rows=len(table))
    catalog_id = selected.schema.metadata[b'catalog_id'].decode()
    save(destination / 'indexes/catalog.json', dict(version=1, generation=generation, catalog_id=catalog_id, files=files))
    reviews = []
    for index, row in enumerate(extra_documents):
        members = [item['source_id'] for item in extra_sources if item['document_id'] == row['document_id']]
        reviews.append(dict(index=index, document_id=row['document_id'], body_key=row['body_key'], source_ids=members))
    reviews[2]['body_key'] = 'changed-body'
    reviews[3]['source_ids'].append('changed-source')
    reviews[4]['document_id'] = 'missing-document'
    save(destination / 'reviews.json', dict(version=1, catalog_id=catalog_id, review_sha256='d' * 64, rows=reviews))
    save(destination / 'fixture.json', dict(retained_document_row_groups=groups, documents=len(selected),
        sources=len(sources), arrow_bytes=dict(documents=selected.nbytes, sources=sources.nbytes),
        scope='Closed stratified retained LIST_COLUMNS projection plus 8 synthetic semantic edge groups; source_occurrences replaced with typed nulls, no body acquisition',
        input_files={p.name:dict(bytes=p.stat().st_size, sha256=digest(p)) for p in source.glob('*.parquet')},
        files=files))


def owned_size(value):
    seen = set()
    def visit(item):
        if id(item) in seen:
            return 0
        seen.add(id(item))
        size = sys.getsizeof(item)
        if isinstance(item, dict):
            size += sum(visit(k) + visit(v) for k, v in item.items())
        elif isinstance(item, (list, tuple, set)):
            size += sum(map(visit, item))
        elif isinstance(item, PackedMembers):
            size += visit(item.offsets) + visit(item.rows)
        return size
    return visit(value)


def highwater():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == 'darwin' else value * 1024


def arm(fixture_path, destination, kind, operation):
    import pyarrow as pa
    sys.path.insert(0, str(ROOT / 'apps/site/scripts'))
    module = viewer(kind)
    start = time.perf_counter()
    destination.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((fixture_path / 'indexes/catalog.json').read_text())
    file = fixture_path / manifest['files']['filenames']['key']
    if operation == 'measure':
        with module.Catalog(file, search_indexes=False) as catalog:
            loaded = time.perf_counter() - start
            peak = highwater()
            arrow = {'sources': catalog.table.nbytes, 'documents': catalog.documents.nbytes,
                     'order': catalog.order.nbytes}
            state = {name: owned_size(getattr(catalog, name)) for name in (
                'source_ids', 'document_id_entries', 'entry_ids', 'members', 'preferred_sources', 'entry_positions',
                'saved_responses', 'document_entries', 'api_sources', 'api_entries', 'video_sources', 'video_entries',
                'filter_text', '_complete_groups', 'info')}
            info = catalog.info
        save(destination / 'receipt.json', dict(arm=kind, operation=operation, constructor_seconds=loaded,
            constructor_highwater_rss=peak, arrow_bytes=arrow, approximate_python_owned_bytes=state, info=info,
            search_indexes_built=bool(catalog.filter_text), readers_closed=catalog.file.closed and catalog.document_file.closed))
    else:
        publisher = load(ROOT / 'apps/site/scripts/publish-filename-viewer.py', 'measured_publisher')
        publisher.viewer = module
        original_load = publisher.review_binding.load_identities
        publisher.review_binding.load_identities = lambda path: original_load(path, descriptor=None)
        timings = {}
        publication = publisher.publish(fixture_path, destination / 'public',
            review_identities=fixture_path / 'reviews.json', stage_timings=timings)
        files = {str(p.relative_to(destination / 'public')):dict(bytes=p.stat().st_size, sha256=digest(p))
                 for p in (destination / 'public').rglob('*') if p.is_file() and p.name != 'manifest.json'}
        publication.pop('published_at')
        save(destination / 'receipt.json', dict(arm=kind, operation=operation, seconds=time.perf_counter()-start,
            highwater_rss=highwater(), stages=timings, files=files, manifest=publication,
            scratch_output_bytes=sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())))


def guarded(command, output):
    started = time.perf_counter()
    log = output.with_suffix('.log')
    with log.open('wb') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        peak = 0
        while process.poll() is None:
            rss = subprocess.check_output(['ps','-o','rss=','-p',str(process.pid)], text=True).strip()
            peak = max(peak, int(rss or 0) * 1024)
            size = sum(p.stat().st_size for p in output.parent.rglob('*') if p.is_file())
            if peak > CEILING or size > OUTPUT_CEILING or time.perf_counter() - started > DEADLINE:
                process.kill(); process.wait()
                save(output, dict(status='stopped', peak_rss=peak, output_bytes=size))
                raise RuntimeError('Declared experiment ceiling exceeded')
            time.sleep(.05)
    save(output, dict(exit_code=process.returncode, seconds=time.perf_counter()-started, sampled_peak_rss=peak))
    if process.returncode:
        raise RuntimeError(f'Experiment child failed; see {log}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['run','fixture','arm'])
    parser.add_argument('output', type=Path)
    parser.add_argument('--retained', type=Path)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--kind', choices=['baseline','candidate'])
    parser.add_argument('--measure', choices=['measure','publish'])
    args = parser.parse_args()
    if args.operation == 'fixture':
        fixture(args.retained, args.output)
    elif args.operation == 'arm':
        arm(args.fixture, args.output, args.kind, args.measure)
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        save(args.output / 'proposal.json', dict(revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            viewer_sha256=digest(VIEWER), experiment_sha256=digest(__file__), python=sys.version, platform=platform.platform(),
            maximum_document_groups=32768, sampled_rss_ceiling=CEILING, deadline_per_child_seconds=DEADLINE,
            output_ceiling=OUTPUT_CEILING, native_memory_limit_claim=False))
        own = [sys.executable, str(Path(__file__).resolve())]
        fixture_path = args.fixture or args.output / 'fixture'
        if args.fixture is None:
            guarded(own + ['fixture', str(fixture_path), '--retained', str(args.retained)], args.output / 'fixture-watchdog.json')
        save(args.output / 'fixture-reference.json', dict(path=str(fixture_path),
            files={str(p.relative_to(fixture_path)): dict(bytes=p.stat().st_size, sha256=digest(p))
                   for p in fixture_path.rglob('*') if p.is_file()}))
        for kind in ['baseline', 'candidate']:
            for operation in ['measure','publish']:
                name = kind + '-' + operation
                guarded(own + ['arm',str(args.output / name),'--fixture',str(fixture_path),
                    '--kind',kind,'--measure',operation], args.output / (name + '-watchdog.json'))
        before = json.loads((args.output / 'baseline-publish/receipt.json').read_text())
        after = json.loads((args.output / 'candidate-publish/receipt.json').read_text())
        assert before['files'] == after['files']
        assert before['manifest'] == after['manifest']
        save(args.output / 'parity.json', dict(all_non_timestamp_manifest_values_equal=True,
            all_payload_bytes_equal=True, file_count=len(before['files']),
            timestamp_normalization='Only manifest published_at removed; every other file hash/byte size and manifest value compared.'))


if __name__ == '__main__':
    main()
