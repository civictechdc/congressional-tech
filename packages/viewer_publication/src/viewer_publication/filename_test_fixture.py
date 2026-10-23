"""Small catalog covering group retention, API scope and source provenance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='filename-test-fixture.py',
        description='Small catalog covering group retention, API scope and source provenance.',
    )
    parser.add_argument(
        'root',
        type=Path,
        help='Root directory where the test fixture catalog structure will be created.',
    )
    return parser


def main(argv=None):
    if argv is None:
        tokens = sys.argv[1:]
    elif isinstance(argv, (str, Path)):
        tokens = [str(argv)]
    else:
        tokens = [str(a) for a in argv]

    parser = build_parser()
    args = parser.parse_args(tokens)
    root = args.root

    for candidate in (ROOT / 'packages/congress_api/tests', ROOT / 'tests'):
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    import historical_viewer_publication as publisher
    # Small parts exercise multi-part values in the real Python-to-browser path.
    publisher.observations.BLOCK_BYTES = 128
    generation = 'a' * 32
    catalog_id = 'b' * 32
    folder = root / 'catalog-generations' / generation
    folder.mkdir(parents=True, exist_ok=True)
    (root / 'indexes').mkdir(exist_ok=True)
    columns = list(publisher.viewer.LIST_COLUMNS) + ['source_occurrences', 'content_document_kind', 'state_checked_at']
    scalar = {'filename', 'source_url', 'body_key', 'source_id', 'document_id'}
    observation = pa.list_(pa.struct([(key, pa.list_(pa.string())) for key in ['source_page_url', 'source_page_title', 'source_link_label', 'source_occurrence_scope']]))
    schema = pa.schema([(key, observation if key == 'source_occurrences' else pa.string() if key in scalar else pa.list_(pa.string())) for key in columns], metadata={b'catalog_id': catalog_id.encode(), b'house_naming_version': b'fixture'})
    rows = []
    for i, (filename, url, body, group, role, kind) in enumerate([
        ('unfetched alias.pdf', 'https://committee.test/alias', None, 'A', 'document', None),
        ('Saved statement.pdf', 'https://committee.test/final', 'bodies/sha256/ab/' + ('ab' * 32) + '.gz', 'A', 'document', ['witness-statement']),
        ('Unfetched.pdf', 'https://committee.test/unfetched', None, 'B', 'document', None),
        ('1', 'https://api.congress.gov/v3/hearing/116/senate/1?format=json', None, 'C', 'document', None),
        ('Recovered', None, None, 'D', 'source-record', None),
        ('failed.pdf', 'https://committee.test/failure', 'body-failed', 'E', 'error-response', None),
        ('-oNSVIeynzI', 'https://youtu.be/-oNSVIeynzI', 'video-webpage', 'F', 'document', ['opening-statement']),
    ]):
        row = dict.fromkeys(columns)
        row.update(filename=filename, source_url=url, body_key=body, source_id=hashlib.sha256(str(i).encode()).hexdigest(),
                   document_id=group, record_role=[role], document_kind=kind, document_family=['statement'] if kind else None,
                   format=['pdf'] if filename.endswith('.pdf') else None, congress=['117'] if i == 2 else None)
        if os.environ.get('FILENAME_FIXTURE_SPARSE') and i in (1, 6):
            row['filename'] += ' sparse-marker'
        if os.environ.get('FILENAME_FIXTURE_SHARED_PREFIX'):
            row['source_id'] = 'aa' + row['source_id'][2:]
        if os.environ.get('FILENAME_FIXTURE_WIDTH'):
            row['content_document_kind'] = ['Wide 🏛️ ' * int(os.environ['FILENAME_FIXTURE_WIDTH'])]
        if i == 1:
            row.update(http_status=['200'], response_usable=['true'], response_body_complete=['true', 'false'], state_checked_at=['2026-10-14T09:00:00-04:00'])
        if i == 2:
            row['recovered_source_url'] = ['https://archive.test/recovered-unfetched.pdf']
            row['source_occurrences'] = [dict(source_page_url=['https://committee.test/hearing'], source_page_title=['Hearing page'], source_link_label=['Witness name'], source_occurrence_scope=['anchor'])]
            row['source_occurrences'].append(dict(row['source_occurrences'][0]))
            row['source_occurrences'].append(dict(source_page_url=None, source_page_title=[], source_link_label=['José 🏛️'], source_occurrence_scope=None))
        if i == 4:
            row['recovered_filename'] = ['Recovered witness.pdf']
        rows.append(row)
    if os.environ.get('FILENAME_FIXTURE_ROWS'):
        original = rows
        rows = [{**original[i % len(original)],
                 'source_id': hashlib.sha256(str(i).encode()).hexdigest(),
                 'document_id': str(i)} for i in range(int(os.environ['FILENAME_FIXTURE_ROWS']))]
    if os.environ.get('FILENAME_FIXTURE_NATIVE_IDENTITIES'):
        from congress_api.retention.document_index import source_identity
        for index, row in enumerate(rows):
            if os.environ.get('FILENAME_FIXTURE_ROWS'):
                row['filename'] = f"{row['filename']} {index:05d}"
            row['source_id'] = source_identity(row)
    files = {}
    for name, subset in [('filenames', rows), ('documents', rows if os.environ.get('FILENAME_FIXTURE_ROWS') else [rows[i] for i in [1, 2, 3, 4, 5, 6]])]:
        path = folder / ('document-filenames.parquet' if name == 'filenames' else 'documents.parquet')
        pq.write_table(pa.Table.from_pylist(subset, schema=schema), path, row_group_size=256 if os.environ.get('FILENAME_FIXTURE_ROWS') else 2, compression='zstd')
        files[name] = dict(key=str(path.relative_to(root)), bytes=path.stat().st_size, rows=len(subset), sha256=publisher.digest(path))
    (root / 'indexes/catalog.json').write_text(json.dumps(dict(version=1, generation=generation, catalog_id=catalog_id, files=files)))
    # Fixture catalogs are not the reviewed catalog; tests supply their own review data.
    publisher.publish(root, root / 'public', review_identities=None)
    queries = [{'q': 'alias', 'document_kind': 'witness-statement'}, {'q': 'JOSÉ 🏛️', 'field': 'source_occurrences'}, {'q': '\"source_page_url\":', 'field': 'source_occurrences'}, {}, {'scope': 'all'}, {'retained': 'no', 'scope': 'all'}, {'q': 'alias', 'retained': 'no'}, {'q': 'alias'},
               {'q': 'ALIAS', 'document_kind': '__null__'}, {'document_kind': '__null__'}, {'scope': 'capture-records', 'retained': 'no'},
               {'q': 'Witness name', 'field': 'source_occurrences'}, {'scope': 'all', 'q': 'Recovered witness'}, {'congress': '117'}, {'q': 'unfetched', 'format': 'pdf'}, {'scope': 'all', 'page': '99', 'limit': '2'}]
    catalog = publisher.viewer.Catalog(folder / 'document-filenames.parquet')
    expected = [dict(query=query, result=catalog.search(query)) for query in queries]
    (root / 'expected.json').write_text(json.dumps(expected))
    (root / 'source-records.json').write_text(json.dumps(rows))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
elif __name__ == 'native_legacy_fixture':
    main()
