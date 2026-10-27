"""B4: source retention does not depend on downstream document review decisions."""
import ast
import hashlib
from pathlib import Path

from congress_api.retention.body_store import BodyStore, LocalAdapter


def test_capture_store_retains_source_without_review_exclusion_policy(tmp_path):
    body = tmp_path / 'source'
    body.write_bytes(b'<html>an unclassified source remains evidence</html>')
    digest = hashlib.sha256(body.read_bytes()).hexdigest()
    key = f'bodies/sha256/{digest[:2]}/{digest}'
    result = BodyStore(LocalAdapter(tmp_path / 'raw')).put(key, body, 'text/html')
    assert result.outcome == 'stored'
    assert (tmp_path / 'raw' / key).is_file()


def test_surviving_raw_components_do_not_import_the_old_exclusion_gate():
    root = Path(__file__).parents[1] / 'src/congress_api'
    names = ['retention/body_store.py', 'retention/receipt_writer.py',
             'retention/archive_expander.py', 'acquisition/fetcher.py', 'transport/raw_adapters.py']
    for name in names:
        tree = ast.parse((root / name).read_text())
        imported = {alias.name for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
        assert not imported.intersection({'enforce_body_ingest_gate', 'load_excluded_body_hashes',
                                          'ExcludedBodyError'}), name
