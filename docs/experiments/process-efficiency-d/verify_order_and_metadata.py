"""Supplement existing D measurements; inspect retained bytes without retiming."""
import ast
from hashlib import sha256
import json
from pathlib import Path
import re

import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / 'output/process-efficiency-d'
VARIABLE = {'catalog_id', 'source_fingerprint', 'document_grouping_fingerprint'}


def fingerprints(arm):
    package = OUTPUT / arm / 'packages/congress_api/src/congress_api'
    paths = [package / 'retention' / (name + '.py') for name in (
        'catalog_cache', 'document_index', 'document_recovery', 'raw_catalog',
        'catalog_staging', 'catalog_availability', 'body_files',
        'capture_inspection', 'image_tools', 'pdf_tools')]
    paths += [path for directory in ('parsers', 'models')
              for path in (package / directory).rglob('*.py') if path.name != 'document_cover.py']
    source = sha256()
    for path in sorted(paths):
        source.update(path.name.encode())
        source.update(path.read_bytes())
    grouping = sha256()
    for name in ('document_index', 'document_evidence', 'catalog_staging'):
        grouping.update((package / 'retention' / (name + '.py')).read_bytes())
    text = (package / 'retention/document_index.py').read_text()
    function = next(node for node in ast.parse(text).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'fill_document_kind')
    grouping.update(''.join(text.splitlines(keepends=True)[function.lineno - 1:function.end_lineno]).encode())
    return {'source_fingerprint': source.hexdigest(), 'document_grouping_fingerprint': grouping.hexdigest()}


def ordered_rows(path):
    digest, count = sha256(), 0
    for batch in pq.ParquetFile(path).iter_batches(batch_size=64):
        for row in batch.to_pylist():
            text = json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
            digest.update(sha256(text.encode()).digest())
            count += 1
    return {'rows': count, 'ordered_sha256': digest.hexdigest()}


def main():
    expected = {arm: fingerprints(arm) for arm in ('baseline', 'cached', 'one-pass')}
    comparisons = {}
    for group, candidate in [('cached-runs', 'cached'), ('one-pass-runs', 'one-pass')]:
        baseline, runs = {}, []
        for report_path in sorted((OUTPUT / group).glob('*/benchmark.json')):
            report = json.loads(report_path.read_text())
            arm = 'baseline' if report_path.parent.name.endswith('-baseline') else candidate
            entry = {'run': report_path.parent.name, 'arm': arm, 'files': {}}
            ids = set()
            for label, key, name in [('filenames', 'filenames_key', 'document-filenames.parquet'),
                                     ('documents', 'documents_key', 'documents.parquet')]:
                path = report_path.parent / 'objects' / report['result'][key]
                data_hash = sha256(path.read_bytes()).hexdigest()
                assert data_hash == report['candidate_inventory'][name]['sha256'], 'Retained output changed'
                metadata = {key.decode(): value.decode() for key, value in pq.read_schema(path).metadata.items()}
                assert all(metadata[key] == value for key, value in expected[arm].items()), 'Wrong implementation fingerprint'
                assert re.fullmatch('[0-9a-f]{32}', metadata['catalog_id']), 'Invalid generated catalog ID'
                ids.add(metadata['catalog_id'])
                stable = {key: value for key, value in metadata.items() if key not in VARIABLE}
                actual = {'ordered_rows': ordered_rows(path), 'required_metadata': stable}
                baseline.setdefault(label, actual)
                assert actual == baseline[label], 'Required metadata or physical row order changed'
                entry['files'][label] = {**actual, 'sha256': data_hash,
                    'recorded_variable_metadata': {key: metadata[key] for key in sorted(VARIABLE)},
                    'implementation_fingerprints_verified': True}
            assert ids == {report['result']['catalog_id']}, 'Pair/catalog selection ID differs'
            runs.append(entry)
        assert len(runs) == 6
        comparisons[group] = runs
    return {'status': 'passed', 'timing_rerun': False, 'runs': 12, 'files': 24,
            'allowed_metadata_differences': {
                'catalog_id': 'Fresh UUID per complete generated pair; verified against both tables and selection result',
                'source_fingerprint': 'Recomputed from the exact archived implementation used by each arm',
                'document_grouping_fingerprint': 'Recomputed from the exact archived implementation used by each arm'},
            'timestamp_metadata_fields': [], 'comparisons': comparisons}


if __name__ == '__main__':
    print(json.dumps(main(), indent=2) + '\n')
