"""Extract visible substitute targets without repairing incomplete source names."""
import gzip
import json

import pytest

from house_naming import Engine
from house_naming.corpus import residual_fields
from house_naming.filename_corpus import build_corpus


SOURCE_NAMES = (
    'BILLS-115-AmendmentinthenatureofasubstitutetoSubtitle__BudgetReconciliationLegislativeRecommendationsRelatingtoRepealandReplaceofHealth-RelatedTa',
    'BILLS-115-AmendmentinthenatureofasubstitutetoSubtitle__BudgetReconciliationLegislativeRecommendationsRelatingtoRepealofCertainConsumerTaxes-B0005',
)


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for match in result['observations']:
        for field in match['fields']:
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
            assert name[field['start']:field['end']] == field['raw']
    return result


def targets(result):
    return [m for m in result['observations'] if m['rule'] == 'substitute-target']


@pytest.mark.parametrize('name', SOURCE_NAMES)
def test_raw_source_truncation_keeps_visible_parts_and_missing_data(engine, name):
    assert len(name) == 145
    result = checked(engine, name)
    assert 'missing-or-unsupported-extension' in result['issues']
    match, = targets(result)
    actual = {f['name']: f['raw'] for f in match['fields']}
    assert actual == {
        'amendment_marker': 'Amendmentinthenatureofasubstitute',
        'target_marker': 'to',
        'target_subject': name[name.index('Subtitle'):],
    }
    assert all(f['code'] is None for f in match['fields'])
    assert not any(m['scope'] == 'legislative-payload' for m in result['observations'])
    assert not any(f['name'] in {'bioguide_token', 'sponsor_identifier_token', 'version_token', 'amendment_identifier', 'extension'}
                   for m in result['observations'] for f in m['fields'])
    outer = next(m for m in result['observations'] if m['rule'] == 'legislative-file')
    assert next(f['raw'] for f in outer['fields'] if f['name'] == 'payload') == name[9:]
    rows = residual_fields(result, field_names={'target_subject'})
    assert [s['raw'] for row in rows for s in row['residual_spans']] == [actual['target_subject']]


@pytest.mark.parametrize('name,expected', [
    ('BILLS-119-ANStoCommitteePrint119-A.pdf', {'label': 'CommitteePrint', 'print_identifier': '119-A'}),
    (' BILLS-119-ANStoCommitteePrint119-A.pdf.pdf ', {'label': 'CommitteePrint', 'print_identifier': '119-A'}),
    ('BILLS-119ANStoHR6498', {'measure_token': 'HR', 'measure_number': '6498'}),
    ('BILLS-119-ANSforHR295.pdf', {'measure_token': 'HR', 'measure_number': '295'}),
    ('BILLS-119-ANStoContemptReport.pdf', {'target_subject': 'ContemptReport'}),
])
def test_shared_rule_keeps_original_offsets_with_or_without_extension(engine, name, expected):
    result = checked(engine, name)
    match, = targets(result)
    actual = {f['name']: f['raw'] for f in match['fields']}
    assert actual.items() >= expected.items()
    assert not any(m['scope'] == 'legislative-payload' for m in result['observations'])


@pytest.mark.parametrize('name', [
    'ANStoCommitteePrint119-A.pdf',
    'BILLS-119--ANStoHR6498.pdf',
    'BILLS-119-ANStoHR123Services.pdf',
    'BILLS-119-ANStone.pdf',
    'BILLS-119-ANSto123.pdf',
    'BILLS-119-Transportation.pdf',
    'BILLS-115s585rfh.xmlhttps:',
    'BILLS-119HR8432ToprovidetheFoodandDrugAdministrationneededauthoritiestocarryoutitsregulatorymissionwithrespecttohumanfoodstoprovideadditionalreso',
])
def test_unrelated_or_unsupported_shapes_are_not_reinterpreted(engine, name):
    assert not targets(checked(engine, name))


def test_complete_sponsor_layout_keeps_one_existing_target_reading(engine):
    name = 'BILLS-119-ANStoHR6498-B000668-Amdt-18.pdf'
    result = checked(engine, name)
    match, = targets(result)
    assert name[match['start']:match['end']] == 'ANStoHR6498'
    assert any(m['rule'] == 'sponsored-amendment' for m in result['observations'])


def test_partial_targets_remain_on_the_incomplete_payload_review_list(tmp_path):
    result = build_corpus(SOURCE_NAMES, tmp_path)
    assert result['filenames_with_unparsed_structured_payload'] == 2
    assert result['structural_collisions'] == 0
    with gzip.open(tmp_path / 'review.jsonl.gz', 'rt') as stream:
        rows = list(map(json.loads, stream))
    assert len(rows) == 2
    assert all(row['unparsed_structured_payload'] for row in rows)
    assert all(any(m['rule'] == 'substitute-target' for m in row['matches']) for row in rows)
