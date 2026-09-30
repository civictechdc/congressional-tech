"""Regression cases from the combined review, including real command failures."""
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from house_naming import filenames
from house_naming.filename_corpus import OTHER_TEXT_FIELDS, build_corpus, residual_fields


@pytest.mark.parametrize('payload', ['ANSServices', 'AINSServices', 'ANSEarth', 'ANSCats',
                                    'HR1Services', 'HR1Earth', 'HR1Cats', 'HR1Areas'])
def test_word_endings_have_no_official_version_label(payload):
    parsed = filenames.parse_filename(f'BILLS-119{payload}.pdf')
    versions = [f for m in parsed.matches for f in m.fields if f.name == 'version_token']
    assert versions
    assert all(f.code is None and f.label is None and f.vocabulary_url is None and f.candidates for f in versions)
    word = next(word for word in ('Services', 'Earth', 'Cats', 'Areas') if payload.endswith(word))
    assert any(f.name == 'descriptor' and f.raw == word for m in parsed.matches for f in m.fields)
    assert any(s['raw'] == word for row in residual_fields(parsed) for s in row['residual_spans'])


@pytest.mark.parametrize(('payload', 'version'), [('ANSih', 'ih'), ('ANStoHR1988ih', 'ih'),
    ('ANSServices-ES', 'ES'), ('ANStoHR1988es', 'es'), ('HR1Services-es', 'es'),
    ('SubtitleArth', 'rth'), ('HR1Actih', 'ih'), ('HR1RPTrh', 'rh')])
def test_explicit_version_positions_remain_usable(payload, version):
    parsed = filenames.parse_filename(f'BILLS-119{payload}.pdf')
    field, = [f for m in parsed.matches for f in m.fields if f.name == 'version_token']
    assert field.raw == version
    assert field.code == version.lower() and field.label


def test_separated_version_and_joined_house_stage_remain_whole():
    for payload, code, candidates in [('HR1Title-eas', 'eas', ('eas',)), ('HR1Titlepih', 'pih', ('pih',))]:
        parsed = filenames.parse_filename(f'BILLS-119{payload}.pdf')
        field, = [f for m in parsed.matches for f in m.fields if f.name == 'version_token']
        assert field.raw == code
        assert field.code == code and field.candidates == candidates


@pytest.mark.parametrize(('name', 'number'), [
    ('BILLS-112hr-PIH-description.pdf', None),
    ('BILLS-112hres-PIH-electing-sgt-at-arms.xml', None),
    ('BILLS-115hres5-PIH-FINAL.pdf', '5'),
    ('BILLS-119pih-NutritionEducationandChronicDiseasePreventioninCommunityHealthCentersActof2026.pdf', None),
    ('BILLS-119HR42Pih.pdf', '42'),
])
def test_documented_house_pih_stage_has_its_own_source(name, number):
    from house_naming.bill_codes import BILL_VERSIONS
    from house_naming.naming import HOUSE_NAMING_URL
    assert 'pih' not in BILL_VERSIONS  # Not part of GovInfo's common-version table.
    parsed = filenames.parse_filename(name)
    version, = [f for m in parsed.matches for f in m.fields if f.name == 'version_token']
    assert version.code == 'pih' and version.label == 'Pre-introduced measure; no bill number'
    assert version.vocabulary_url == HOUSE_NAMING_URL + "#page=6"
    assert name[version.start:version.end] == version.raw
    numbers = {f.raw for m in parsed.matches for f in m.fields if f.name == 'measure_number'}
    assert numbers == ({number} if number else set())


def test_mixed_case_joined_pih_keeps_both_possible_boundaries():
    parsed = filenames.parse_filename('BILLS-117OAWPih.pdf')
    original, = [m for m in parsed.matches if m.rule == 'titled-introduced-draft']
    fields = {f.name: f for f in original.fields}
    assert fields['descriptor'].raw == 'OAWPih'
    assert fields['version_token'].raw == 'Pih'
    assert fields['version_token'].candidates == ('ih', 'pih')
    assert fields['version_token'].code is None and fields['version_token'].label is None
    # Repeated field names are separate observations, not last-value-wins data.
    local, = [m for m in parsed.matches if m.rule == 'local-introduction-component']
    local_fields = {f.name: f for f in local.fields}
    assert local_fields['local_identifier'].raw == 'OAWP'
    assert local_fields['local_identifier'].code is None
    assert local_fields['version_token'].raw == local_fields['version_token'].code == 'ih'
    assert local_fields['version_token'].label == 'Introduced in House'


@pytest.mark.parametrize('name', ['Biography-PIH.pdf', 'BILLS-119hr5-PiHome.pdf', 'BILLS-119hr5-Topih-final.pdf'])
def test_house_stage_search_requires_legislative_scope_and_separators(name):
    assert not any(m.rule == 'house-stage-marker' for m in filenames.parse_filename(name).matches)


