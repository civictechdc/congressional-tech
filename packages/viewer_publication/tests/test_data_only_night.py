"""ct-pz32: a night only new receipts can explain needs no cause record, inside its tripwires."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication.data_only_night import (COLUMN_LOSS_FLOOR, DATA_ONLY_CAUSE, FILE_ROWS_PER_RECEIPT, GROUP_FLOOR,
                                                GROUP_ROWS_PER_RECEIPT, RECAPTURED_PAGES, REMOVED_DOCUMENTS,
                                                column_values, data_only_causes, recaptured_pages, unattended_causes)

PROFILE = dict(parser_versions={'html_metadata': 'c226'}, file_hashes={'model/sql/list.sql': 'a' * 64, 'model/sql/detail.sql': 'b' * 64})
INPUTS = dict(profile=PROFILE, entity_digests={'members': 'm' * 64}, provenance=[dict(key='provenance/reviews/r.jsonl', etag='"1"')],
              unprofiled_inputs=dict(producer_versions={'captures': 'c' * 64}, job_pins={'model_spec': 's' * 64, 'daily': 'd' * 64}))
LIVE_KEYS = ['receipts/documents/2026-11-16/a.jsonl.gz', 'receipts/house/pages/2026-11-16/b.jsonl.gz']
NEW_KEY = 'receipts/documents/2026-11-17/c.jsonl.gz'
NIGHT = [f'receipts/house/pages/2026-11-17/{n:04}.jsonl.gz' for n in range(1173)]   # the first measured night's size
REAL = Path(__file__).parent / 'fixtures/data-only-night'
ROWS = {'list.parquet': 400_000, 'detail.parquet': 300_000, 'url_state.parquet': 1_200_000, 'recoveries.parquet': 12_000,
        'channels.parquet': 100}


def group(file, name, count, cause='value differs on matched key', status='unverified', **extra):
    if name.startswith('changed ') and cause == 'value differs on matched key':
        extra.setdefault('value', True)  # as release_comparison.value_group marks a changed column
    return dict(file=file, group=name, cause=cause, count=count, status=status, **extra)


def link_rule(ok=True, **found):
    """The link rule's report: counts and answers for each kind, as release_comparison writes it."""
    rule = dict(ok=ok, missing=0, dangling=0, published_and_retired=0, demoted=0, unchecked=[])
    for prefix in ('', 'lookup_', 'address_'):
        rule.update({prefix + 'changed': 0, prefix + 'changed_answers': []})
    rule.update(found)
    return rule


def report(*groups, link_ok=True, rule=None):
    return dict(link_rule=rule or link_rule(link_ok), failing=[g for g in groups if g['status'] != 'verified'],
                files={name: dict(rows=dict(base=rows, candidate=rows), groups=[{k: v for k, v in g.items() if k != 'file'}
                                                                                 for g in groups if g['file'] == name])
                       for name, rows in ROWS.items()})


def live(keys=LIVE_KEYS, **changes):
    return dict(release_id='1' * 64, key='viewer-publications/releases/1/inputs/x.json', record=dict(INPUTS, **changes),
                receipt_keys=list(keys))


@pytest.fixture
def releases(tmp_path):
    """Two releases whose one file has a full column and a sparse one, written by the caller."""
    def write(name, titles, notes):
        (tmp_path / name).mkdir()
        pq.write_table(pa.table({'title': titles, 'note': pa.array(notes, pa.string()),
                                 'tags': pa.array([[t] if t else [] for t in titles], pa.list_(pa.string()))}),
                       tmp_path / name / 'list.parquet')
        return tmp_path / name
    return write


@pytest.fixture
def decide(releases):
    base = releases('base', ['t'] * 1000, ['n'] * 200 + [None] * 800)
    same = releases('same', ['t'] * 1000, ['n'] * 200 + [None] * 800)
    def run(value, *, record=INPUTS, records=None, keys=(*LIVE_KEYS, *NIGHT), candidate_dir=same, link_proof=None):
        return data_only_causes(value, candidate_record=record, live_records=[live()] if records is None else records,
                                candidate_receipt_keys=list(keys), base_dir=base, candidate_dir=candidate_dir, link_proof=link_proof)
    return run


def test_every_group_of_a_night_built_from_the_live_inputs_is_attributed_without_a_record(decide):
    value = report(group('list.parquet', 'changed title', 1097), group('list.parquet', 'added rows', 478, 'no surviving link key'),
                   group('url_state.parquet', 'removed URLs', -680, 'unexplained', 'unexplained'),
                   group('recoveries.parquet', 'changed bytes, no key or value difference found', 0, 'unexplained', 'unexplained', flag=True))
    entries, reasons, facts = decide(value)
    assert reasons == []
    assert [(e['id'], e['count']) for e in entries] == [
        ('list.parquet|changed title|value differs on matched key', 1097), ('list.parquet|added rows|no surviving link key', 478),
        ('url_state.parquet|removed URLs|unexplained', -680),
        ('recoveries.parquet|changed bytes, no key or value difference found|unexplained', 0)]
    assert all(e['cause'] == DATA_ONLY_CAUSE and e['disposition'] == 'explained' and e['automatic'] and e['tickets'] == ['ct-pz32']
               for e in entries)
    assert (facts['live_receipts'], facts['new_receipt_keys'], facts['groups'], facts['columns_compared']) == (2, NIGHT, 4, 3)
    from congress_api.lake.versions import version_digest
    assert facts['profile_sha256'] == version_digest(packages={}, files={}, values=PROFILE)


