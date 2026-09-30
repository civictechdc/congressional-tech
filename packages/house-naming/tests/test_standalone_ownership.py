"""The installed filename tools must not depend on the acquisition application."""
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq


BLOCK_APPLICATION = '''
import sys
from importlib.abc import MetaPathFinder
class BlockApplication(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'congress_api' or fullname.startswith('congress_api.'):
            raise ImportError('Unexpected acquisition dependency: ' + fullname)
sys.meta_path.insert(0, BlockApplication())
'''


def test_typed_api_and_corpus_command_work_without_congress_api(tmp_path):
    inventory = tmp_path / 'names.parquet'
    pq.write_table(pa.Table.from_pylist([
        {'filename': 'BILLS-119HR42RepClyburnSomeTitleih.pdf', 'variants': []},
        {'filename': 'CPRT-119WPRT12345.pdf', 'variants': []},
    ]), inventory)
    reference = tmp_path / 'members.json'
    reference.write_text('{"119":["Clyburn"]}')
    script = BLOCK_APPLICATION + '''
from house_naming.filenames import parse_filename
from house_naming.filename_corpus import main, parser_source_paths
assert any(f.raw == 'WPRT' for m in parse_filename('CPRT-119WPRT12345.pdf').matches for f in m.fields)
assert all('house_naming' in str(p) for p in parser_source_paths())
raise SystemExit(main())
'''
    process = subprocess.run([sys.executable, '-c', script, str(inventory), str(tmp_path / 'out'),
                              '--member-surnames', str(reference)], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    import json
    coverage = json.loads((tmp_path / 'out/coverage.json').read_text())
    assert coverage['member_title_matches'] == 1
    assert coverage['mechanical_gate']


def test_base_engine_does_not_import_optional_typed_or_parquet_dependencies():
    script = BLOCK_APPLICATION + '''
class BlockOptional(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pydantic', 'pyarrow'}:
            raise ImportError('Unexpected optional dependency: ' + fullname)
sys.meta_path.insert(0, BlockOptional())
from house_naming import Engine
result = Engine().extract('CPRT-119WPRT12345.pdf')
assert result['valid']
assert any(m['rule'] == 'published-print' for m in result['observations'])
'''
    process = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
