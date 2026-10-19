"""Moved research commands admit their retained notes before any population work."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


PACKAGE = Path(__file__).resolve().parents[1]


class SnapshotReached(Exception):
    """Stop after the actual command reaches its note hash."""


@pytest.mark.parametrize('source,note,hash_function', [
    ('tools/compare_filename_engines.py', 'filename-engine-comparison.md', 'file_hashes'),
    ('tools/compare_filename_metadata.py', 'filename-metadata-comparison.md', 'digest'),
    ('tools/compare_house_naming_context_corpus.py', 'house-naming-context-corpus.md', 'sha'),
    ('tools/recompare_filename_metadata.py', 'filename-metadata-recomparison.md', 'digest'),
    ('tests/compare_filename_extraction.py', 'house-naming-extraction.md', 'sha'),
])
def test_default_command_hashes_owned_note_without_population_work(
        tmp_path, monkeypatch, source, note, hash_function):
    monkeypatch.syspath_prepend(str(PACKAGE / 'tools'))
    path = PACKAGE / source
    spec = importlib.util.spec_from_file_location('note_path_command', path)
    command = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(command)
    expected_note = PACKAGE / 'notes' / note
    expected_hash = hashlib.sha256(expected_note.read_bytes()).hexdigest()

    run, previous = tmp_path / 'run', tmp_path / 'previous'
    run.mkdir(); previous.mkdir()
    (run / 'summary.json').write_text(json.dumps({'hashes': {}, 'baseline': str(previous)}))
    (run / 'paired-outputs.jsonl.gz').touch()
    (previous / 'comparison.parquet').touch()
    inventory, reference = tmp_path / 'inventory.parquet', tmp_path / 'reference.json'
    inventory.touch(); reference.write_text('[]')
    output = tmp_path / 'output'
    name = path.name
    arguments = {
        'compare_filename_engines.py': [str(output), '--inventory', str(inventory)],
        'compare_filename_metadata.py': [str(run), str(output)],
        'compare_house_naming_context_corpus.py': [str(run), str(reference), str(output)],
        'recompare_filename_metadata.py': [str(run), str(previous), str(output)],
        'compare_filename_extraction.py': [str(run), str(output)],
    }
    monkeypatch.setattr('sys.argv', [str(path), *arguments[name]])
    if hasattr(command, 'parser_source_paths'):
        monkeypatch.setattr(command, 'parser_source_paths', lambda: [])
    if hasattr(command, 'Engine'):
        monkeypatch.setattr(command, 'Engine', lambda: pytest.fail('population classification started'))
    if name == 'recompare_filename_metadata.py':
        monkeypatch.setattr(command.pq, 'read_table', lambda _: SimpleNamespace(to_pylist=lambda: []))

    def checked_hash(value):
        value = Path(value)
        digest = hashlib.sha256(value.read_bytes()).hexdigest()
        if value.name == note:
            assert value == expected_note
            assert digest == expected_hash
            raise SnapshotReached
        return digest

    if hash_function == 'file_hashes':
        monkeypatch.setattr(command, hash_function,
                            lambda values: {str(value): checked_hash(value) for value in values})
    else:
        monkeypatch.setattr(command, hash_function, checked_hash)
    with pytest.raises(SnapshotReached):
        command.main()


def test_rejection_inventory_checks_note_before_classification(tmp_path, monkeypatch):
    path = PACKAGE / 'tools/inventory_house_naming_rejections.py'
    spec = importlib.util.spec_from_file_location('rejection_note_command', path)
    command = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(command)
    note = PACKAGE / 'notes/filename-engine-comparison.md'
    expected_hash = hashlib.sha256(note.read_bytes()).hexdigest()
    monkeypatch.setattr('sys.argv', [str(path), '--run', str(tmp_path / 'unused'),
                                     '--output', str(tmp_path / 'output')])
    monkeypatch.setattr(command, 'Engine', lambda: pytest.fail('population classification started'))
    original = Path.read_bytes

    def read_note(value):
        assert value == note
        assert hashlib.sha256(original(value)).hexdigest() == expected_hash
        raise SnapshotReached

    monkeypatch.setattr(Path, 'read_bytes', read_note)
    with pytest.raises(SnapshotReached):
        command.main()