@pytest.mark.parametrize('change,names', [
    (dict(profile=dict(PROFILE, file_hashes=dict(PROFILE['file_hashes'], **{'model/sql/list.sql': 'c' * 64}))),
     'profile.file_hashes.model/sql/list.sql'),
    (dict(profile=dict(PROFILE, parser_versions={'html_metadata': 'next'})), 'profile.parser_versions.html_metadata'),
    (dict(entity_digests={'members': 'n' * 64}), 'entity_digests.members'),
    (dict(provenance=[dict(key='provenance/reviews/r.jsonl', etag='"2"')]), 'provenance'),
    (dict(unprofiled_inputs=dict(INPUTS['unprofiled_inputs'], producer_versions={'captures': 'e' * 64})),
     'unprofiled_inputs.producer_versions.captures'),
    (dict(unprofiled_inputs=dict(INPUTS['unprofiled_inputs'], job_pins={'model_spec': 's' * 64, 'daily': 'f' * 64})),
     'unprofiled_inputs.job_pins.daily'),
])
def test_a_changed_definition_pin_decision_or_producer_is_not_a_data_only_night(decide, change, names):
    entries, reasons, _ = decide(report(group('list.parquet', 'changed title', 3)), record=dict(INPUTS, **change))
    assert entries == [] and reasons == [f'data-only night: the candidate differs from the live release in {names}']
    # Every refusal found is named, not only the first: here also a night over its cap.
    stopped = decide(report(group('list.parquet', 'changed title', 9000), link_ok=False), record=dict(INPUTS, **change))[1]
    assert len(stopped) == 3 and stopped[0] == 'data-only night: the link rule failed (not ok)'


def test_an_input_neither_side_names_cannot_be_called_equal(decide):
    value = report(group('list.parquet', 'changed title', 3))
    old = live(); del old['record']['unprofiled_inputs']
    assert decide(value, records=[old])[1] == ['data-only night: the live release keeps no unprofiled_inputs to compare with']
    bare = {k: v for k, v in INPUTS.items() if k != 'unprofiled_inputs'}
    assert decide(value, record=bare, records=[old])[1] == ['data-only night: the candidate names no unprofiled_inputs']


