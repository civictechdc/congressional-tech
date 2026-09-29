"""Real residual filenames, plus negative controls for literal-only extraction."""
import gzip
import json

import pytest

from congress_api.filename_corpus import build_corpus, residual_fields
from congress_api.filenames import RULES, parse_filename


@pytest.mark.parametrize(('name', 'rule', 'expected'), [
    ('BILLS-113hrFARMEXT-SUS.pdf', 'joined-title-local-code',
     {'measure_token': 'hr', 'descriptor': 'FARMEXT', 'local_code_token': 'SUS'}),
    ('BILLS-115HR__-RCP115-77.pdf', 'placeholder-print-reference',
     {'measure_token': 'HR', 'number_placeholder': '__', 'print_congress': '115', 'print_number': '77'}),
    ('BILLS-115HR__-RCP115-77.xml', 'placeholder-print-reference',
     {'measure_token': 'HR', 'number_placeholder': '__', 'print_congress': '115', 'print_number': '77'}),
    ('BILLS-118 HRES_HR277HR288HR1615HR1640.pdf', 'resolution-measure-list',
     {'measure_token': 'HRES', 'measure_list': 'HR277HR288HR1615HR1640'}),
    ('BILLS-118 hres_44HR277HR288HR1615HR1640_xml.pdf', 'resolution-measure-list',
     {'measure_token': 'hres', 'measure_number': '44', 'measure_list': 'HR277HR288HR1615HR1640', 'filename_format_token': 'xml'}),
    ('BILLS-118 hres_HR1435_xml.pdf', 'resolution-measure-list',
     {'measure_token': 'hres', 'measure_list': 'HR1435', 'filename_format_token': 'xml'}),
    ('BILLS-118 hres_HR2670_2_xml.pdf', 'resolution-measure-list',
     {'measure_token': 'hres', 'measure_list': 'HR2670', 'numeric_suffix_token': '2', 'filename_format_token': 'xml'}),
    ('BILLS-118 hres_HR2HR1163_xml.pdf', 'resolution-measure-list',
     {'measure_token': 'hres', 'measure_list': 'HR2HR1163', 'filename_format_token': 'xml'}),
    ('BILLS-118 hres_HR3564HR3799HRes461_xml.pdf', 'resolution-measure-list',
     {'measure_token': 'hres', 'measure_list': 'HR3564HR3799HRes461', 'filename_format_token': 'xml'}),
])
def test_remaining_nine_have_single_layout_and_exact_fields(name, rule, expected):
    parsed = parse_filename(name)
    inner_ids = {r.id for r in RULES if r.scope == 'legislative-payload'}
    inner = [m for m in parsed.matches if m.rule in inner_ids]
    assert [m.rule for m in inner] == [rule]
    fields = {f.name: f.raw for f in inner[0].fields}
    assert fields.items() >= expected.items()
    if 'measure_number' not in expected:
        assert 'measure_number' not in fields
    for match in parsed.matches:
        for field in match.fields:
            assert name[field.start:field.end] == field.raw
    assert ''.join(p.raw for p in parsed.pieces) == name


def test_combined_resolution_keeps_all_individual_references():
    parsed = parse_filename('BILLS-118 hres_44HR3564HR3799HRes461_xml.pdf')
    refs = [{f.name: f.raw for f in m.fields} for m in parsed.matches if m.rule == 'measure-reference']
    assert [(r['measure_token'], r['measure_number']) for r in refs] == [
        ('hres', '44'), ('HR', '3564'), ('HR', '3799'), ('HRes', '461')]


def test_local_markers_are_not_versions_or_content_format():
    parsed = parse_filename('BILLS-118 hres_HR2670_2_xml.pdf')
    fields = [f for m in parsed.matches for f in m.fields]
    assert [f.raw for f in fields if f.name == 'extension'] == ['pdf']
    assert not any(f.name in {'version_token', 'version_number_token', 'part_number', 'amendment_token'} for f in fields)
    assert all(f.label is None for f in fields if f.name in {'numeric_suffix_token', 'filename_format_token'})
    parsed = parse_filename('BILLS-113hrFARMEXT-SUS.pdf')
    assert not any(f.name == 'version_token' for m in parsed.matches for f in m.fields)
    assert next(f for m in parsed.matches for f in m.fields if f.name == 'local_code_token').label is None