@pytest.mark.parametrize(('name', 'expected'), [
    ('BILLS-115HR1695-RCP115- 13.pdf', {'print_congress': '115', 'print_number': '13'}),
    ('CHRG-114shrg52542-add1.pdf', {'publication_marker': 'add', 'publication_identifier': '1'}),
    ('CHRG-106hhrg59318-err.htm', {'publication_marker': 'err'}),
    ('CHRG-107shrg87708-volII.pdf', {'publication_marker': 'vol', 'publication_identifier': 'II'}),
    ('CHRG-110hhrg45731-ptb.htm', {'publication_marker': 'pt', 'publication_identifier': 'b'}),
    ('CHRG-109hhrg26292v1.pdf', {'publication_marker': 'v', 'publication_identifier': '1'}),
    ('Testimony-Brian-2020-07-28-REVISED3.pdf', {'revision_marker': 'REVISED', 'revision_number': '3'}),
    ('Opening Statement-Peters-2019-09-25.REVISED.pdf.pdf', {'revision_marker': 'REVISED'}),
    ('BILLS-115HR10-HAmdt.pdf', {'amendment_marker': 'HAmdt'}),
    ('BILLS-113hjres59-HAmdt2a.xml', {'amendment_marker': 'HAmdt', 'amendment_token': '2a'}),
    ('BILLS-118340ANSih-U2.pdf', {'amendment_marker': 'ANS'}),
    ('BILLS-113-HR1256rh-FS_xml.pdf', {'filename_format_token': 'xml', 'extension': 'pdf'}),
])
def test_reviewed_literal_markers_have_exact_spans(name, expected):
    parsed = filenames.parse_filename(name)
    fields = [f for m in parsed.matches for f in m.fields]
    assert {f.name: f.raw for f in fields}.items() >= expected.items()
    for field in fields:
        assert name[field.start:field.end] == field.raw


@pytest.mark.parametrize('name', ['BILLS-119pih-add1.pdf', 'Biography-Services-volII.pdf',
                                    'CHRG-119shrg11111-error.pdf', 'CHRG-119shrg11111-volumeTwo.pdf',
                                    'BILLS-119pih-TRANSition.pdf', 'unrevised3.pdf'])
def test_markers_require_their_scope_and_word_boundaries(name):
    assert not {'publication-suffix-marker', 'legislative-amendment-marker', 'revised-token'}.intersection(
        m.rule for m in filenames.parse_filename(name).matches)


def test_member_suffix_uses_supplied_names_and_preserves_the_original_suffix():
    name = 'BILLS-118HR6273-RepMoylanih.pdf'
    without = filenames.parse_filename(name)
    with_reference = filenames.parse_filename(name, member_surnames={'118': ('Moylan',)})
    assert not any(f.name == 'member_surname_token' for m in without.matches for f in m.fields)
    fields = {f.name: f.raw for m in with_reference.matches for f in m.fields}
    assert fields.items() >= {'suffix': '-RepMoylanih', 'member_surname_token': 'Moylan', 'version_token': 'ih'}.items()
    assert 'title_token' not in fields


def test_other_text_audit_covers_unhandled_payloads_and_unstructured_stems(tmp_path):
    names = ['HRPT-119-HRtaxex.pdf', 'AMNT-119-LocalAmendment.pdf', 'AName-20261340.pdf',
             'HHRG-119-AG00-Wstate-Smith-20260101.pdf', 'BILLS-119HR1Services.pdf']
    build_corpus(names, tmp_path)
    rows = list(map(json.loads, gzip.open(tmp_path / 'other-text-fields.jsonl.gz', 'rt')))
    fields = {(r['filename'], f['field']['name']): f for r in rows for f in r['fields']}
    assert ('HRPT-119-HRtaxex.pdf', 'payload') in fields
    assert ('AMNT-119-LocalAmendment.pdf', 'payload') in fields
    assert ('AName-20261340.pdf', 'unstructured_stem') in fields
    assert (names[3], 'subject_token') in fields
    assert (names[3], 'payload') not in fields  # Already has a complete inner layout.
    captures = json.loads((tmp_path / 'capture-review.json').read_text())
    assert any(r['field'] == 'version_token' and r['status'] == 'uncertain' and r['value'] == 'es' for r in captures)
    # An invalid date-shaped number remains inspectable as a rejected candidate.
    review = list(map(json.loads, gzip.open(tmp_path / 'review.jsonl.gz', 'rt')))
    assert any(s['raw'] == '20261340' and s['reason'] == 'No valid supported calendar reading.'
               for row in review for s in row['suppressed'])


def test_plain_amendment_ids_are_already_literal_syntax():
    parsed = filenames.parse_filename('BILLS-119-HR1-S000123-Amdt-12a.pdf')
    rows = residual_fields(parsed, field_names=OTHER_TEXT_FIELDS)
    assert not any(row['field']['name'] == 'amendment_token' for row in rows)