def test_daily_qualification_provenance_may_grow_while_decisions_and_removed_ledgers_stop(tmp_path, releases):
    """Review 7b: daily capture appends receipt-bound provenance/qualifications/ ledgers without
    stopping a mixed data-only night, while decision edits, removed ledgers or unknown receipts stop."""
    import hashlib
    from congress_api.retention.provenance import file_pin
    from congress_api.retention.qualification_facts import build_qualification_fact
    from congress_shared.custody import verify_local_file
    from corpus_recovery.qualification import qualify

    base = releases('qbase', ['t'] * 1000, ['n'] * 200 + [None] * 800)
    cand = releases('qcand', ['t'] * 1000, ['n'] * 200 + [None] * 800)
    bad_pdf = tmp_path / 'bad.pdf'
    bad_pdf.write_bytes(b'%PDF-1.7\ntruncated')
    q_rec = qualify(verify_local_file(bad_pdf), tmp_path / 'qcache')

    q_key_1 = 'provenance/qualifications/20261116T120000Z-' + '1' * 64 + '.jsonl'
    q_key_2 = 'provenance/qualifications/20261117T120000Z-' + '2' * 64 + '.jsonl'
    q_path_2 = tmp_path / 'q2.jsonl'
    fact_2 = build_qualification_fact(q_rec, requested_url='https://fixture.test/doc.pdf', url='https://fixture.test/doc.pdf',
                                      receipt_key=NIGHT[0], retrieved_at='2026-11-17T12:00:00Z', http_status=200,
                                      headers={'Content-Type': 'application/pdf'})
    q_bytes_2 = (json.dumps(fact_2, sort_keys=True) + '\n').encode()
    q_path_2.write_bytes(q_bytes_2)
    etag_1 = '"' + 'a' * 32 + '"'
    etag_2 = '"' + hashlib.md5(q_bytes_2).hexdigest() + '"'

    live_prov = [*INPUTS['provenance'], dict(key=q_key_1, etag=etag_1)]
    cand_prov = [*live_prov, dict(key=q_key_2, etag=etag_2)]
    val = report(group('list.parquet', 'changed title', 5))

    entries, reasons, _ = data_only_causes(
        val, candidate_record=dict(INPUTS, provenance=cand_prov),
        live_records=[live(provenance=live_prov)],
        candidate_receipt_keys=[*LIVE_KEYS, *NIGHT], base_dir=base, candidate_dir=cand,
        qualification_files=[dict(key=q_key_2, path=str(q_path_2), **file_pin(q_path_2))],
    )
    assert reasons == [] and len(entries) == 1

    # Dropping or mutating an existing live qualification ledger stops the night.
    _, dropped_reasons, _ = data_only_causes(
        val, candidate_record=dict(INPUTS, provenance=[*INPUTS['provenance'], dict(key=q_key_2, etag=etag_2)]),
        live_records=[live(provenance=live_prov)],
        candidate_receipt_keys=[*LIVE_KEYS, *NIGHT], base_dir=base, candidate_dir=cand,
    )
    assert dropped_reasons == ['data-only night: the candidate differs from the live release in provenance']

    # Citing an unknown receipt outside candidate_receipt_keys stops the night.
    q_path_unknown = tmp_path / 'q-unknown.jsonl'
    fact_unknown = build_qualification_fact(q_rec, requested_url='https://fixture.test/doc.pdf', url='https://fixture.test/doc.pdf',
                                            receipt_key='receipts/documents/2026-11-19/outside.jsonl.gz',
                                            retrieved_at='2026-11-19T12:00:00Z', http_status=200)
    raw_unk = (json.dumps(fact_unknown, sort_keys=True) + '\n').encode()
    q_path_unknown.write_bytes(raw_unk)
    _, unk_reasons, _ = data_only_causes(
        val, candidate_record=dict(INPUTS, provenance=[*live_prov, dict(key=q_key_2, etag='"' + hashlib.md5(raw_unk).hexdigest() + '"')]),
        live_records=[live(provenance=live_prov)],
        candidate_receipt_keys=[*LIVE_KEYS, *NIGHT], base_dir=base, candidate_dir=cand,
        qualification_files=[dict(key=q_key_2, path=str(q_path_unknown), **file_pin(q_path_unknown))],
    )
    assert any('cites unknown receipts' in r for r in unk_reasons)

    # Review 7c: unbound records (receipt_key=None) and retryable=True records citing unknown receipts also stop.
    from dataclasses import asdict
    from datetime import datetime, timezone
    from corpus_recovery.qualification import QualificationConfig, _finish, _identity

    q_path_unbound = tmp_path / 'q-unbound.jsonl'
    fact_unbound = build_qualification_fact(q_rec, requested_url='https://fixture.test/doc.pdf', url='https://fixture.test/doc.pdf',
                                            receipt_key=None, retrieved_at='2026-11-17T12:00:00Z', http_status=200)
    raw_unb = (json.dumps(fact_unbound, sort_keys=True) + '\n').encode()
    q_path_unbound.write_bytes(raw_unb)
    _, unb_reasons, _ = data_only_causes(
        val, candidate_record=dict(INPUTS, provenance=[*live_prov, dict(key=q_key_2, etag='"' + hashlib.md5(raw_unb).hexdigest() + '"')]),
        live_records=[live(provenance=live_prov)],
        candidate_receipt_keys=[*LIVE_KEYS, *NIGHT], base_dir=base, candidate_dir=cand,
        qualification_files=[dict(key=q_key_2, path=str(q_path_unbound), **file_pin(q_path_unbound))],
    )
    assert any('unbound' in r for r in unb_reasons)

    retry_rec = _finish({
        'body_sha256': q_rec['body_sha256'], 'body_bytes': q_rec['body_bytes'],
        'validator': _identity(), 'config': asdict(QualificationConfig()),
        'status': 'unresolved', 'media_type': 'application/pdf', 'reason': 'worker_timeout', 'retryable': True,
    })
    q_path_retry_unk = tmp_path / 'q-retry-unk.jsonl'
    fact_retry_unk = build_qualification_fact(retry_rec, requested_url='https://fixture.test/doc.pdf', url='https://fixture.test/doc.pdf',
                                              receipt_key='receipts/documents/2026-11-19/outside-retry.jsonl.gz',
                                              retrieved_at='2026-11-19T12:00:00Z', http_status=200)
    raw_ru = (json.dumps(fact_retry_unk, sort_keys=True) + '\n').encode()
    q_path_retry_unk.write_bytes(raw_ru)
    _, ru_reasons, _ = data_only_causes(
        val, candidate_record=dict(INPUTS, provenance=[*live_prov, dict(key=q_key_2, etag='"' + hashlib.md5(raw_ru).hexdigest() + '"')]),
        live_records=[live(provenance=live_prov)],
        candidate_receipt_keys=[*LIVE_KEYS, *NIGHT], base_dir=base, candidate_dir=cand,
        qualification_files=[dict(key=q_key_2, path=str(q_path_retry_unk), **file_pin(q_path_retry_unk))],
    )
    assert any('cites unknown receipts' in r for r in ru_reasons)

    # Review 7c: a mixed night (changed list.parquet title + url_state clearing body_not_qualified on a 304)
    # routed through unattended_causes -> data_only_causes MUST refuse without positive qualification proof!
    pq.write_table(pa.table({
        'requested_url': ['https://fixture.test/doc.pdf'],
        'attempts': pa.array([1], pa.int32()),
        'last_good_at': pa.array([datetime(2026, 11, 16, tzinfo=timezone.utc)], pa.timestamp('us', tz='UTC')),
        'capture_disposition': ['eligible'],
        'capture_reason': ['body_not_qualified'],
    }), base / 'url_state.parquet')
    pq.write_table(pa.table({
        'requested_url': ['https://fixture.test/doc.pdf'],
        'attempts': pa.array([2], pa.int32()),
        'last_good_at': pa.array([datetime(2026, 11, 16, tzinfo=timezone.utc)], pa.timestamp('us', tz='UTC')),
        'capture_disposition': ['eligible'],
        'capture_reason': ['no_satisfying_recovery'],
    }), cand / 'url_state.parquet')
    mixed_rep = report(
        group('list.parquet', 'changed title', 1),
        group('url_state.parquet', 'changed capture_reason', 1),
    )
    mixed_entries, mixed_reasons, _ = unattended_causes(
        mixed_rep,
        traced=lambda _r: pytest.fail('mixed night should route to data_only'),
        data_only=lambda r: data_only_causes(
            r, candidate_record=INPUTS, live_records=[live()],
            candidate_receipt_keys=[*LIVE_KEYS, NIGHT[0]], base_dir=base, candidate_dir=cand,
            qualification_files=(),
        ),
    )
    assert mixed_entries == []
    assert any('capture_reason is not implied by verified body qualifications' in r for r in mixed_reasons)

    # Review 7d: mixed-night A -> B cross-URL SHA false-clear reproduction!
    # URL u serves qualified body A in NIGHT[0] (advancing last_good_at), then serves failed body B2
    # in NIGHT[1] whose verified failure was recorded under u_other (so URL-only lookup on u sees A).
    # Capture-backed qual_states_job joins u's latest capture to B2 by SHA and REFUSES the false clear;
    # when u's latest capture genuinely is A, qual_states_job APPROVES the clear!
    import io
    import os
    from pypdf import PdfWriter
    from docspec_client.client import NativeDatasets
    from viewer_publication.release_gate import qual_states_job
    from test_release_gate import write_captures

    pw = PdfWriter()
    pw.add_blank_page(width=72, height=72)
    pbuf = io.BytesIO()
    pw.write(pbuf)
    good_pdf_a = pbuf.getvalue()
    good_path_a = tmp_path / 'good-a.pdf'
    good_path_a.write_bytes(good_pdf_a)
    good_rec_a = qualify(verify_local_file(good_path_a), tmp_path / 'qcache')
    assert good_rec_a['status'] == 'qualified'

    bad_pdf_b2 = b'%PDF-1.7\n99 0 obj\n<< /Type /Catalog >>\ntruncated-cross-url'
    bad_path_b2 = tmp_path / 'bad-b2.pdf'
    bad_path_b2.write_bytes(bad_pdf_b2)
    bad_rec_b2 = qualify(verify_local_file(bad_path_b2), tmp_path / 'qcache')
    assert bad_rec_b2['status'] == 'unresolved'

    u_target = 'https://fixture.test/doc.pdf'
    u_other = 'https://fixture.test/other-mirror.pdf'
    t_live = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    t_good_a = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    t_bad_b2 = datetime(2026, 11, 17, 13, 0, tzinfo=timezone.utc)

    q_ab_path = tmp_path / 'q-ab.jsonl'
    q_ab_bytes = (
        json.dumps(build_qualification_fact(q_rec, requested_url=u_target, url=u_target,
                                            receipt_key=LIVE_KEYS[0], retrieved_at=t_live.isoformat(), http_status=200), sort_keys=True) + '\n'
        + json.dumps(build_qualification_fact(good_rec_a, requested_url=u_target, url=u_target,
                                              receipt_key=NIGHT[0], retrieved_at=t_good_a.isoformat(), http_status=200), sort_keys=True) + '\n'
        + json.dumps(build_qualification_fact(bad_rec_b2, requested_url=u_other, url=u_other,
                                              receipt_key=LIVE_KEYS[0], retrieved_at=t_live.isoformat(), http_status=200), sort_keys=True) + '\n'
    ).encode()
    q_ab_path.write_bytes(q_ab_bytes)
    q_ab_key = 'provenance/qualifications/20261117T130500Z-' + '3' * 64 + '.jsonl'
    q_ab_etag = '"' + hashlib.md5(q_ab_bytes).hexdigest() + '"'
    q_ab_files = [dict(key=q_ab_key, path=str(q_ab_path), **file_pin(q_ab_path))]
    cand_ab_prov = [*INPUTS['provenance'], dict(key=q_ab_key, etag=q_ab_etag)]

    pq.write_table(pa.table({
        'requested_url': [u_target],
        'attempts': pa.array([3], pa.int32()),
        'last_good_at': pa.array([t_bad_b2], pa.timestamp('us', tz='UTC')),
        'capture_disposition': ['eligible'],
        'capture_reason': ['no_satisfying_recovery'],
    }), cand / 'url_state.parquet')

    caps_ab_pq = tmp_path / 'caps-ab.parquet'
    write_captures([
        dict(mode='fetch', complete=True, attempt=0, http_status=200, receipt_key=LIVE_KEYS[0], receipt_line=1,
             requested_url=u_target, sha256=bytes.fromhex(q_rec['body_sha256']), retrieved_at=t_live, outcome='stored'),
        dict(mode='fetch', complete=True, attempt=0, http_status=200, receipt_key=NIGHT[0], receipt_line=1,
             requested_url=u_target, sha256=bytes.fromhex(good_rec_a['body_sha256']), retrieved_at=t_good_a, outcome='stored'),
        dict(mode='fetch', complete=True, attempt=0, http_status=200, receipt_key=NIGHT[1], receipt_line=1,
             requested_url=u_target, sha256=bytes.fromhex(bad_rec_b2['body_sha256']), retrieved_at=t_bad_b2, outcome='stored'),
    ], caps_ab_pq)

    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as eng:
        ab_entries, ab_reasons, _ = unattended_causes(
            mixed_rep,
            traced=lambda _r: pytest.fail('mixed night should route to data_only'),
            data_only=lambda r: data_only_causes(
                r, candidate_record=dict(INPUTS, provenance=cand_ab_prov), live_records=[live()],
                candidate_receipt_keys=[*LIVE_KEYS, NIGHT[0], NIGHT[1]], base_dir=base, candidate_dir=cand,
                qualification_files=q_ab_files,
                qual_proof=lambda urls: qual_states_job(
                    tmp_path / 'qual-ab', eng, dict(kind='parquet', path=str(caps_ab_pq)),
                    new_receipts={NIGHT[0], NIGHT[1]}, held_receipts=set(LIVE_KEYS),
                    qual_urls=urls, qualification_files=q_ab_files,
                ),
            ),
        )
        assert ab_entries == []
        assert any('capture_reason is not implied by verified body qualifications' in r for r in ab_reasons)

        # Positive counterpart: when u_target's latest capture is A (only NIGHT[0], attempts=2, last_good_at=t_good_a),
        # qual_states_job proves (url_qualified=True, new_body_qualified=True) and approves the clear!
        caps_ok_pq = tmp_path / 'caps-ok.parquet'
        write_captures([
            dict(mode='fetch', complete=True, attempt=0, http_status=200, receipt_key=LIVE_KEYS[0], receipt_line=1,
                 requested_url=u_target, sha256=bytes.fromhex(q_rec['body_sha256']), retrieved_at=t_live, outcome='stored'),
            dict(mode='fetch', complete=True, attempt=0, http_status=200, receipt_key=NIGHT[0], receipt_line=1,
                 requested_url=u_target, sha256=bytes.fromhex(good_rec_a['body_sha256']), retrieved_at=t_good_a, outcome='stored'),
        ], caps_ok_pq)
        pq.write_table(pa.table({
            'requested_url': [u_target],
            'attempts': pa.array([2], pa.int32()),
            'last_good_at': pa.array([t_good_a], pa.timestamp('us', tz='UTC')),
            'capture_disposition': ['eligible'],
            'capture_reason': ['no_satisfying_recovery'],
        }), cand / 'url_state.parquet')
        ok_entries, ok_reasons, _ = unattended_causes(
            mixed_rep,
            traced=lambda _r: pytest.fail('mixed night should route to data_only'),
            data_only=lambda r: data_only_causes(
                r, candidate_record=dict(INPUTS, provenance=cand_ab_prov), live_records=[live()],
                candidate_receipt_keys=[*LIVE_KEYS, NIGHT[0]], base_dir=base, candidate_dir=cand,
                qualification_files=q_ab_files,
                qual_proof=lambda urls: qual_states_job(
                    tmp_path / 'qual-ok', eng, dict(kind='parquet', path=str(caps_ok_pq)),
                    new_receipts={NIGHT[0]}, held_receipts=set(LIVE_KEYS),
                    qual_urls=urls, qualification_files=q_ab_files,
                ),
            ),
        )
        assert ok_reasons == [] and len(ok_entries) == 2


