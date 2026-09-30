"""Catalog-only extensions and failures at the configuration boundary."""
from copy import deepcopy

import pytest

from house_naming import Engine, NamingError, check_catalog
from house_naming.extraction import Extractor


@pytest.fixture(scope='module')
def engine():
    return Engine()


def observations(guide, name):
    check_catalog(guide)
    result = Extractor(guide).extract(name)
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for match in result['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
    return result['observations']


def test_catalog_only_alias_and_nested_rule(engine):
    guide = engine.guide
    guide['extraction_vocabularies']['review-alias'] = {
        'wtz': {'label': 'Witness testimony', 'note': 'Literal alias; content is unverified.'}}
    guide['extraction_rules'].extend([
        dict(id='review-container', scope='stem', priority=0,
             pattern=r'CAT_(?P<subject_token>WTZ)', description='Reviewed container.',
             searchable_fields=['subject_token'],
             refine=[dict(field='subject_token', stage='fields', mode='fullmatch', rules=['review-alias'])]),
        dict(id='review-alias', scope='legislative-text-search', priority=0,
             pattern=r'(?P<label>WTZ)', description='Reviewed literal alias.',
             field_vocabularies={'label': [{'vocabulary': 'review-alias'}]}),
    ])
    matches = observations(guide, 'CAT_WTZ.pdf')
    field = next(m for m in matches if m['rule'] == 'review-alias')['fields'][0]
    assert (field['raw'], field['start'], field['end']) == ('WTZ', 4, 7)
    assert field['label'] == 'Witness testimony'
    assert field['note'] == 'Literal alias; content is unverified.'
    assert field['code'] is None
    assert not any(m['rule'] == 'review-alias' for m in observations(guide, 'unrelated_WTZ.pdf'))


def test_catalog_search_order_preserves_numeric_reference(engine):
    guide = engine.guide
    guide['extraction_rules'].append(dict(
        id='review-reference', scope='search', priority=0, scan_order=0, reserve='match',
        pattern=r'ZX(?P<document_identifier>111111)', description='Reviewed numeric identifier.'))
    matches = observations(guide, 'ZX111111.pdf')
    assert any(m['rule'] == 'review-reference' for m in matches)
    assert not any(f['name'] in {'date_token', 'short_date_token'} for m in matches for f in m['fields'])


def test_note_only_reading_is_supported(engine):
    guide = engine.guide
    guide['extraction_rules'].append(dict(
        id='review-note', scope='stem', priority=0, pattern=r'(?P<literal>ZZNOTE)',
        description='An unclassified source token.', field_readings={'literal': {'note': 'Retain this wording.'}}))
    field = next(m for m in observations(guide, 'ZZNOTE.pdf') if m['rule'] == 'review-note')['fields'][0]
    assert field['note'] == 'Retain this wording.'
    assert field['label'] is None and field['code'] is None


def test_field_reading_overrides_the_shorthand_label(engine):
    guide = engine.guide
    guide['extraction_rules'].append(dict(
        id='review-label', scope='stem', priority=0, pattern=r'(?P<label>ZZLABEL)',
        description='Default description.', label='Default label.',
        field_readings={'label': {'label': 'Specific label.', 'note': 'Specific qualification.'}}))
    field = next(m for m in observations(guide, 'ZZLABEL.pdf') if m['rule'] == 'review-label')['fields'][0]
    assert (field['label'], field['note']) == ('Specific label.', 'Specific qualification.')


@pytest.mark.parametrize('marker,code,label', [
    ('HRPT', 'hrpt', 'House report citation'),
    ('H.Rept.', 'hrpt', 'House report citation'),
    ('SRPT', 'srpt', 'Senate report citation'),
    ('S Rept', 'srpt', 'Senate report citation'),
])
def test_printed_report_citation_aliases_keep_their_meaning(engine, marker, code, label):
    result = engine.extract(f'{marker}115-409.pdf')
    fields = [f for m in (*result['observations'], *result['suppressed']) for f in m['fields']]
    field = next(f for f in fields if f['name'] == 'citation_marker')
    assert (field['raw'], field['code'], field['label']) == (marker.rstrip('.'), code, label)


def test_generated_support_text_remains_searchable(engine):
    result = engine.extract('Smith in support of fiscal year 2026.pdf')
    assert any(m['rule'] == 'support-reference' for m in result['observations'])
    field = next(f for m in result['observations'] if m['rule'] == 'written-fiscal-year'
                 for f in m['fields'] if f['name'] == 'fiscal_year_token')
    assert field['raw'] == '2026'
    assert field['note'] == 'Printed fiscal year; no calendar date is established.'


def test_overlapping_refinement_scopes_keep_catalog_order(engine):
    name = 'BILLS-113HR-SC-AP-FY2014-Agriculture-SubcommitteeDraft.pdf'
    rules = [m['rule'] for m in engine.extract(name)['observations']]
    assert rules.index('appropriation-subject') < rules.index('draft-wording')
    assert rules.count('draft-wording') == 1


@pytest.mark.parametrize('damage', [
    'processor', 'reading-capture', 'lookup-capture', 'lookup-vocabulary', 'house-reference',
    'capture-rule', 'refine-rule', 'refine-mode', 'refine-stage', 'refine-capture',
    'self-cycle', 'capture-cycle', 'indirect-cycle', 'unselected-child',
])
def test_invalid_catalog_fails_before_any_filename(engine, damage):
    guide = engine.guide
    parent = dict(id='review-parent', scope='stem', priority=0,
                  pattern=r'(?P<subject_token>ZZ)', description='Parent.')
    child = dict(id='review-child', scope='legislative-text-search', priority=0,
                 pattern=r'(?P<label>ZZ)', description='Child.')
    guide['extraction_rules'].extend([parent, child])
    route = dict(field='subject_token', stage='fields', mode='search', rules=['review-child'])
    parent['refine'] = [route]
    if damage == 'processor':
        parent['processors'] = ['run-arbitrary-code']
    elif damage == 'reading-capture':
        parent['field_readings'] = {'absent': {'note': 'Not captured.'}}
    elif damage == 'lookup-capture':
        parent['field_vocabularies'] = {'subject_token': [{'vocabulary': 'publication', 'from': 'absent'}]}
    elif damage == 'lookup-vocabulary':
        parent['field_vocabularies'] = {'subject_token': [{'vocabulary': 'missing'}]}
    elif damage == 'house-reference':
        parent['field_readings'] = {'subject_token': {'house_context': 'measure', 'house_token': 'not-a-measure'}}
    elif damage == 'capture-rule':
        parent['capture_rules'] = {'subject_token': ['absent']}
    elif damage == 'refine-rule':
        route['rules'] = ['absent']
    elif damage == 'refine-mode':
        route['mode'] = 'evaluate'
    elif damage == 'refine-stage':
        route['stage'] = 'unimplemented'
    elif damage == 'refine-capture':
        route['field'] = 'absent'
    elif damage == 'self-cycle':
        route['rules'] = ['review-parent']
    elif damage == 'capture-cycle':
        parent['capture_rules'] = {'subject_token': ['review-parent']}
    elif damage == 'indirect-cycle':
        child['refine'] = [dict(field='label', stage='fields', mode='search', rules=['review-parent'])]
    elif damage == 'unselected-child':
        route['search_rules'] = ['measure-reference']
    for validate in (check_catalog, Extractor):
        with pytest.raises(NamingError) as error:
            validate(guide)
        assert error.value.code == 'invalid-catalog'


def test_rule_ids_are_not_dispatch_instructions(engine):
    guide = engine.guide
    original = Extractor(deepcopy(guide))
    renamed = {r['id']: 'review-' + r['id'] for r in guide['extraction_rules']}
    for rule in guide['extraction_rules']:
        rule['id'] = renamed[rule['id']]
        for route in rule.get('refine', ()):
            for key in ('rules', 'search_rules'):
                if key in route:
                    route[key] = [renamed[value] for value in route[key]]
            if 'trim_for' in route:
                route['trim_for'] = {renamed[key]: value for key, value in route['trim_for'].items()}
        for field, children in rule.get('capture_rules', {}).items():
            rule['capture_rules'][field] = [renamed[value] for value in children]
    guide['extraction_roles'] = {key: renamed[value] for key, value in guide['extraction_roles'].items()}
    check_catalog(guide)
    reader = Extractor(guide)

    def normalize(value):
        if isinstance(value, dict):
            return {key: item.replace('review-', '') if key == 'rule' else normalize(item)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    for name in (
        'BILLS-119hr1ih.pdf', 'CHRG-107shrg83924-err2.pdf', 'HR111111.pdf',
        'H.R. 12345.pdf', 'BILLS-119ANSServices.pdf', 'HRPT-112-HR123-p2.pdf',
        'Smith Testimony 03-27-19.pdf', 'Smith in support of HR1.pdf',
        'S.123 Reported.pdf', 'RCP118-5_HR1_HR2.pdf', 'First Degree 2.pdf',
        'BILLS-119HR1_HAmdt2.pdf', 'S.Hrg.119-12345.pdf', '03-2020-Smith.pdf',
        'CRPT-119hrpt12.pdf', 'CPRT-119hprt12345.pdf',
    ):
        assert normalize(reader.extract(name)) == original.extract(name), name
