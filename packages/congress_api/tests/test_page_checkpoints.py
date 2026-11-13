"""Durable restart proof with native text and a scripted backend; no OCR service runs."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import pyarrow.parquet as pq

from body_text_fixtures import PAGE_ONE, PAGE_TWO, two_page_pdf, lake, committed
from congress_api.lake import body_text
from congress_api.parsers import body_text as derivation
from congress_api.retention.page_checkpoints import CheckpointError, adapter, encoded


RUNNER = '''
import json, os, sys
from pathlib import Path
from congress_api.parsers import body_text as bt
from congress_api.retention.page_checkpoints import adapter
from spicy_docs.extraction import NativeText
from spicy_docs.extraction.model import PageContent, Observation
class Scripted:
    def extract(self, page):
        with Path(sys.argv[3]).open('a') as calls:
            calls.write(str(page.number)+'\\n')
        if page.number == 2 and os.environ.get('FAIL_PAGE'):
            os._exit(73)
        content = NativeText().extract(page)
        # Scripted recognition provenance tests ordering without invoking a recognizer.
        marker = Observation('scripted', content.text, {'macos_build':'test-build'}, None, ())
        return PageContent(content.blocks, content.observations + (marker,))
rule = bt.PageRule(Scripted(), checkpoint_identity={'backend':'scripted-test', 'reader':'default-200'})
r = bt.pdf_text(Path(sys.argv[1]).read_bytes(), strategy=rule, page_deadline_seconds=0,
                checkpoint=adapter(sys.argv[2]))
print(json.dumps(dict(status=r.status, text=r.text, offsets=r.page_offsets, ocr=r.ocr_pages, build=r.macos_build)))
'''


def test_a_new_process_reuses_pages_after_late_worker_death(tmp_path):
    pdf, checkpoints, calls = tmp_path / 'source.pdf', tmp_path / 'pages', tmp_path / 'calls'
    pdf.write_bytes(two_page_pdf())
    command = [sys.executable, '-c', RUNNER, str(pdf), str(checkpoints), str(calls)]
    first = subprocess.run(command, env=dict(os.environ, FAIL_PAGE='1'), capture_output=True, text=True)
    assert first.returncode == 73
    assert len(list(checkpoints.glob('**/page-*.json'))) == 1
    second = subprocess.run(command, env={k: v for k, v in os.environ.items() if k != 'FAIL_PAGE'},
                            capture_output=True, text=True, check=True)
    result = json.loads(second.stdout)
    assert calls.read_text().splitlines() == ['1', '2', '2']
    assert result == dict(status='completed', text=PAGE_ONE+'\n'+PAGE_TWO,
                         offsets=[0, len(PAGE_ONE.encode())+1], ocr=[1, 2], build='test-build')
    uninterrupted = subprocess.run(command[:4] + [str(tmp_path / 'fresh'), str(tmp_path / 'fresh-calls')],
                                    capture_output=True, text=True, check=True)
    assert json.loads(uninterrupted.stdout) == result


@pytest.mark.parametrize('damage', ['text', 'metadata', 'source', 'policy'])
def test_corrupt_checkpoint_is_not_a_source_reading(tmp_path, damage):
    source = two_page_pdf()
    kwargs = dict(strategy=derivation.native_only(), page_deadline_seconds=0, checkpoint=adapter(tmp_path))
    first = derivation.pdf_text(source, **kwargs)
    assert first.status == 'completed'
    page = next(tmp_path.glob('**/page-*.json'))
    record = json.loads(page.read_text())
    if damage == 'text':
        record['payload']['result']['blocks'][0]['text'] = 'Plausible wrong amount $999'
    else:
        if damage == 'metadata':
            del record['payload']['result']['metadata']['page_count']
        elif damage == 'source':
            record['payload']['result']['metadata']['source_sha256'] = '0' * 64
        else:
            record['payload']['identity']['rule']['policy'] = 'different-policy'
        record['sha256'] = sha256(encoded(record['payload'])).hexdigest()
    page.write_text(json.dumps(record))
    with pytest.raises(CheckpointError, match='digest mismatch|missing page metadata|Conflicting page checkpoint'):
        derivation.pdf_text(source, **kwargs)
    assert list(tmp_path.glob('**/failure-*.json'))


def test_real_native_cover_and_valid_blank_replay_without_changed_cleanup(tmp_path):
    import pymupdf
    cover = Path(__file__).parent / 'fixtures/document-covers/house-hearing.pdf'
    doc = pymupdf.open()
    doc.new_page()
    for source in (cover.read_bytes(), doc.tobytes()):
        kwargs = dict(strategy=derivation.native_only(), page_deadline_seconds=0)
        direct = derivation.pdf_text(source, **kwargs)
        events = []
        first = derivation.pdf_text(source, **kwargs, checkpoint=adapter(tmp_path), evidence=events.append)
        replay_events = []
        replay = derivation.pdf_text(source, **kwargs, checkpoint=adapter(tmp_path), evidence=replay_events.append)
        assert direct == first == replay
        assert [e for e in events if e['event'] == 'document_cleanup'] == [
            e for e in replay_events if e['event'] == 'document_cleanup']
        assert any(e['event'] == 'page_reused' for e in replay_events)
    assert replay.status == 'completed' and replay.text == '' and replay.page_offsets == (0,)


def test_checkpoint_identity_change_does_not_reuse_old_pages(tmp_path):
    source = two_page_pdf()
    rule = derivation.native_only()
    kwargs = dict(page_deadline_seconds=0, checkpoint=adapter(tmp_path))
    assert derivation.pdf_text(source, strategy=rule, **kwargs).status == 'completed'
    changed = derivation.PageRule(rule.strategy, rule.reader, dict(rule.checkpoint_identity, policy='new'))
    assert derivation.pdf_text(source, strategy=changed, **kwargs).status == 'completed'
    assert len(list(tmp_path.glob('**/page-*.json'))) == 4


def test_actual_worker_reuses_checkpoints_and_leaves_corruption_pending(tmp_path):
    args, _ = lake(tmp_path, {'pdf': (two_page_pdf(), 'pdf')})
    checkpoint_root = tmp_path / 'durable-pages'
    report = body_text.run(**args, work=tmp_path / 'run', execute=True, page_checkpoints=checkpoint_root)
    assert report['status'] == 'completed'
    assert committed(args, tmp_path / 'readback', 'body_text', 'text')[0]['text'] == PAGE_ONE+'\n'+PAGE_TWO
    page = next(checkpoint_root.glob('**/page-*.json'))
    page.write_text('{broken')
    # A new empty destination forces another worker attempt over the same source and cache.
    other = tmp_path / 'other'
    other.mkdir()
    captures = pq.read_table(args['captures']).to_pylist()
    body = captures[0]['sha256'].hex()
    source = (args['local_root'] / ('bodies/sha256/'+body[:2]+'/'+body)).read_bytes()
    fresh_args, _ = lake(other, {'pdf': (source, 'pdf')})
    pending = body_text.run(**fresh_args, work=other / 'run', execute=True, page_checkpoints=checkpoint_root)
    assert pending['pending_read_reasons'] == {'page_checkpoint': 1}
    assert committed(fresh_args, other / 'outcomes', 'readings', 'status') == []


def test_exact_page_replacement_reuses_other_pages_and_retains_previous_policy(tmp_path):
    from spicy_docs.extraction import NativeText
    from spicy_docs.extraction.model import PageContent, Observation, TextBlock

    calls = []

    class Replacement:
        def extract(self, page):
            calls.append(page.number)
            block = TextBlock('Reviewed replacement control', observation='scripted')
            return PageContent((block,), (Observation('scripted', block.text, {'backend': 'scripted'}, None, (block,)),))

    source = two_page_pdf()
    baseline = derivation.PageRule(NativeText(), checkpoint_identity={'policy': 'native-control'})
    kwargs = dict(page_deadline_seconds=0, checkpoint=adapter(tmp_path))
    original = derivation.pdf_text(source, strategy=baseline, **kwargs)
    retained = {p: p.read_bytes() for p in tmp_path.glob('**/page-*.json')}
    replacement = derivation.PageRule(Replacement(), checkpoint_identity={'policy': 'repair-one'})
    rule = derivation.PageRule(baseline.strategy, checkpoint_identity=baseline.checkpoint_identity,
        page_overrides={sha256(source).hexdigest(): {2: replacement}})
    events = []
    repaired = derivation.pdf_text(source, strategy=rule, evidence=events.append, **kwargs)
    assert calls == [2] and repaired.text == PAGE_ONE + '\nReviewed replacement control'
    assert repaired.ocr_pages == (2,) and repaired.page_offsets == original.page_offsets
    assert [e['page'] for e in events if e['event'] == 'page_reused'] == [1]
    assert all(p.read_bytes() == value for p, value in retained.items())
    assert derivation.pdf_text(source, strategy=rule, **kwargs) == repaired
    assert calls == [2]

    # A changed page policy invalidates only that page; source identity prevents a spill to another PDF.
    other = derivation.PageRule(Replacement(), checkpoint_identity={'policy': 'repair-two'})
    changed = derivation.PageRule(baseline.strategy, checkpoint_identity=baseline.checkpoint_identity,
        page_overrides={sha256(source).hexdigest(): {2: other}})
    assert derivation.pdf_text(source, strategy=changed, **kwargs) == repaired
    assert calls == [2, 2]
    assert derivation.pdf_text(source + b'\n', strategy=rule, **kwargs) == original
    assert calls == [2, 2]
    assert derivation.pdf_text(source, strategy=rule, page_deadline_seconds=0) == repaired


def test_page_replacement_identity_and_page_bounds_are_checked_before_reuse(tmp_path):
    source = two_page_pdf()
    baseline = derivation.native_only()
    sha = sha256(source).hexdigest()
    for source_key, page in [('prefix', 1), (sha, 0), (sha, True)]:
        with pytest.raises(ValueError, match='SHA-256|positive integers'):
            derivation.PageRule(baseline.strategy, page_overrides={source_key: {page: baseline}})
    kwargs = dict(page_deadline_seconds=0, checkpoint=adapter(tmp_path))
    assert derivation.pdf_text(source, strategy=baseline, **kwargs).status == 'completed'
    bad = derivation.PageRule(baseline.strategy, checkpoint_identity=baseline.checkpoint_identity,
        page_overrides={sha: {3: baseline}})
    with pytest.raises(CheckpointError, match='outside the source page count'):
        derivation.pdf_text(source, strategy=bad, **kwargs)
    assert derivation.pdf_text(source, strategy=bad, page_deadline_seconds=0).status == 'error'
    unidentified = derivation.PageRule(baseline.strategy, checkpoint_identity=baseline.checkpoint_identity,
        page_overrides={sha: {2: derivation.PageRule(baseline.strategy)}})
    with pytest.raises(ValueError, match='explicit reproducible rule identity'):
        derivation.pdf_text(source, strategy=unidentified, **kwargs)


def test_missing_extracted_page_remains_pending_and_keeps_completed_page(tmp_path, monkeypatch):
    from spicy_docs.extraction import DocumentExtractor

    extract = DocumentExtractor.extract

    def truncated(self, *args, **kwargs):
        stream = extract(self, *args, **kwargs)
        try:
            yield next(stream)
        finally:
            stream.close()

    monkeypatch.setattr(DocumentExtractor, 'extract', truncated)
    with pytest.raises(CheckpointError, match='Incomplete or conflicting extracted page sequence'):
        derivation.pdf_text(two_page_pdf(), strategy=derivation.native_only(),
                            page_deadline_seconds=0, checkpoint=adapter(tmp_path))
    assert len(list(tmp_path.glob('**/page-*.json'))) == 1
    assert list(tmp_path.glob('**/failure-*.json'))


WORKER_RUNNER = '''
import json, os
from hashlib import sha256
from pathlib import Path
from congress_api.parsers import body_text as bt
from congress_api.retention.page_checkpoints import adapter
from spicy_docs.extraction import NativeText
from spicy_docs.extraction.model import PageContent, Observation, TextBlock
def parse(payload):
    request = json.loads(payload)
    source = Path(request['source']).read_bytes()
    class Baseline:
        def extract(self, page):
            with Path(request['calls']).open('a') as calls: calls.write('baseline:'+str(page.number)+'\\n')
            if page.number == 2: os._exit(73)
            return NativeText().extract(page)
    class Repair:
        def extract(self, page):
            with Path(request['calls']).open('a') as calls: calls.write('repair:'+str(page.number)+'\\n')
            block = TextBlock('Scripted page-two control', observation='scripted')
            return PageContent((block,), (Observation('scripted', block.text, {'backend':'scripted'}, None, (block,)),))
    replacements = {sha256(source).hexdigest(): {2: bt.PageRule(Repair(), checkpoint_identity={'policy':'repair'})}}
    rule = bt.PageRule(Baseline(), checkpoint_identity={'policy':'baseline'},
                       page_overrides=replacements if request['repair'] else {})
    events = []
    reading = bt.pdf_text(source, strategy=rule, page_deadline_seconds=0,
                          checkpoint=adapter(request['checkpoints']), evidence=events.append)
    result = dict(status=reading.status, text=reading.text, offsets=reading.page_offsets,
                  ocr_pages=reading.ocr_pages, events=events)
    Path(request['output']).write_text(json.dumps(result))
    return result
'''


def test_supervised_worker_restarts_only_the_failed_page_with_a_new_policy(tmp_path):
    from congress_api.retention.parser_worker import ParserWorker

    parser, source = tmp_path / 'parser.py', tmp_path / 'source.pdf'
    parser.write_text(WORKER_RUNNER)
    source.write_bytes(two_page_pdf())
    request = dict(source=str(source), calls=str(tmp_path / 'calls'), checkpoints=str(tmp_path / 'pages'),
                   output=str(tmp_path / 'output.json'), repair=False)
    limits = dict(timeout_seconds=10, memory_bytes=512 << 20, max_input_bytes=4096, max_output_bytes=65536)
    with ParserWorker('fixture', 'v1', str(parser)+':parse', **limits) as worker:
        failed = worker.parse('body', json.dumps(request).encode())
    assert failed == dict(status='unreadable', reason='parser_crash', attempts=2)
    assert not Path(request['output']).exists()
    request['repair'] = True
    with ParserWorker('fixture', 'v1', str(parser)+':parse', **limits) as worker:
        result = worker.parse('body', json.dumps(request).encode())
    (tmp_path / 'worker-outcomes.json').write_text(json.dumps({'failed': failed, 'repaired': result}, indent=2))
    assert result['status'] == 'completed'
    assert result['value']['text'] == PAGE_ONE + '\nScripted page-two control'
    assert result['value']['ocr_pages'] == [2]
    assert Path(request['calls']).read_text().splitlines() == ['baseline:1', 'baseline:2', 'baseline:2', 'repair:2']
    assert len(list(Path(request['checkpoints']).glob('**/page-*.json'))) == 2
    fresh_request = dict(request, checkpoints=str(tmp_path / 'fresh-pages'), calls=str(tmp_path / 'fresh-calls'),
                         output=str(tmp_path / 'fresh-output.json'))
    with ParserWorker('fixture', 'v1', str(parser)+':parse', **limits) as worker:
        fresh = worker.parse('body', json.dumps(fresh_request).encode())
    for key in ('status', 'text', 'offsets', 'ocr_pages'):
        assert fresh['value'][key] == result['value'][key]
    cleanup = lambda value: [e for e in value['events'] if e['event'] in ('page_normalized', 'document_cleanup')]
    assert cleanup(fresh['value']) == cleanup(result['value'])