def test_any_kept_input_of_the_live_release_with_the_same_inputs_serves_and_every_kept_receipt_counts_as_live(decide):
    older = live(keys=['receipts/documents/2026-11-15/z.jsonl.gz'], entity_digests={'members': 'o' * 64})
    value = report(group('list.parquet', 'added rows', 2, 'no surviving link key'))
    # The older input's receipt is live too: a candidate without it dropped a receipt.
    assert 'absent from the candidate' in decide(value, records=[older, live()])[1][0]
    for records in ([older, live()], [live(), older]):
        entries, reasons, facts = decide(value, records=records, keys=[*LIVE_KEYS, 'receipts/documents/2026-11-15/z.jsonl.gz', NEW_KEY])
        assert reasons == [] and len(entries) == 1 and facts['live_receipts'] == 3 and facts['new_receipt_keys'] == [NEW_KEY]
    # A refusal compares with the nearest kept input, wherever it sorts.
    off = dict(INPUTS, entity_digests={'members': 'p' * 64})
    assert [decide(value, record=off, records=records)[1][0] for records in ([older, live()], [live(), older])] == [
        'data-only night: the candidate differs from the live release in entity_digests.members'] * 2


def test_receipts_must_only_grow_and_something_new_must_have_been_read(decide):
    value = report(group('list.parquet', 'changed title', 3))
    assert decide(value, keys=[LIVE_KEYS[0], NEW_KEY])[1] == [
        f"data-only night: 1 receipts the live release read are absent from the candidate (first ['{LIVE_KEYS[1]}'])"]
    assert decide(value, keys=LIVE_KEYS)[1] == [
        'data-only night: the candidate read no receipt the live release did not, so nothing explains a difference']
    # Even with nothing failing: a difference-free night is the traced proof's, and no receipt is no explanation.
    assert decide(report(), keys=LIVE_KEYS)[1]
    assert decide(value, records=[live(keys=[])])[1] == ['data-only night: the live release has no receipt set to compare with']
    assert decide(report(group('list.parquet', 'changed title', 3), link_ok=False))[1] == ['data-only night: the link rule failed (not ok)']


