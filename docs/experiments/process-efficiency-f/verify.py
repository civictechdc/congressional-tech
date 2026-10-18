"""Check ordered outputs, full required metadata, and previous-table identities."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'output/process-efficiency-f'
spec = importlib.util.spec_from_file_location('d_verify', ROOT / 'docs/experiments/process-efficiency-d/verify_order_and_metadata.py')
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
d.OUTPUT = OUT / 'sources'


def file_digest(path):
    import hashlib
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    fingerprints = {arm: d.fingerprints(arm) for arm in ('bytes', 'files', 'cached')}
    stable_reference, groups = {}, {}
    fixture = ROOT / 'output/process-efficiency-d/fixture-v2/indexes'
    for group in ('files-runs', 'cache-runs'):
        entries = []
        for path in sorted((OUT / group).glob('*/benchmark.json')):
            report = json.loads(path.read_text()); arm = path.parent.name.split('-', 1)[1]
            assert report['status'] == 'passed' and report['inputs_unchanged']
            result = report['result']; files = {}; ids = set()
            manifest = json.loads((path.parent / 'objects/indexes/catalog.json').read_text())
            assert manifest['generation'] == result['generation'] and manifest['catalog_id'] == result['catalog_id']
            for label, name in (('filenames', 'document-filenames.parquet'), ('documents', 'documents.parquet')):
                table_path = path.parent / 'objects' / result[label + '_key']
                digest = file_digest(table_path)
                assert digest == report['candidate_inventory'][name]['sha256'] == manifest['files'][label]['sha256']
                metadata = {k.decode(): v.decode() for k, v in pq.read_schema(table_path).metadata.items()}
                assert all(metadata[k] == v for k, v in fingerprints[arm].items())
                assert re.fullmatch('[0-9a-f]{32}', metadata['catalog_id'])
                ids.add(metadata['catalog_id'])
                actual = {'ordered_rows': d.ordered_rows(table_path),
                          'required_metadata': {k: v for k, v in metadata.items() if k not in d.VARIABLE}}
                stable_reference.setdefault(label, actual)
                assert stable_reference[label] == actual
                old_digest = file_digest(fixture / name)
                old_key = f'catalog-history/sha256/{old_digest}/{name}'
                assert result['previous_' + label + '_key'] == old_key
                assert file_digest(path.parent / 'objects' / old_key) == old_digest
                files[label] = {**actual, 'sha256': digest, 'history_sha256': old_digest,
                    'implementation_fingerprints_verified': True,
                    'variable_metadata': {k: metadata[k] for k in sorted(d.VARIABLE)}}
            assert ids == {result['catalog_id']}
            entries.append({'run': path.parent.name, 'arm': arm, 'files': files})
        assert len(entries) == 6
        groups[group] = entries
    inputs = json.loads((ROOT / 'docs/experiments/process-efficiency-f/evidence/component-inputs.json').read_text())
    for item in inputs['verified_files'].values():
        assert file_digest(Path(item['path'])) == item['sha256']
    assert file_digest(Path(inputs['root']) / 'indexes/catalog.json') == inputs['selector_sha256']
    for path in (OUT / 'component-runs-2').glob('[1-4]-*.json'):
        report = json.loads(path.read_text())
        assert report['status'] == 'passed' and report['manifest'] == inputs['manifest']
    return {'status': 'passed', 'runs': 12, 'files': 24, 'timing_rerun': False,
            'component_inputs_unchanged': True, 'comparisons': groups,
            'allowed_metadata_differences': sorted(d.VARIABLE), 'timestamp_fields': []}


if __name__ == '__main__':
    print(json.dumps(main(), indent=2))
