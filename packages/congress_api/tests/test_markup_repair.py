"""Retained raw bytes become inspectable partial artifacts, never selected readings."""
from hashlib import sha256
from importlib import import_module
import json
from pathlib import Path
import subprocess
import sys

import pytest

from congress_api.retention.markup_repair import inspect_xml_repair

ORIGINAL = Path(__file__).parent / 'fixtures/markup-repair/truncated-resolution.xml'
ORIGINAL_SHA = '4cad751b9ec4c7584d60e1d5059b70d29672853056fd789766b9decad7092498'


def test_actual_cut_resolution_retains_original_candidate_events_and_partial_text(tmp_path):
    original = ORIGINAL.read_bytes()
    out = tmp_path / 'review'
    result = inspect_xml_repair(ORIGINAL, expected_sha256=ORIGINAL_SHA, output_dir=out,
                               source_gap_note='Source ends mid-idref attribute after TITLE II in the table of contents.')
    assert (out / 'original.raw').read_bytes() == original
    assert result['status'] == 'partial' and result['content_completeness'] == 'unestablished'
    assert result['qualification'] == 'not_qualified_for_selection' and not result['selected_for_publication']
    assert result['byte_positions_address'] == 'candidate'
    assert result['source_gap_note'].startswith('Source ends mid-idref')
    for item in result['files'].values():
        body = (out / item['path']).read_bytes()
        assert sha256(body).hexdigest() == item['sha256'] and len(body) == item['bytes']
    repair = json.loads((out / 'repair.json').read_text())
    assert repair['source_sha256'] == ORIGINAL_SHA != repair['candidate_sha256']
    assert repair['diagnostics'] and repair['lxml_version']
    text = (out / 'candidate.txt').read_text()
    assert 'S. CON. RES. 5' in text and text.endswith('TITLE II—Reconciliation')
    events = [json.loads(line) for line in (out / 'candidate.events.jsonl').read_text().splitlines()]
    assert any(event['text'] == 'S. CON. RES. 5' for event in events)
    assert json.loads((out / 'output.json').read_text()) == result


def test_actual_cli_reports_partial_without_claiming_a_completed_document(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'congress_api.retention.markup_repair', '--input', str(ORIGINAL),
                             '--sha256', ORIGINAL_SHA, '--output-dir', str(tmp_path / 'cli')],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'partial'
    assert json.loads(result.stdout)['qualification'] == 'not_qualified_for_selection'


def test_changed_original_or_byte_bound_creates_no_candidate_directory(tmp_path):
    for kwargs, message in [({'expected_sha256': '0' * 64}, 'expected_sha256'),
                             ({'expected_sha256': ORIGINAL_SHA, 'max_bytes': 10}, 'max_bytes')]:
        out = tmp_path / 'not-created'
        with pytest.raises(ValueError, match=message):
            inspect_xml_repair(ORIGINAL, output_dir=out, **kwargs)
        assert not out.exists()


def test_existing_review_is_never_overwritten(tmp_path):
    out = tmp_path / 'review'
    out.mkdir()
    (out / 'keep.txt').write_text('prior refusal evidence')
    with pytest.raises(FileExistsError):
        inspect_xml_repair(ORIGINAL, expected_sha256=ORIGINAL_SHA, output_dir=out)
    assert (out / 'keep.txt').read_text() == 'prior refusal evidence'
    assert list(out.iterdir()) == [out / 'keep.txt']


def test_unsafe_xml_retains_refusal_evidence_without_a_candidate_text(tmp_path):
    original = tmp_path / 'unsafe.xml'
    body = b'<!DOCTYPE r [<!ENTITY x "injected">]><r>&x;'
    original.write_bytes(body)
    out = tmp_path / 'review'
    result = inspect_xml_repair(original, expected_sha256=sha256(body).hexdigest(), output_dir=out)
    assert result['status'] == 'refused'
    assert (out / 'original.raw').read_bytes() == body
    assert (out / 'repair.json').is_file() and (out / 'output.json').is_file()
    assert not (out / 'candidate.txt').exists()


def test_valid_original_is_observed_without_automatic_selection(tmp_path):
    source = tmp_path / 'valid.xml'
    body = b'<r>source</r>'
    source.write_bytes(body)
    out = tmp_path / 'review'
    result = inspect_xml_repair(source, expected_sha256=sha256(body).hexdigest(), output_dir=out)
    assert result['status'] == 'unchanged' and not result['selected_for_publication']
    assert (out / 'candidate.xml').read_bytes() == body
    assert (out / 'candidate.txt').read_text() == 'source'


def test_actual_cli_retains_refusal_when_unchanged_candidate_exceeds_its_bound(tmp_path):
    source = tmp_path / 'valid.xml'
    original = b'<r>A short valid input</r>'
    source.write_bytes(original)
    out = tmp_path / 'bounded'
    result = subprocess.run([sys.executable, '-m', 'congress_api.retention.markup_repair', '--input', str(source),
                             '--sha256', sha256(original).hexdigest(), '--output-dir', str(out),
                             '--max-candidate-bytes', '8'], capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
    assert json.loads(result.stdout)['status'] == 'refused'
    output = json.loads((out / 'output.json').read_text())
    assert output['status'] == 'refused' and output['reason'] == 'candidate_exceeds_byte_bound'
    assert output['limits']['max_candidate_bytes'] == 8
    assert (out / 'original.raw').read_bytes() == original
    assert (out / 'repair.json').is_file()
    assert not (out / 'candidate.xml').exists() and not (out / 'candidate.txt').exists()
    assert not output['selected_for_publication']


def test_candidate_consumer_refusal_retains_its_final_record(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise ValueError('planted candidate normalization refusal')

    monkeypatch.setattr(import_module('spicy_docs.extraction.body_text'), 'rendition_text', refuse)
    source = tmp_path / 'valid.xml'
    source.write_bytes(b'<r>source</r>')
    out = tmp_path / 'review'
    result = inspect_xml_repair(source, expected_sha256=sha256(source.read_bytes()).hexdigest(), output_dir=out)
    assert result['status'] == 'refused' and result['reason'] == 'candidate_consumer_refused'
    assert result['consumer_error']['message'] == 'planted candidate normalization refusal'
    assert json.loads((out / 'output.json').read_text()) == result
    assert (out / 'original.raw').is_file() and (out / 'candidate.xml').is_file()
    assert not (out / 'candidate.txt').exists()


def test_empty_retained_xml_keeps_an_explicit_refusal_packet(tmp_path):
    source = tmp_path / 'empty.xml'
    source.write_bytes(b'')
    out = tmp_path / 'review'
    result = inspect_xml_repair(source, expected_sha256=sha256(b'').hexdigest(), output_dir=out)
    assert result['status'] == 'refused' and result['reason'] == 'recovery_input_refused'
    assert (out / 'original.raw').read_bytes() == b''
    assert json.loads((out / 'output.json').read_text()) == result
    assert not (out / 'candidate.xml').exists()


def test_candidate_bound_does_not_reduce_the_separate_input_bound(tmp_path):
    source = tmp_path / 'malformed.xml'
    body = b'<r>source</r>' + b' ' * 1024 + b'outside-root'
    source.write_bytes(body)
    out = tmp_path / 'review'
    result = inspect_xml_repair(source, expected_sha256=sha256(body).hexdigest(), output_dir=out,
                               max_bytes=2048, max_candidate_bytes=64)
    assert result['status'] == 'partial'
    assert (out / 'original.raw').read_bytes() == body
    assert (out / 'candidate.xml').stat().st_size <= 64
