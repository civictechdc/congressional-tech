"""Native audit refinements must prove retained literals, not waive losses."""
from copy import deepcopy

import pytest

from audit_filename_extraction import native_refinement_reason
from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def native_field(name, raw, start):
    return dict(name=name, raw=raw, start=start, end=start + len(raw),
                code=None, label=None, candidates=[], note=None)


def sponsor_case(engine):
    name = 'BILLS-116-HR2474-KOOO395-Amdt-17.pdf'
    return (native_field('suffix', '-KOOO395-Amdt-17', 16),
            deepcopy(engine.extract(name)['observations']))


def hanging_case(engine):
    name = 'bills-118s3679ispdf'
    return deepcopy(engine.extract(name)['observations'])


def test_opaque_suffix_is_preserved_as_specific_literal_fields(engine):
    field, observations = sponsor_case(engine)
    assert native_refinement_reason(field, observations) == 'opaque_suffix_refined'


@pytest.mark.parametrize('attribute,value', [
    ('code', 'old-code'), ('label', 'Existing meaning'),
    ('candidates', ['possible-meaning']), ('context', 'version'),
])
def test_existing_meaning_cannot_be_waived(engine, attribute, value):
    field, observations = sponsor_case(engine)
    field[attribute] = value
    assert native_refinement_reason(field, observations) is None


@pytest.mark.parametrize('removed', [
    'sponsor_identifier_token', 'amendment_marker', 'amendment_token',
])
def test_each_specific_component_is_required(engine, removed):
    field, observations = sponsor_case(engine)
    for match in observations:
        match['fields'] = [f for f in match['fields'] if f['name'] != removed]
    assert native_refinement_reason(field, observations) is None


@pytest.mark.parametrize('replacement', ['K000395', 'KOOO394', 'KOO395'])
def test_changed_or_repaired_source_text_is_not_preservation(engine, replacement):
    field, observations = sponsor_case(engine)
    for match in observations:
        for f in match['fields']:
            if f['name'] == 'sponsor_identifier_token':
                f['raw'] = replacement
    assert native_refinement_reason(field, observations) is None


@pytest.mark.parametrize('opaque_name', ['payload', 'suffix', 'descriptor', 'name_token',
                                        'local_identifier', 'generic_identifier'])
def test_broad_fields_cannot_hide_unparsed_text(engine, opaque_name):
    field, observations = sponsor_case(engine)
    for match in observations:
        for f in match['fields']:
            if f['name'] == 'sponsor_identifier_token':
                f['name'] = opaque_name
    assert native_refinement_reason(field, observations) is None


def test_fallback_assumptions_do_not_establish_specific_components(engine):
    field, observations = sponsor_case(engine)
    for match in observations:
        if match['rule'] == 'unverified-sponsor-amendment':
            match['scope'] = 'unmatched-stem'
    assert native_refinement_reason(field, observations) is None


def test_separator_only_suffix_does_not_pass_empty_coverage(engine):
    assert native_refinement_reason(native_field('suffix', '--', 16),
                                    sponsor_case(engine)[1]) is None


def test_version_and_empty_suffix_refinements_remain_separate(engine):
    observations = hanging_case(engine)
    assert native_refinement_reason(native_field('version_token', 'ispdf', 14), observations) == 'hanging_pdf_separated'
    assert native_refinement_reason(native_field('suffix', '', 19), observations) == 'empty_suffix_boundary_refined'


@pytest.mark.parametrize('change', ['no-version', 'no-pdf', 'uncoded-version', 'wrong-code',
                                   'wrong-context', 'no-label', 'different-pdf', 'gap'])
def test_hanging_split_requires_recognized_adjacent_fields(engine, change):
    observations = hanging_case(engine)
    match = next(m for m in observations if m['rule'] == 'legislative-text')
    fields = {f['name']: f for f in match['fields']}
    if change.startswith('no-') and change != 'no-label':
        key = 'version_token' if change == 'no-version' else 'ignored_suffix'
        match['fields'] = [f for f in match['fields'] if f['name'] != key]
    elif change == 'uncoded-version': fields['version_token']['code'] = None
    elif change == 'wrong-code': fields['version_token']['code'] = 'ih'
    elif change == 'wrong-context': fields['version_token']['context'] = 'measure'
    elif change == 'no-label': fields['version_token']['label'] = None
    elif change == 'different-pdf': fields['ignored_suffix']['raw'] = 'xml'
    elif change == 'gap': fields['ignored_suffix']['start'] += 1
    assert native_refinement_reason(native_field('version_token', 'ispdf', 14), observations) is None
    assert native_refinement_reason(native_field('suffix', '', 19), observations) is None


@pytest.mark.parametrize('field', [
    native_field('suffix', '', 18), native_field('suffix', 'x', 19),
    native_field('version_token', 'ishpdf', 14), native_field('version_token', 'ispdf', 13),
])
def test_other_native_values_and_positions_are_not_waived(engine, field):
    assert native_refinement_reason(field, hanging_case(engine)) is None
