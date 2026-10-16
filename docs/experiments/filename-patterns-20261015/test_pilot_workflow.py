"""Exercise catalog gating and evidence-preserving blind reference decisions."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import pilot_blind_review as blind
import pilot_reconcile as reconcile
import pilot_review as review
from test_pilot_evidence import reference_fixture


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def document(identity='doc', **changes):
    return dict(document_id=identity, source_id='source-' + identity,
                filename='', source_url='https://example.gov/document.pdf',
                source_urls=['https://example.gov/document.pdf'],
                document_kind=[], record_role=['document'], format=['pdf'],
                body_keys=['bodies/sha256/' + 'a' * 64 + '.gz'], **changes)


def catalog(tmp_path, rows, *, invalid_reference=False):
    root = tmp_path / 'catalog'
    generation = 'b' * 32
    folder = root / 'catalog-generations' / generation
    folder.mkdir(parents=True)
    metadata = {b'catalog_id': b'new-catalog', b'house_naming_version': b'3.1.0'}
    documents = folder / 'documents.parquet'
    pq.write_table(pa.Table.from_pylist(rows).replace_schema_metadata(metadata), documents)
    sources = [dict(source_id=row['source_id'], document_id=row['document_id']) for row in rows]
    if invalid_reference:
        sources[0]['document_id'] = 'missing'
    filenames = folder / 'document-filenames.parquet'
    pq.write_table(pa.Table.from_pylist(sources).replace_schema_metadata(metadata), filenames)
    manifest = dict(version=1, generation=generation, catalog_id='new-catalog', files={})
    for label, path in [('documents', documents), ('filenames', filenames)]:
        manifest['files'][label] = dict(key=str(path.relative_to(root)), bytes=path.stat().st_size,
                                       rows=len(rows), sha256=reconcile.file_digest(path))
    write_json(root / 'indexes/catalog.json', manifest)
    return root, documents, manifest


def publication(tmp_path, manifest):
    folder = tmp_path / 'publication'
    commit = 'c' * 40
    write_json(folder / 'publication-receipt.json', dict(status='published_and_verified',
               published_commit=commit, rebuild_run=123, previous_catalog_id='old-catalog', catalog_id='new-catalog'))
    write_json(folder / 'public-readback.json', dict(public_readback='verified', commit=commit,
               rebuild_run='https://github.com/civictechdc/congressional-tech/actions/runs/123',
               catalog_id='new-catalog', house_naming_version='3.1.0'))
    write_json(folder / 'after-public-manifest.json', dict(catalog_id='new-catalog', source_manifest=manifest))
    write_json(folder / 'after-viewer-manifest.json', dict(info=dict(catalog_id='new-catalog',
               house_naming_version='3.1.0'), source_manifest=manifest))
    return folder


def sample_file(tmp_path, rows):
    path = tmp_path / 'sample.json'
    write_json(path, dict(records=rows))
    return path


def test_reconciliation_preserves_missing_and_changed_samples(tmp_path):
    first, changed = document(), document('changed')
    original = [dict(document_id=r['document_id'], split='held-out', body_keys=r['body_keys']) for r in [first, changed]]
    original += [dict(document_id='missing', split='development', body_keys=[])]
    changed.update(record_role=['page'], document_kind=['report'], body_keys=['bodies/' + 'd' * 64 + '.gz'])
    _, documents, _ = catalog(tmp_path, [first, changed, document('not-selected')])
    output = tmp_path / 'rehearsal'
    result = reconcile.run(sample_file(tmp_path, original), documents, output, receipts={})
    ledger = json.loads((output / 'eligibility.json').read_text())['records']
    assert [r['document_id'] for r in ledger] == ['doc', 'changed', 'missing']
    assert [r['review_id'] for r in ledger] == ['H001', 'H002', 'D001']
    assert ledger[0]['catalog_eligible'] and not ledger[0]['reference_available']
    assert set(ledger[1]['changes']) == {'role_changed_or_ambiguous', 'newly_classified', 'body_set_changed'}
    assert set(ledger[2]['changes']) == {'missing_document_id', 'no_frozen_body_digest'}
    assert result['census_totals'] == dict(records=3, unnamed_records=3, unclassified_records=2)
    assert not result['held_out_review_unlocked']


@pytest.mark.parametrize('bad', ['duplicate-sample', 'duplicate-catalog', 'broken-pair', 'changed-file'])
def test_reconciliation_rejects_invalid_inputs(tmp_path, bad):
    rows = [document()]
    if bad == 'duplicate-catalog':
        rows *= 2
    root, documents, _ = catalog(tmp_path, rows, invalid_reference=bad == 'broken-pair')
    selected = [dict(document_id='doc', split='held-out', body_keys=rows[0]['body_keys'])]
    if bad == 'duplicate-sample':
        selected *= 2
    if bad == 'changed-file':
        documents.write_bytes(documents.read_bytes() + b'changed')
    with pytest.raises(ValueError):
        reconcile.run(sample_file(tmp_path, selected), documents, tmp_path / 'result',
                      catalog_root=root if bad in {'broken-pair', 'changed-file'} else None, receipts={})
    assert not (tmp_path / 'result').exists()


def test_verified_pair_unlocks_but_changed_publication_and_ledger_do_not(tmp_path, monkeypatch):
    row = document()
    root, documents, manifest = catalog(tmp_path, [row])
    pub = publication(tmp_path, manifest)
    sample = sample_file(tmp_path, [dict(document_id='doc', split='held-out', body_keys=row['body_keys'])])
    monkeypatch.setattr(review, 'SAMPLE', sample)
    output = tmp_path / 'reconciled'
    result = reconcile.run(sample, None, output, catalog_root=root, publication_dir=pub, receipts={})
    assert result['paired_catalog_validated'] and result['held_out_review_unlocked']
    assert blind.held_out_eligibility(output)['doc']['catalog_eligible']
    readback = pub / 'public-readback.json'
    before = readback.read_bytes()
    value = json.loads(before); value['commit'] = 'd' * 40
    write_json(readback, value)
    with pytest.raises(ValueError, match='Publication evidence'):
        blind.held_out_eligibility(output)
    readback.write_bytes(before)
    (output / 'eligibility.json').write_text('{}')
    with pytest.raises(ValueError, match='Eligibility ledger changed'):
        blind.held_out_eligibility(output)


def packet_fixture(tmp_path, monkeypatch):
    row, pdf, text = reference_fixture(tmp_path, monkeypatch)
    review.LABELS.write_text('{}')
    freeze = tmp_path / 'freeze.json'
    write_json(freeze, dict(candidate='test', source_hashes={}, sample_sha256=reconcile.file_digest(review.SAMPLE),
                           labels_sha256=reconcile.file_digest(review.LABELS)))
    return row, pdf, text, freeze


def export_fixture(output):
    packet = json.loads((output / 'packet.json').read_text())
    return dict(packet_id=packet['packet_id'], decisions=[dict(review_id='D001', reviewer='Test reviewer',
                verdict='classified', reference_kind='report', evidence_page=1, evidence_quote='REPORT', note='Test only')])


def test_packet_is_blind_and_import_is_idempotent_without_relabeling(tmp_path, monkeypatch):
    _, _, _, freeze = packet_fixture(tmp_path, monkeypatch)
    output = tmp_path / 'packet'
    blind.build('development', output, freeze)
    packet = json.loads((output / 'packet.json').read_text())
    assert set(packet['records'][0]) == {'review_id', 'document_id', 'state', 'body_sha256', 'pdf', 'pages'}
    assert packet['purpose'] == 'practice'
    export = tmp_path / 'export.json'
    write_json(export, export_fixture(output))
    labels_before = review.LABELS.read_bytes()
    added = blind.import_decisions(output, export, freeze_path=freeze)
    assert len(added) == 1 and added[0]['human_validated'] is False
    journal = output / 'reference-decisions.jsonl'
    before = journal.read_bytes()
    assert blind.import_decisions(output, export, freeze_path=freeze) == []
    assert journal.read_bytes() == before
    value = export_fixture(output); value['decisions'][0]['reference_kind'] = 'hearing'
    write_json(export, value)
    with pytest.raises(ValueError, match='Existing decision differs'):
        blind.import_decisions(output, export, freeze_path=freeze)
    assert journal.read_bytes() == before and review.LABELS.read_bytes() == labels_before


def test_packet_pdf_links_follow_served_directory_through_worktree_symlink(tmp_path, monkeypatch):
    _, pdf, _, freeze = packet_fixture(tmp_path, monkeypatch)
    linked = tmp_path / 'linked'
    linked.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(review, 'OUT', linked)
    output = tmp_path / 'packet'
    blind.build('development', output, freeze)
    packet = json.loads((output / 'packet.json').read_text())
    link = packet['records'][0]['pdf']
    assert link == '../development/' + pdf.name
    assert (output / link).resolve() == pdf


@pytest.mark.parametrize('blank', [True, False])
def test_unusable_extracted_pages_remain_visual_review(tmp_path, monkeypatch, blank):
    row, _, text, freeze = packet_fixture(tmp_path, monkeypatch)
    if blank:
        text.write_text('  \n')
    else:
        row['bodies'][0]['status'] = 'needs_visual_review'
    row['bodies'][0]['pages'][0]['text_sha256'] = reconcile.file_digest(text)
    output = tmp_path / 'packet'
    blind.build('development', output, freeze)
    packet = json.loads((output / 'packet.json').read_text())
    assert packet['records'][0]['state'] == 'needs_visual_review'
    assert packet['records'][0]['pdf']


def test_verified_heldout_packet_and_reference_import(tmp_path, monkeypatch):
    row, pdf, text, freeze = packet_fixture(tmp_path, monkeypatch)
    pdf.parent.rename(tmp_path / 'held-out')
    row['split'] = 'held-out'
    selected = json.loads(review.SAMPLE.read_text())
    selected['records'][0]['split'] = 'held-out'
    write_json(review.SAMPLE, selected)
    value = json.loads(freeze.read_text()); value['sample_sha256'] = reconcile.file_digest(review.SAMPLE)
    write_json(freeze, value)
    current = document(); current['body_keys'] = selected['records'][0]['body_keys']
    root, _, manifest = catalog(tmp_path, [current])
    pub = publication(tmp_path, manifest)
    reconciled = tmp_path / 'reconciled'
    reconcile.run(review.SAMPLE, None, reconciled, catalog_root=root, publication_dir=pub)
    output = tmp_path / 'packet'
    blind.build('held-out', output, freeze, reconciled)
    packet = json.loads((output / 'packet.json').read_text())
    assert packet['purpose'] == 'reference_review' and packet['records'][0]['review_id'] == 'H001'
    export = export_fixture(output); export['decisions'][0]['review_id'] = 'H001'
    path = tmp_path / 'export.json'; write_json(path, export)
    new = blind.import_decisions(output, path, freeze_path=freeze, reconciliation=reconciled)
    assert len(new) == 1 and new[0]['split'] == 'held-out'


@pytest.mark.parametrize('bad', ['packet', 'interface', 'body', 'quote', 'cross-packet', 'duplicate', 'unknown', 'no-reviewer', 'no-kind'])
def test_bad_decisions_never_write_journal(tmp_path, monkeypatch, bad):
    _, pdf, _, freeze = packet_fixture(tmp_path, monkeypatch)
    output = tmp_path / 'packet'
    blind.build('development', output, freeze)
    value = export_fixture(output)
    if bad == 'packet':
        (output / 'packet.json').write_text('{}')
    elif bad == 'interface':
        (output / 'report.html').write_text('Changed review page')
    elif bad == 'body':
        pdf.write_bytes(b'replaced')
    elif bad == 'quote':
        value['decisions'][0]['evidence_quote'] = 'Not in the document'
    elif bad == 'cross-packet':
        value['packet_id'] = 'other'
    elif bad == 'duplicate':
        value['decisions'] *= 2
    elif bad == 'unknown':
        value['decisions'][0]['review_id'] = 'H001'
    elif bad == 'no-reviewer':
        value['decisions'][0]['reviewer'] = ''
    else:
        value['decisions'][0]['reference_kind'] = ''
    export = tmp_path / 'export.json'; write_json(export, value)
    with pytest.raises(ValueError):
        blind.import_decisions(output, export, freeze_path=freeze)
    assert not (output / 'reference-decisions.jsonl').exists()


@pytest.mark.parametrize('bad', ['candidate', 'text', 'body', 'held-out', 'rehearsal'])
def test_packet_refuses_changed_evidence_and_premature_heldout(tmp_path, monkeypatch, bad):
    _, pdf, text, freeze = packet_fixture(tmp_path, monkeypatch)
    reconciliation = None
    if bad == 'candidate':
        source = tmp_path / 'candidate.py'; source.write_text('before')
        value = json.loads(freeze.read_text()); value['source_hashes'] = {'candidate.py': reconcile.file_digest(source)}
        write_json(freeze, value); monkeypatch.setattr(blind, 'ROOT', tmp_path)
        source.write_text('after')
    elif bad == 'text':
        text.write_text('changed')
    elif bad == 'body':
        pdf.write_bytes(b'changed')
    else:
        # Any attempt to read body/text evidence before the gate is a test failure.
        monkeypatch.setattr(review, 'records', lambda: pytest.fail('Held-out body evidence read before gate'))
        if bad == 'rehearsal':
            reconciliation = tmp_path / 'rehearsal'
            write_json(reconciliation / 'summary.json', dict(held_out_review_unlocked=False))
    with pytest.raises((ValueError, AssertionError)):
        blind.build('held-out' if bad in {'held-out', 'rehearsal'} else 'development',
                    tmp_path / 'packet', freeze, reconciliation)
    assert not (tmp_path / 'packet').exists()
