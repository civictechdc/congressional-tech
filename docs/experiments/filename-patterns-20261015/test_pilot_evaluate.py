"""Reference sealing, denominator conservation and native reader comparisons."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import pilot_blind_review as blind
import pilot_evaluate as evaluate
import pilot_review as review
from pilot_reconcile import file_digest
from test_pilot_workflow import packet_fixture, export_fixture, write_json, catalog, publication, document
import pilot_reconcile


def ready(tmp_path, monkeypatch, *, decided=True):
    row, pdf, text, freeze = packet_fixture(tmp_path, monkeypatch)
    runtime = dict(reader_versions={'pypdf': 'test'}, reader_fingerprint='test-reader')
    monkeypatch.setattr(evaluate, 'environment', lambda: runtime.copy())
    candidate = json.loads(freeze.read_text())
    candidate.update(reader_versions=runtime['reader_versions'], baseline_commit='38f7557',
                     development_summary=dict(baseline_parser_sha256=evaluate.sha256(b'baseline').hexdigest()))
    write_json(freeze, candidate)
    packet = tmp_path / 'packet'
    blind.build('development', packet, freeze)
    export = tmp_path / 'export.json'
    write_json(export, export_fixture(packet))
    if decided:
        blind.import_decisions(packet, export, freeze_path=freeze)
    return packet, freeze, export, pdf


def test_missing_available_reference_blocks_seal(tmp_path, monkeypatch):
    packet, freeze, _, _ = ready(tmp_path, monkeypatch, decided=False)
    with pytest.raises(ValueError, match='Every available record'):
        evaluate.seal(packet, freeze_path=freeze)
    assert not (packet / 'label-freeze.json').exists()


@pytest.mark.parametrize('changed', ['journal', 'environment', 'pdf', 'freeze', 'interface'])
def test_changed_evidence_blocks_evaluation_before_reader(tmp_path, monkeypatch, changed):
    packet, freeze, _, pdf = ready(tmp_path, monkeypatch)
    evaluate.seal(packet, freeze_path=freeze)
    if changed == 'journal':
        path = packet / 'reference-decisions.jsonl'
        value = json.loads(path.read_text()); value['reference_kind'] = 'hearing'
        path.write_text(json.dumps(value) + '\n')
    elif changed == 'environment':
        monkeypatch.setattr(evaluate, 'environment', lambda: {})
    elif changed == 'pdf':
        pdf.write_bytes(b'changed')
    elif changed == 'freeze':
        freeze.write_text(freeze.read_text() + ' ')
    else:
        (packet / 'report.html').write_text('changed')
    monkeypatch.setattr(evaluate, 'read_pdf', lambda *a, **kw: pytest.fail('Reader ran before validation'))
    with pytest.raises(ValueError):
        evaluate.evaluate(packet, tmp_path / 'results', freeze_path=freeze)
    assert not (tmp_path / 'results').exists()


def test_reader_version_mismatch_blocks_seal(tmp_path, monkeypatch):
    packet, freeze, _, _ = ready(tmp_path, monkeypatch)
    monkeypatch.setattr(evaluate, 'environment', lambda: dict(reader_versions={'pypdf': 'different'}))
    with pytest.raises(ValueError, match='reader versions'):
        evaluate.seal(packet, freeze_path=freeze)


def test_unavailable_records_conserved_without_invented_labels(tmp_path, monkeypatch):
    packet, freeze, export, _ = ready(tmp_path, monkeypatch)
    selected = json.loads(review.SAMPLE.read_text())
    selected['records'].append(dict(document_id='unavailable', split='development', body_keys=[]))
    write_json(review.SAMPLE, selected)
    candidate = json.loads(freeze.read_text()); candidate['sample_sha256'] = file_digest(review.SAMPLE)
    write_json(freeze, candidate)
    packet = tmp_path / 'complete'
    blind.build('development', packet, freeze)
    write_json(export, export_fixture(packet)); blind.import_decisions(packet, export, freeze_path=freeze)
    sealed = evaluate.seal(packet, freeze_path=freeze)
    assert len(sealed['records']) == 2
    assert sealed['records'][1]['verdict'] == 'not_reviewable'
    assert sealed['records'][1]['reference_kind'] == ''
    decisions = export_fixture(packet)
    decisions['decisions'] = [dict(decisions['decisions'][0], review_id='D002', verdict='unavailable',
                                  reference_kind='', evidence_quote='', evidence_page=None)]
    write_json(export, decisions)
    before = (packet / 'reference-decisions.jsonl').read_bytes()
    with pytest.raises(ValueError, match='sealed'):
        blind.import_decisions(packet, export, freeze_path=freeze)
    assert (packet / 'reference-decisions.jsonl').read_bytes() == before
    # Identical imports remain safe after sealing.
    write_json(export, export_fixture(packet))
    assert blind.import_decisions(packet, export, freeze_path=freeze) == []
    evaluate.verify_seal(packet, freeze_path=freeze)


def reading(kind='', status='completed'):
    return dict(status=status, content_document_kind=[kind] if kind else [])


def comparison(identity, baseline, candidate, reference='report', verdict='classified', state='review'):
    return dict(review_id=identity, baseline=baseline, candidate=candidate,
                reference_kind=reference, reference_verdict=verdict, evidence_state=state)


def test_metrics_distinguish_errors_abstentions_unscored_and_missing():
    rows = [comparison('exact', reading(), reading('report')),
            comparison('wrong', reading('report'), reading('amendment')),
            comparison('error', reading(), reading(status='failed')),
            comparison('abstain', reading(), reading()),
            comparison('uncertain', reading(), reading('report'), '', 'uncertain'),
            comparison('missing', reading(status='not_run'), reading(status='not_run'), '', 'not_reviewable', 'unavailable')]
    result = evaluate.summarize(rows)
    metric = result['metrics']['candidate']
    assert result['records'] == 6
    assert metric['attempted'] == 5 and metric['not_run'] == 1
    assert metric['assigned'] == 3 and metric['scored_assignments'] == 2
    assert metric['exact_agreements'] == 1 and metric['unscored_assignments'] == 1
    assert metric['abstentions'] == 1 and metric['reader_errors'] == ['error']
    assert metric['disagreements'] == [dict(review_id='wrong', expected='report', observed='amendment')]
    assert result['changed_prior_kinds'] == ['wrong']
    assert result['rule_status']['amendment']['status'] == 'blocked_observed_error'
    assert result['rule_status']['report']['status'] == 'blocked_observed_error'
    assert not any(v['automatic_release'] for v in result['rule_status'].values())
    assert metric['attempted'] == metric['assigned'] + metric['abstentions'] + len(metric['reader_errors'])


def test_reader_failure_cannot_appear_as_a_new_assignment_or_agreement():
    result = evaluate.summarize([comparison('x', reading(status='failed'), reading('report')),
                                 comparison('y', reading('report'), reading('report', 'failed'))])
    assert result['newly_assigned'] == []
    assert result['changed_prior_kinds'] == ['y']
    assert result['metrics']['candidate']['assigned'] == 1


def test_lost_prior_kind_is_flagged_even_without_reference_or_new_prediction():
    result = evaluate.summarize([comparison('x', reading('transcript'), reading(), '', 'uncertain')])
    assert result['rule_status']['transcript']['status'] == 'blocked_observed_error'
    assert result['rule_status']['transcript']['changed_prior_kinds'] == ['x']


def test_small_sample_interval_does_not_imply_perfect_precision():
    assert evaluate.interval(0, 0) is None
    assert evaluate.interval(1, 1)[0] == pytest.approx(0.2065493144)
    assert evaluate.interval(24, 24)[0] == pytest.approx(0.8620237953)
    low, high = evaluate.interval(5, 10)
    assert low < 0.5 < high and low + high == pytest.approx(1)


def test_evaluation_reuses_native_reader_and_writes_bound_summary(tmp_path, monkeypatch):
    packet, freeze, _, pdf = ready(tmp_path, monkeypatch)
    evaluate.seal(packet, freeze_path=freeze)
    monkeypatch.setattr(evaluate.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=b'baseline'))
    calls = []
    def read(path, expected, fingerprint, baseline=None):
        calls.append((path.resolve(), expected, baseline))
        return reading('report' if baseline is None else '')
    monkeypatch.setattr(evaluate, 'read_pdf', read)
    # The test runtime needs a fingerprint only when invoking candidate workers.
    sealed = json.loads((packet / 'label-freeze.json').read_text())
    sealed['environment']['reader_fingerprint'] = 'test-reader'
    write_json(packet / 'label-freeze.json', sealed)
    monkeypatch.setattr(evaluate, 'environment', lambda: sealed['environment'])
    output = tmp_path / 'results'
    result = evaluate.evaluate(packet, output, freeze_path=freeze)
    assert result['completed'] and result['metrics']['candidate']['exact_agreements'] == 1
    assert result['newly_assigned'] == ['D001']
    assert len(calls) == 2 and all(c[0] == pdf and c[1] == file_digest(pdf) for c in calls)
    assert result['readings_sha256'] == file_digest(output / 'readings.jsonl')
    assert result['purpose'] == 'practice' and result['human_validated'] is False


@pytest.mark.parametrize('response', [b'other baseline', b''])
def test_wrong_baseline_never_invokes_reader(tmp_path, monkeypatch, response):
    packet, freeze, _, _ = ready(tmp_path, monkeypatch)
    evaluate.seal(packet, freeze_path=freeze)
    monkeypatch.setattr(evaluate.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=response))
    monkeypatch.setattr(evaluate, 'read_pdf', lambda *a, **kw: pytest.fail('Reader ran with wrong baseline'))
    with pytest.raises(ValueError, match='Baseline parser'):
        evaluate.evaluate(packet, tmp_path / 'results', freeze_path=freeze)


def test_actual_pdf_worker_uses_maintained_reader():
    pdf = evaluate.ROOT / 'tests/fixtures/document-covers/house-amendment.pdf'
    result = evaluate.read_pdf(pdf, file_digest(pdf), 'test-native-reader')
    assert result['status'] == 'completed'
    assert result['content_document_kind'] == ['amendment']
    assert result['parser_fingerprint'] == 'test-native-reader'


def test_frozen_baseline_worker_survives_reader_move(tmp_path):
    freeze = json.loads((evaluate.HERE / 'content_rule_freeze.json').read_text())
    source = evaluate.subprocess.run(
        ['git', 'show', freeze['baseline_commit'] + ':' + evaluate.COVER],
        cwd=evaluate.ROOT, check=True, capture_output=True).stdout
    baseline = tmp_path / 'baseline_document_cover.py'
    baseline.write_bytes(source)
    assert file_digest(baseline) == freeze['development_summary']['baseline_parser_sha256']
    pdf = evaluate.ROOT / 'tests/fixtures/document-covers/house-amendment.pdf'
    before = evaluate.read_pdf(pdf, file_digest(pdf), 'baseline-reader', baseline)
    after = evaluate.read_pdf(pdf, file_digest(pdf), 'candidate-reader')
    assert before['status'] == 'completed', before
    assert not before.get('content_document_kind')
    assert after['status'] == 'completed', after
    assert after['content_document_kind'] == ['amendment']


def test_worker_refuses_changed_body():
    pdf = evaluate.ROOT / 'tests/fixtures/document-covers/house-amendment.pdf'
    result = evaluate.read_pdf(pdf, '0' * 64, 'test-native-reader')
    assert result['status'] == 'worker_failed'
    assert 'PDF changed' in result['diagnostic']


def test_heldout_publication_gate_and_single_run_marker(tmp_path, monkeypatch):
    packet, freeze, export, _ = ready(tmp_path, monkeypatch, decided=False)
    (tmp_path / 'development').rename(tmp_path / 'held-out')
    receipts = review.records(); receipts['doc']['split'] = 'held-out'
    selected = json.loads(review.SAMPLE.read_text()); selected['records'][0]['split'] = 'held-out'
    write_json(review.SAMPLE, selected)
    candidate = json.loads(freeze.read_text()); candidate['sample_sha256'] = file_digest(review.SAMPLE)
    write_json(freeze, candidate)
    current = document(); current['body_keys'] = selected['records'][0]['body_keys']
    root, _, manifest = catalog(tmp_path, [current])
    pub = publication(tmp_path, manifest)
    reconciled = tmp_path / 'reconciled'
    pilot_reconcile.run(review.SAMPLE, None, reconciled, catalog_root=root, publication_dir=pub)
    packet = tmp_path / 'heldout-packet'
    blind.build('held-out', packet, freeze, reconciled)
    decisions = export_fixture(packet); decisions['decisions'][0]['review_id'] = 'H001'
    write_json(export, decisions)
    blind.import_decisions(packet, export, freeze_path=freeze, reconciliation=reconciled)
    evaluate.seal(packet, freeze_path=freeze, reconciliation=reconciled)
    calls = []
    monkeypatch.setattr(evaluate.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=b'baseline'))
    monkeypatch.setattr(evaluate, 'read_pdf', lambda *a, **kw: calls.append(a) or reading('report'))
    readback = pub / 'public-readback.json'; before = readback.read_bytes()
    value = json.loads(before); value['public_readback'] = 'not_verified'; write_json(readback, value)
    with pytest.raises(ValueError, match='Publication evidence'):
        evaluate.evaluate(packet, tmp_path / 'blocked', freeze_path=freeze, reconciliation=reconciled)
    assert calls == [] and not (packet / 'evaluation-started.json').exists()
    readback.write_bytes(before)
    result = evaluate.evaluate(packet, tmp_path / 'first', freeze_path=freeze, reconciliation=reconciled)
    assert result['purpose'] == 'reference_review' and len(calls) == 2
    assert (packet / 'evaluation-started.json').is_file()
    with pytest.raises(FileExistsError):
        evaluate.evaluate(packet, tmp_path / 'second', freeze_path=freeze, reconciliation=reconciled)
    assert len(calls) == 2
