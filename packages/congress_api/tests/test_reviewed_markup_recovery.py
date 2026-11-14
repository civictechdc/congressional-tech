"""Reviewed repair keys are distinct, while bad pins and unsafe sources stay refused."""
from hashlib import sha256
import json

import pyarrow.parquet as pq
import pytest

from body_text_fixtures import STAMP, committed, lake
from congress_api.lake import body_text
from congress_api.lake.reading_versions import MARKUP_RECOVERY_DECLARATIONS, MARKUP_RECOVERY_VERSIONS
from congress_api.parsers import markup_recovery as recovery

HTML = b'<meta charset="utf-8"><p>Jos\xe9 requested the hearing on March 31.</p>'
HTML_CANDIDATE = '<meta charset="utf-8"><p>José requested the hearing on March 31.</p>'.encode()
HTML_TEXT = 'José requested the hearing on March 31.'
XML = b'<!DOCTYPE bill [<!ENTITY title "Access Act">]><bill><title>&title;</title><p>Grant $1000.</p></bill>'
XML_CANDIDATE = b'<bill><title>Access Act</title><p>Grant $1000.</p></bill>'
XML_TEXT = 'Access Act\nGrant $1000.'


def case(data=HTML, parser='html_text', candidate=HTML_CANDIDATE, text=HTML_TEXT):
    return dict(body_sha256=sha256(data).hexdigest(), parser=parser, policy=recovery.POLICIES[parser],
                candidate_sha256=sha256(candidate).hexdigest(), text_sha256=sha256(text.encode()).hexdigest(),
                review_sha256='a' * 64)


def manifest(tmp_path, cases, **extra):
    path = tmp_path / 'review.json'
    raw = json.dumps({'version': 1, 'cases': cases, **extra}).encode()
    path.write_bytes(raw)
    return dict(path=str(path), sha256=sha256(raw).hexdigest())


def test_declared_recovery_versions_do_not_reuse_ordinary_identity():
    assert {key: sha256(value.encode()).hexdigest() for key, value in MARKUP_RECOVERY_DECLARATIONS.items()} == MARKUP_RECOVERY_VERSIONS
    assert set(MARKUP_RECOVERY_VERSIONS.values()).isdisjoint(body_text.current_versions().values())


@pytest.mark.parametrize('data,row,text', [
    (HTML, case(), HTML_TEXT),
    (XML, case(XML, 'xml_text', XML_CANDIDATE, XML_TEXT), XML_TEXT),
])
def test_actual_consumer_preserves_original_candidate_and_reviewed_output(tmp_path, data, row, text):
    result = recovery.read_reviewed_markup(data, dict(case=row, manifest_sha256='b' * 64), evidence_dir=tmp_path / 'evidence')
    assert result.status == 'completed' and result.text == text
    assert result.fields['source_sha256'] == sha256(data).hexdigest() != result.fields['candidate_sha256']
    assert result.ocr_pages == () and result.page_offsets == (0,)
    assert (tmp_path / 'evidence/original.raw').read_bytes() == data
    evidence = json.loads((tmp_path / 'evidence/recovery.json').read_text())
    assert evidence['qualification'] == 'not_qualified_for_selection' and evidence['review'] == row
    output = json.loads((tmp_path / 'evidence/output.json').read_text())
    assert output['reading_key']['parser_version'] == MARKUP_RECOVERY_VERSIONS[row['parser']]
    assert not output['selected']


@pytest.mark.parametrize('field', ['body_sha256', 'candidate_sha256', 'text_sha256'])
def test_wrong_reviewed_identity_never_yields_a_reading(tmp_path, field):
    row = dict(case(), **{field: '0' * 64})
    with pytest.raises(recovery.RecoveryInputError):
        recovery.read_reviewed_markup(HTML, dict(case=row, manifest_sha256='b' * 64), evidence_dir=tmp_path / 'evidence')
    assert not (tmp_path / 'evidence/output.json').exists()


def test_unsafe_entity_is_a_retained_refusal_with_no_text(tmp_path):
    data = b'<!DOCTYPE bill [<!ENTITY secret SYSTEM "file:///etc/passwd">]><bill>&secret;</bill>'
    row = case(data, 'xml_text', b'not a candidate', '')
    result = recovery.read_reviewed_markup(data, dict(case=row, manifest_sha256='b' * 64), evidence_dir=tmp_path / 'evidence')
    assert result.status == 'error' and result.error_type == 'MarkupRecoveryRefused' and result.text is None
    assert result.fields['recovery_status'] == 'refused'
    assert not (tmp_path / 'evidence/candidate.raw').exists()
    assert (tmp_path / 'evidence/original.raw').read_bytes() == data


def test_successful_ordinary_markup_cannot_be_relabelled_as_recovery(tmp_path):
    row = case(HTML_CANDIDATE)
    with pytest.raises(recovery.RecoveryInputError, match='Ordinary markup already completes'):
        recovery.read_reviewed_markup(HTML_CANDIDATE, dict(case=row, manifest_sha256='b' * 64), evidence_dir=tmp_path / 'evidence')
    assert not (tmp_path / 'evidence').exists()