def test_a_catch_up_approves_itself_and_only_the_share_of_a_file_bounds_a_backlog(decide):
    """After a stopped night the next one carries two nights of receipts. No count of nights is
    kept: the caps follow the receipts, and 2% of a file is the ceiling however many there are."""
    two_nights = [*LIVE_KEYS, *NIGHT, *(f'receipts/senate/pages/2026-11-18/{n:04}.jsonl.gz' for n in range(1775))]
    catch_up = report(group('list.parquet', 'changed title', 4000), group('list.parquet', 'added rows', 1200, 'no surviving link key'))
    entries, reasons, facts = decide(catch_up, keys=two_nights)
    assert reasons == [] and len(entries) == 2 and facts['new_receipts'] == 2948
    backlog = [*LIVE_KEYS, *(f'receipts/documents/2026-11-0{n % 9}/{n}.jsonl.gz' for n in range(40_000))]
    assert decide(report(group('list.parquet', 'changed title', 8000)), keys=backlog)[1] == []      # 2% of 400,000
    assert 'more than the 8000 rows' in decide(report(group('list.parquet', 'changed title', 8001)), keys=backlog)[1][0]


@pytest.mark.parametrize('planted', [
    group('list.parquet', 'manifest digest disagrees with file', 0, 'unexplained', 'unexplained', flag=True),
    group('detail.parquet', 'column page_metadata removed', 0, 'schema'),
    group('list.parquet', 'NULL url', 500, 'defect: a published source address must not be null', 'defect'),
    group('channels.parquet', 'file added', 40, 'file absent from the base release'),
    group('list.parquet', 'added bills', 21, 'unexplained', 'unexplained'),
    group('list.parquet', 'live file now an alternate', 3, 'a person decides which file a link opens (ct-4qld)'),
    group('list.parquet', 'removed rows', -1, 'no surviving link key'),
    group('list.parquet', 'added rows', 3, 'no surviving link key', flag=True),
])
def test_only_the_shapes_a_capture_night_makes_are_explained_and_the_rest_wait_for_a_person(decide, planted):
    entries, reasons, _ = decide(report(group('list.parquet', 'changed title', 5, value=True), planted))
    assert entries == [] and len(reasons) == 1 and 'is not a difference new receipts alone explain' in reasons[0]
    assert planted['group'] in reasons[0]


