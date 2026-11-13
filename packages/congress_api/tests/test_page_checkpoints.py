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


@pytest.mark.parametrize('damage', ['text', 'metadata'])
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
        del record['payload']['result']['metadata']['page_count']
        record['sha256'] = sha256(encoded(record['payload'])).hexdigest()
    page.write_text(json.dumps(record))
    with pytest.raises(CheckpointError, match='digest mismatch|missing page metadata'):
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