def test_changed_ordinary_declaration_requires_new_qualification(tmp_path, monkeypatch):
    monkeypatch.setitem(recovery.READING_VERSIONS, 'html_text', '0' * 64)
    with pytest.raises(recovery.RecoveryInputError, match='renewed qualification'):
        recovery.read_reviewed_markup(HTML, dict(case=case(), manifest_sha256='b' * 64), evidence_dir=tmp_path / 'evidence')
    assert not (tmp_path / 'evidence').exists()


@pytest.mark.parametrize('bad_version', [True, 1.0, '1', 2])
def test_manifest_version_must_be_exact(tmp_path, bad_version):
    ref = manifest(tmp_path, [case()], version=bad_version)
    with pytest.raises(recovery.RecoveryInputError):
        recovery.load_manifest(ref)


def test_manifest_identity_duplicates_and_unknown_policy_refuse(tmp_path):
    ref = manifest(tmp_path, [case()])
    with pytest.raises(recovery.RecoveryInputError, match='differs from its pin'):
        recovery.load_manifest(dict(ref, sha256='0' * 64))
    ref = manifest(tmp_path, [case(), case()])
    with pytest.raises(recovery.RecoveryInputError, match='Duplicate'):
        recovery.load_manifest(ref)
    ref = manifest(tmp_path, [dict(case(), policy='silently-trim-binary')])
    with pytest.raises(recovery.RecoveryInputError, match='Unsupported'):
        recovery.load_manifest(ref)


def test_worker_native_append_keeps_old_refusal_and_exact_recovery_keys(tmp_path):
    args, _ = lake(tmp_path, dict(html=(HTML, 'html'), xml=(XML, 'xml')))
    # Keep actual ordinary errors in the same private catalog before the opt-in path.
    first = body_text.run(**args, work=tmp_path / 'ordinary', execute=True)
    assert all(r['reading_status'] == 'error' for r in first['batches'][0]['body_outcomes'])
    planned = body_text.plan(captures=args['captures'], engine=args['engine'], work=tmp_path / 'plan',
                             local_root=args['local_root'], decided_at=STAMP)
    items = pq.read_table(planned['work_list']).to_pylist()
    planned['versions'] = MARKUP_RECOVERY_VERSIONS
    for item in items:
        item['parser_version'] = MARKUP_RECOVERY_VERSIONS[item['parser']]
    ref = manifest(tmp_path, [case(), case(XML, 'xml_text', XML_CANDIDATE, XML_TEXT)])
    staged = body_text.stage(planned, items, engine=args['engine'], work=tmp_path / 'stage', markup_recovery=ref)
    assert staged['body_text_rows'] == staged['readings_rows'] == 2
    assert staged['ocr_pages'] == staged['ocr_pending'] == staged['unreadable'] == staged['pending_reads'] == 0
    body_text.append(staged, engine=args['engine'], work=tmp_path / 'append', catalog_root=args['catalog_root'], tables=args['tables'])
    again = body_text.append(staged, engine=args['engine'], work=tmp_path / 'again', catalog_root=args['catalog_root'], tables=args['tables'])
    assert again['body_text']['files'] == again['readings']['files'] == []
    readings = committed(args, tmp_path / 'readings', 'readings', 'parser,parser_version,status,fields')
    assert len(readings) == 4 and sum(r['status'] == 'error' for r in readings) == 2
    texts = committed(args, tmp_path / 'texts', 'body_text', "parser,parser_version,text,encode(text_sha256,'hex') AS sha,page_offsets,ocr_pages")
    assert {(r['body'], r['parser'], r['parser_version']) for r in texts} == {
        (row['body_sha256'], row['parser'], MARKUP_RECOVERY_VERSIONS[row['parser']])
        for row in [case(), case(XML, 'xml_text', XML_CANDIDATE, XML_TEXT)]}
    assert {r['text'] for r in texts} == {HTML_TEXT, XML_TEXT}
    assert all(r['sha'] == sha256(r['text'].encode()).hexdigest() and r['page_offsets'] == [0] and not r['ocr_pages'] for r in texts)
    # A changed expected output leaves the attempt pending and writes neither table row.
    ref = manifest(tmp_path, [dict(case(), text_sha256='0' * 64)])
    item = next(i for i in items if i['parser'] == 'html_text')
    failed = body_text.stage(planned, [item], engine=args['engine'], work=tmp_path / 'bad-pin', markup_recovery=ref)
    assert failed['readings_rows'] == failed['body_text_rows'] == 0 and failed['pending_reads'] == 1
    assert failed['body_outcomes'][0]['reason'] == 'markup_recovery_input'


def test_stage_rejects_default_versions_before_reading_inputs(tmp_path):
    ref = manifest(tmp_path, [case()])
    with pytest.raises(recovery.RecoveryInputError, match='separate declared'):
        body_text.stage(dict(versions=body_text.current_versions()), [], engine=None, work=tmp_path / 'stage', markup_recovery=ref)
    assert not (tmp_path / 'stage').exists()
    with pytest.raises(ValueError, match='require their pinned recovery manifest'):
        body_text.stage(dict(versions=MARKUP_RECOVERY_VERSIONS), [], engine=None, work=tmp_path / 'no-manifest')
    assert not (tmp_path / 'no-manifest').exists()