@pytest.mark.parametrize('file,name,count,status,new,passes', [
    # Five rows for each new receipt: a night of 1,173 may move 5,865 in one group, a night of 400 only 2,000.
    ('url_state.parquet', 'added URLs', 5865, 'unverified', 1173, True), ('url_state.parquet', 'added URLs', 5866, 'unverified', 1173, False),
    ('url_state.parquet', 'added URLs', 2000, 'unverified', 400, True), ('url_state.parquet', 'added URLs', 2001, 'unverified', 400, False),
    # Never more than 2% of the file, however many receipts: 240 of recoveries' 12,000 rows.
    ('recoveries.parquet', 'added keys', 240, 'unverified', 1173, True), ('recoveries.parquet', 'added keys', 241, 'unverified', 1173, False),
    ('channels.parquet', 'added keys', GROUP_FLOOR, 'unverified', 1, True), ('channels.parquet', 'added keys', GROUP_FLOOR + 1, 'unverified', 1, False),
    # A verified group is proven to be what it says, not to be small.
    ('list.parquet', 'removed rows', -REMOVED_DOCUMENTS, 'verified', 1173, True), ('list.parquet', 'removed rows', -REMOVED_DOCUMENTS - 1, 'verified', 1173, False),
    ('url_state.parquet', 'removed URLs', -3000, 'verified', 1173, True), ('url_state.parquet', 'removed URLs', -40_000, 'verified', 1173, False),  # 0.25% of the queue
    ('recoveries.parquet', 'removed keys', -GROUP_FLOOR, 'verified', 1173, True), ('recoveries.parquet', 'removed keys', -GROUP_FLOOR - 1, 'verified', 1173, False),
    ('list.parquet', 'added keys', 8001, 'verified', 2000, False),
])
def test_tripwires_scale_with_the_nights_receipts_and_each_files_own_rows(decide, file, name, count, status, new, passes):
    changed = group('list.parquet', 'changed title', 5)
    entries, reasons, _ = decide(report(changed, group(file, name, count, 'fixture', status)), keys=[*LIVE_KEYS, *NIGHT[:new], *(
        f'receipts/senate/pages/2026-11-17/{n}.jsonl.gz' for n in range(max(0, new - len(NIGHT))))])
    assert bool(entries) == passes and bool(reasons) != passes


def test_the_real_capture_night_passes_every_group_check_and_the_real_wipe_stops_on_them_alone(decide):
    night = json.loads((REAL / 'capture-night-20261117-c998ffa0766f.json').read_text())
    entries, reasons, facts = decide(night)                                    # 1,173 receipts new, as that night had
    assert reasons == [] and len(entries) == len(night['failing']) == 42 and facts['groups'] == 42
    assert {e['id']: e['count'] for e in entries} == {f"{g['file']}|{g['group']}|{g['cause']}": g['count'] for g in night['failing']}
    wipe = json.loads((REAL / 'html-metadata-wipe-20261116-08c465599d7b.json').read_text())
    entries, reasons, _ = decide(wipe)
    assert entries == [] and len(reasons) >= 18
    assert any('detail.parquet|changed page_metadata|value differs on matched key (12587)' in reason for reason in reasons)


def test_the_larger_real_night_is_stopped_only_by_what_a_person_must_see(decide):
    """Run 44087092120: 1,775 receipts. Its size is within what its receipts explain; a recaptured
    page (the link rule, until proven) and two single unverified removals are for a person."""
    night = json.loads((REAL / 'larger-capture-night-20261117-2ec7ae83a852.json').read_text())
    larger = [*LIVE_KEYS, *(f'receipts/senate/pages/2026-11-17/{n:04}.jsonl.gz' for n in range(1775))]
    removals = [
        'data-only night: people.parquet|removed keys|person_aliases states the key ambiguous (-1) is not a difference new receipts alone explain; it needs a cause record',
        'data-only night: recording_matches.parquet|removed keys|no evidence given (-1) is not a difference new receipts alone explain; it needs a cause record']
    entries, reasons, _ = decide(dict(night, link_rule=link_rule(False)), keys=larger)
    assert entries == [] and reasons == ['data-only night: the link rule failed (not ok)', *removals]
    # Measured on the smaller nights' fixed caps this night also tripped on its size; scaled to its receipts it does not.
    assert not any('more than' in reason for reason in reasons)
    assert decide(dict(night, link_rule=link_rule()), keys=larger)[1] == removals


BODY, NEWER, OTHER = 'a' * 64, 'b' * 64, 'c' * 64
PAGE = 'https://committee.house.gov/calendar/eventsingle.aspx?EventID=1'
RECEIPT = 'receipts/house/pages/2026-11-17/run-1.jsonl.gz'