@pytest.mark.parametrize(('payload', 'rule'), [
    (' sres_9S21HJRES8_3_xml', 'resolution-measure-list'),
    ('SXX-RCP119-8', 'placeholder-print-reference'),
    ('hjresLOCAL99-ABC', 'joined-title-local-code'),
])
def test_rules_generalize_beyond_the_observed_nine(payload, rule):
    assert any(m.rule == rule for m in parse_filename(f'BILLS-119{payload}.pdf').matches)


@pytest.mark.parametrize('payload', [
    'hres_HR', 'hres_44', 'hres_44HR1oops', 'hres_HR1_2_xml_more',
    'HR__-RCP-77', 'HR__-RCP115-X', 'HR__-RCP115-77junk',
    'hrFarmExt-SUS', 'HRFARMEXT-SUS', 'Services-SUS',
])
def test_new_layouts_reject_incomplete_or_ambiguous_boundaries(payload):
    new = {'resolution-measure-list', 'placeholder-print-reference', 'joined-title-local-code'}
    assert not new.intersection(m.rule for m in parse_filename(f'BILLS-119{payload}.pdf').matches)


@pytest.mark.parametrize(('payload', 'expected'), [
    ('hrPIH-AHCA', 'PIH'), ('hrIH-LOCAL', 'IH'), ('sIS-LOCAL', 'IS'), ('hresES-LOCAL', 'ES'),
])
def test_joined_title_does_not_reinterpret_an_existing_version(payload, expected):
    parsed = parse_filename(f'BILLS-119{payload}.pdf')
    assert 'joined-title-local-code' not in {m.rule for m in parsed.matches}
    versions = [f.raw for m in parsed.matches for f in m.fields if f.name == 'version_token']
    assert versions == [expected]


def test_residual_audit_subtracts_overlapping_specific_fields_but_not_wrappers():
    # The enclosing payload and suffix contain the whole string; the search
    # rules already recover a print, part and revision, with overlapping spans.
    parsed = parse_filename('BILLS-119HR1-RCP119-2-Part1-U3-FreeText.pdf')
    row, = residual_fields(parsed)
    assert [s['raw'] for s in row['residual_spans']] == ['FreeText']
    for span in row['residual_spans']:
        assert parsed.filename[span['start']:span['end']] == span['raw']


def test_residual_audit_preserves_text_on_both_sides_of_a_capture():
    parsed = parse_filename('BILLS-119pih-Title-U3-MoreText.pdf')
    row, = residual_fields(parsed)
    assert [s['raw'] for s in row['residual_spans']] == ['Title', 'MoreText']


def test_reference_assisted_title_is_still_free_text_in_the_audit():
    parsed = parse_filename('BILLS-119HR2RepClyburnFreeTextih.pdf', member_surnames={'119': ('Clyburn',)})
    row, = residual_fields(parsed)
    assert [s['raw'] for s in row['residual_spans']] == ['FreeText']


def test_residual_audit_reports_titles_separately_from_already_extracted_suffixes(tmp_path):
    names = ['BILLS-119pih-FreeText1-U2.pdf', 'BILLS-119pih-FreeText2-U3.xml',
             'HHRG-119-AG00-Wstate-Smith-20260101-U1.pdf', 'CHRG-119hhrg1234.pdf']
    summary = build_corpus(names, tmp_path)
    assert summary['residual_text_audit'] == {
        'opaque_fields_audited': 3, 'fields_with_residual_text': 2,
        'filenames_with_opaque_fields': 3, 'filenames_with_residual_text': 2}
    rows = list(map(json.loads, gzip.open(tmp_path / 'residual-fields.jsonl.gz', 'rt')))
    known = next(r for r in rows if r['filename'].startswith('HHRG'))
    assert known['fields'][0]['residual_spans'] == []
    patterns = list(map(json.loads, gzip.open(tmp_path / 'residual-patterns.jsonl.gz', 'rt')))
    assert len(patterns) == 1
    assert patterns[0]['shape'] == 'freetext<number>'
    assert patterns[0]['filenames'] == 2
    assert json.loads((tmp_path / 'residual-summary.json').read_text())['recurring_residual_shapes'] == 1