@pytest.fixture
def command_inputs(tmp_path):
    baseline = tmp_path / 'baseline'
    baseline.mkdir()
    for name in ('filenames.py', 'bill_codes.py', 'naming.py'):
        shutil.copy2(Path(filenames.__file__).parent / name, baseline / name)
    import house_naming
    shutil.copytree(Path(house_naming.__file__).parent, baseline / 'house_naming',
                    ignore=shutil.ignore_patterns('__pycache__'))
    (baseline / 'baseline-remaining-legislative-payloads.json').write_text('[]')
    inventory = tmp_path / 'inventory.parquet'
    pq.write_table(pa.Table.from_pylist([{'filename': 'BILLS-119hr1ih.pdf', 'variants': []}]), inventory)
    ref = tmp_path / 'members.json'
    ref.write_text('[]')
    return baseline, inventory, ref


def run_comparison(inputs, trial, *extra):
    baseline, inventory, ref = inputs
    return subprocess.run([sys.executable, 'tests/compare_filename_families.py', trial, '--root', str(baseline),
        '--inventory', str(inventory), '--legislators', str(ref), '--minimum-useful', '0', *extra], capture_output=True, text=True)


def test_comparison_command_exit_status_and_frozen_vocabulary(command_inputs):
    baseline, _, _ = command_inputs
    passed = run_comparison(command_inputs, 'passing')
    assert passed.returncode == 0, passed.stderr
    vocabulary = baseline / 'house_naming/data/guide.json'
    guide = json.loads(vocabulary.read_text())
    guide['codes']['version']['ih']['label'] = 'Frozen baseline label'
    vocabulary.write_text(json.dumps(guide))
    failed = run_comparison(command_inputs, 'failing')
    assert failed.returncode == 1, failed.stderr
    report = json.loads((baseline / 'failing/comparison.json').read_text())
    assert not report['mechanical_gate'] and report['problems']
    assert report['changed_during_run'] == []
    expected = baseline / 'reviewed-changes.json'
    expected.write_text((baseline / 'failing/changes.json').read_text())
    reviewed = run_comparison(command_inputs, 'reviewed', '--expected-changes', str(expected))
    assert reviewed.returncode == 0, reviewed.stderr
    wrong = json.loads(expected.read_text())
    wrong['BILLS-119hr1ih.pdf']['after_sha256'] = 'not-the-reviewed-output'
    expected.write_text(json.dumps(wrong))
    rejected = run_comparison(command_inputs, 'stale-review', '--expected-changes', str(expected))
    assert rejected.returncode == 1, rejected.stderr
    report = json.loads((baseline / 'stale-review/comparison.json').read_text())
    assert any('stale_expected_change' in p for p in report['problems'])


@pytest.mark.parametrize('failure', ['none', 'collision', 'changed_input'])
def test_corpus_command_fails_collisions_and_input_changes(command_inputs, tmp_path, failure):
    _, inventory, ref = command_inputs
    ref.write_text('{}')
    out = tmp_path / failure
    script = '''import sys, re
from pathlib import Path
from house_naming import filenames as f, filename_corpus as c
mode = sys.argv.pop(1)
if mode == 'collision':
    from house_naming.extraction import Extractor
    guide = f.HOUSE_NAMING.guide
    guide['extraction_rules'].append(dict(id='duplicate-bills', pattern=r'(?P<payload>BILLS-.+)',
        scope='stem', description='Test collision', priority=0))
    f.HOUSE_NAMING._extractor = Extractor(guide)
if mode == 'changed_input':
    original = c.build_corpus
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(sys.argv[-1]).write_text('[]\\n')
        return result
    c.build_corpus = changed
raise SystemExit(c.main())
'''
    result = subprocess.run([sys.executable, '-c', script, failure, str(inventory), str(out),
                             '--member-surnames', str(ref)], text=True, capture_output=True)
    assert result.returncode == (0 if failure == 'none' else 1), result.stderr
    report = json.loads((out / 'coverage.json').read_text())
    assert report['mechanical_gate'] == (failure == 'none')
    if failure == 'collision':
        assert report['structural_collisions'] == 1
    if failure == 'changed_input':
        assert report['changed_during_run'] == [str(ref)]


def test_comparison_freezes_the_house_catalog(command_inputs):
    baseline, inventory, _ = command_inputs
    pq.write_table(pa.Table.from_pylist([{'filename': 'BILLS-119hr1-SUS.pdf', 'variants': []}]), inventory)
    guide = baseline / 'house_naming/data/guide.json'
    value = json.loads(guide.read_text())
    value['codes']['consideration']['sus']['label'] = 'Frozen source label'
    guide.write_text(json.dumps(value))
    failed = run_comparison(command_inputs, 'frozen-house')
    assert failed.returncode == 1, failed.stderr
    report = json.loads((baseline / 'frozen-house/comparison.json').read_text())
    assert report['counts']['changed_outputs'] == 1
    assert any('house_naming/data/guide.json' in path for path in report['hashes'])
    assert report['changed_during_run'] == []


def test_comparison_requires_the_baseline_dependency(command_inputs):
    baseline, _, _ = command_inputs
    (baseline / 'house_naming/naming.py').unlink()
    failed = run_comparison(command_inputs, 'missing-dependency')
    assert failed.returncode != 0
    assert 'requires frozen naming.py' in failed.stderr