def recapture(tmp_path, *, title='Hearing on Shipbuilding', status=200, url=PAGE, stores=NEWER, receipt=RECEIPT,
              title_source='page_title', media='text/html', **found):
    """One page captured again: its address, link key and lookup key all move from BODY to NEWER."""
    import gzip
    for name, titles in (('live', ['other', 'Hearing on Shipbuilding']), ('candidate', ['other', 'filler', title])):
        (tmp_path / name).mkdir(exist_ok=True)
        pq.write_table(pa.table({'title': titles}), tmp_path / name / 'list.parquet')
        page = name == 'live' or None   # the live row is always a page; the candidate row takes the arguments
        pq.write_table(pa.table({'title_source': pa.array([None] * (len(titles) - 1) + ['page_title' if page else title_source], pa.string()),
                                 'saved_media_type': pa.array([None] * (len(titles) - 1) + ['text/html' if page else media], pa.string())}),
                       tmp_path / name / 'detail.parquet')
    answers = dict(changed=1, changed_answers=[dict(key='1a56', live_row=1, live_body=BODY, candidate_row=2, candidate_body=NEWER)],
                   lookup_changed=1, lookup_changed_answers=[dict(key='6aea', live_row=1, live_body=BODY, candidate_rows=[2], candidate_bodies=[NEWER])],
                   address_changed=1, address_changed_answers=[dict(key=PAGE, live_row=1, live_body=BODY, candidate_rows=[2], candidate_bodies=[NEWER])])
    answers.update(found)
    line = json.dumps(dict(url=url, requested_url=url.replace('eventsingle', 'EventSingle'), http_status=status,
                           captures=[dict(sha256=stores, bytes=10)]))
    raw = {RECEIPT: gzip.compress(('{"url": "https://elsewhere"}\n' + line + '\n').encode())}
    read = []
    def read_receipt(key):
        read.append(key)
        return raw[key]
    proven, reasons, facts = recaptured_pages(link_rule(False, **answers), tmp_path / 'live', tmp_path / 'candidate', held=set(LIVE_KEYS),
        trace=lambda keys: [dict(prefix=NEWER[:16], receipt_key=receipt, receipt_line=2, sha=NEWER)] if keys == {NEWER[:16]} else [],
        read_receipt=read_receipt)
    return proven, reasons, facts, read


def test_a_page_captured_again_at_its_own_address_under_its_title_is_proven_from_the_raw_receipt(tmp_path):
    proven, reasons, facts, read = recapture(tmp_path)
    assert reasons == [] and read == [RECEIPT]
    assert proven == [dict(kind='link_key', key='1a56', live_body=BODY, candidate_body=NEWER),
                      dict(kind='lookup_key', key='6aea', live_body=BODY, candidate_body=NEWER),
                      dict(kind='address', key=PAGE, live_body=BODY, candidate_body=NEWER)]
    assert facts['recaptures'] == [dict(address=PAGE, live_body=BODY, candidate_body=NEWER, receipt=RECEIPT, title='Hearing on Shipbuilding')]
    # The gate's own matcher accepts exactly these as proven and leaves nothing unnamed.
    from viewer_publication.release_gate import named_corrections
    rule = link_rule(False, changed=1, changed_answers=[dict(key='1a56', live_body=BODY, candidate_body=NEWER)],
                     lookup_changed=1, lookup_changed_answers=[dict(key='6aea', live_body=BODY, candidate_bodies=[NEWER])],
                     address_changed=1, address_changed_answers=[dict(key=PAGE, live_body=BODY, candidate_bodies=[NEWER])],
                     proven_corrections=proven)
    assert named_corrections(rule, [])[2] == dict(link_key=[], lookup_key=[], address=[])
    assert named_corrections(dict(rule, proven_corrections=[]), [])[2]['address']


@pytest.mark.parametrize('change', [
    dict(title='404 Not Found'), dict(title=None), dict(status=500), dict(url='https://committee.house.gov/other'),
    dict(media='application/pdf'), dict(title_source='link_text'), dict(title_source=None),   # a replaced file keeps its listing's title
    dict(address_changed_answers=[dict(key=PAGE, live_row=1, live_body=BODY, candidate_rows=[2], candidate_bodies=[None])]),
    dict(stores=OTHER), dict(receipt=LIVE_KEYS[0]),
    dict(changed_answers=[dict(key='1a56', live_row=1, live_body=BODY, candidate_row=2, candidate_body=OTHER)]),
    dict(address_changed_answers=[dict(key=PAGE, live_row=1, live_body=BODY, candidate_rows=[2, 2], candidate_bodies=[NEWER, OTHER])]),
    dict(address_changed=2),
])
def test_anything_but_that_page_under_that_title_from_a_new_receipt_is_left_to_a_person(tmp_path, change):
    proven, reasons, _, _ = recapture(tmp_path, **change)
    assert reasons and all(reason.startswith('data-only night: ') for reason in reasons)
    # Findings beyond the report's sample refuse the night even though the sampled page is proven.
    assert len(proven) < 3 or change == dict(address_changed=2)


def test_the_link_rule_on_a_data_night_stops_hard_findings_and_takes_proven_recaptures(decide, tmp_path):
    value = report(group('list.parquet', 'changed title', 3))
    for hard in (dict(missing=2), dict(dangling=1), dict(published_and_retired=1), dict(demoted=1), dict(unchecked=['links.parquet absent'])):
        stopped = decide(dict(value, link_rule=link_rule(False, **hard)), link_proof=lambda rule: pytest.fail('a hard finding has no proof'))[1]
        assert len(stopped) == 1 and stopped[0].startswith('data-only night: the link rule failed (')
    moved = link_rule(False, address_changed=1, address_changed_answers=[dict(key=PAGE, live_row=1, live_body=BODY, candidate_rows=[2], candidate_bodies=[NEWER])])
    assert 'they were not examined' in decide(dict(value, link_rule=moved))[1][0]
    # The proof scans the capture table, so a night something else already stopped does not run it.
    over = report(group('list.parquet', 'changed title', 9000), rule=moved)
    stopped = decide(over, link_proof=lambda rule: pytest.fail('the proof must not run on a night already stopped'))[1]
    assert len(stopped) == 2 and 'they were not examined' in stopped[0] and 'changed title' in stopped[1]
    proof = [dict(kind='address', key=PAGE, live_body=BODY, candidate_body=NEWER)]
    entries, reasons, facts = decide(dict(value, link_rule=moved), link_proof=lambda rule: (proof, [], dict(recaptures=[dict(address=PAGE)])))
    assert reasons == [] and len(entries) == 1 and facts['proven_corrections'] == proof and facts['recaptures'] == [dict(address=PAGE)]
    assert decide(dict(value, link_rule=moved), link_proof=lambda rule: ([], ['data-only night: live address would open another file'], {}))[1] == [
        'data-only night: live address would open another file']
    assert RECAPTURED_PAGES == 100


def test_many_groups_each_under_its_cap_still_stop_at_the_files_total(decide):
    columns = [group('detail.parquet', f'changed c{i}', 5000) for i in range(4)]     # 1,173 receipts: 17,595 a file
    entries, reasons, _ = decide(report(*columns))
    assert entries == [] and reasons == [
        f'data-only night: detail.parquet moves 20000 rows across its groups, more than the {FILE_ROWS_PER_RECEIPT * 1173} this night may '
        f'(the lesser of 6% of the file and {FILE_ROWS_PER_RECEIPT} for each of its 1173 new receipts)']
    assert decide(report(*columns[:3]))[1] == [] and GROUP_ROWS_PER_RECEIPT * 1173 >= 5000
    # A backlog cannot widen a file's total past 6% of it: 18,000 of detail's 300,000 rows.
    backlog = [*LIVE_KEYS, *(f'receipts/documents/2026-11-0{n % 9}/{n}.jsonl.gz' for n in range(40_000))]
    assert decide(report(*columns[:3], group('detail.parquet', 'changed c9', 3000)), keys=backlog)[1] == []
    assert '6% of the file' in decide(report(*columns[:3], group('detail.parquet', 'changed c9', 3001)), keys=backlog)[1][0]


def test_a_column_that_empties_stops_the_night_at_any_share_of_its_file(decide, releases):
    value = report(group('list.parquet', 'changed note', 200))                    # 0.05% of the file: no row cap sees it
    wiped = releases('wiped', ['t'] * 1000, [None] * 1000)
    assert decide(value, candidate_dir=wiped)[1] == [
        'data-only night: list.parquet:note lost 200 of its 200 values, more than the 5% one unattended night may']
    emptied = releases('emptied', ['t'] * 800 + [''] * 200, ['n'] * 200 + [None] * 800)   # 200 lists go empty
    assert decide(value, candidate_dir=emptied)[1] == [
        'data-only night: list.parquet:tags.list.element lost 200 of its 1000 values, more than the 5% one unattended night may']
    thinned = releases('thinned', ['t'] * 1000, ['n'] * (200 - COLUMN_LOSS_FLOOR) + [None] * (800 + COLUMN_LOSS_FLOOR))
    assert decide(value, candidate_dir=thinned)[1] == []
    assert column_values(wiped)['list.parquet', 'note'] == 0 and column_values(wiped)['list.parquet', 'title'] == 1000


def test_the_fetch_queue_is_bounded_by_its_row_caps_not_by_the_column_tripwire(decide, tmp_path):
    """A fetched address leaves the queue with its whole linked_from list (run 44065807228)."""
    def queue(name, linked):
        (tmp_path / name).mkdir()
        for file in ('url_state.parquet', 'list.parquet'):
            pq.write_table(pa.table({'linked_from': pa.array(linked, pa.list_(pa.string()))}), tmp_path / name / file)
        return tmp_path / name
    full, worked = queue('full', [['p'] * 10] * 100), queue('worked', [['p'] * 10] * 40 + [[]] * 60)
    value = report(group('url_state.parquet', 'changed linked_from', 60))
    run = lambda files: data_only_causes(value, candidate_record=INPUTS, live_records=[live()],
                                         candidate_receipt_keys=[*LIVE_KEYS, *NIGHT], base_dir=full, candidate_dir=files)
    # The same loss in a content file stops the night; in the queue it does not.
    assert run(worked)[1] == ['data-only night: list.parquet:linked_from.list.element lost 600 of its 1000 values, more than the 5% one unattended night may']
    (worked / 'list.parquet').write_bytes((full / 'list.parquet').read_bytes())
    entries, reasons, facts = run(worked)
    assert reasons == [] and len(entries) == 1 and facts['columns_compared'] == 1


def test_the_traced_proof_decides_every_night_it_can_read_and_data_only_only_the_rest():
    addition = report(group('list.parquet', 'added rows', 3, 'no surviving link key'))
    forbidden = lambda value: pytest.fail('data-only must not decide a night the traced proof can read')
    assert unattended_causes(addition, traced=lambda value: (['traced'], []), data_only=forbidden) == (['traced'], [], None)
    # A proof that ran and refused is final: over its cap, a contradiction in raw, a re-fetch it cannot verify.
    assert unattended_causes(addition, traced=lambda value: ([], ['already in the live release']), data_only=forbidden) == (
        [], ['already in the live release'], None)
    assert unattended_causes(report(), traced=lambda value: ([], ['re-fetch not verified']), data_only=forbidden) == (
        [], ['re-fetch not verified'], None)
    mixed = report(group('list.parquet', 'added rows', 3, 'no surviving link key'), group('list.parquet', 'changed title', 2, value=True))
    assert unattended_causes(mixed, traced=forbidden, data_only=lambda value: (['e'], [], {'f': 1})) == (['e'], [], {'f': 1})
    # The deciding reason leads; the traced proof ran no check, and one line says so.
    assert unattended_causes(mixed, traced=forbidden, data_only=lambda value: ([], ['definition differs'], {})) == (
        [], ['definition differs', 'automatic causes: 1 differences are not additions the traced proof reads, so it ran no check'], None)
    # A verified group the traced proof cannot read is a difference too, with nothing failing.
    quiet = report(group('url_state.parquet', 'removed URLs', -40_000, 'never attempted', 'verified'))
    assert quiet['failing'] == [] and unattended_causes(quiet, traced=forbidden, data_only=lambda value: ([], ['over the cap'], {}))[1][0] == 'over the cap'
