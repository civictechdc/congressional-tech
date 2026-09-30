"""Source meanings, ambiguous prefixes and number roles in literal extraction."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def fields(engine, filename, name):
    result = engine.extract(filename)
    assert all(result[k] == v for k, v in engine.parse(filename).items())
    for observation in result['observations']:
        for field in observation['fields']:
            assert filename[field['start']:field['end']] == field['raw']
            if field['context']:
                assert engine.lookup(field['context'], field['code']) is not None
    return [f for m in result['observations'] for f in m['fields'] if f['name'] == name]


@pytest.mark.parametrize('filename,code', [
    ('BILLS-119hr12ih.pdf', 'bills'),
    ('CHRG-106hhrg53880', 'chrg'),
    ('CRPT-112hrpt2.pdf', 'crpt'),
    ('CRPT-112hrpt-HR2055-SOM.pdf', 'crpt'),
    ('CPRT-112hprt12345.pdf', 'cprt'),
    ('CPRT-112-HPRT-AG00-123.pdf', 'cprt'),
    ('CPRT-112hrpt-activities-Q1-RU.pdf', 'cprt'),
])
def test_publication_prefix_links_to_its_source_definition(engine, filename, code):
    field = fields(engine, filename, 'package_family')[0]
    assert (field['code'], field['context']) == (code, 'collection')
    entry = engine.lookup('collection', code)
    assert field['label'] == entry['label'] and entry['sources']


@pytest.mark.parametrize('filename', [
    'CRPT-112-AG00-Vote001-20111205.pdf',
    'CRPT-112-HMTG-AG00-Vote001-20111205.pdf',
    'HMTG-112-AG-Weekof20111205.pdf',
    'HMTG-112-HHRG-AG00-20111205.pdf',
])
def test_routing_prefix_is_not_a_publication_or_meeting_classification(engine, filename):
    field = fields(engine, filename, 'package_family')[0]
    assert field['context'] is None and field['code'] is None


@pytest.mark.parametrize('filename', [
    'BILLS-119-HR12-B000123-Amdt-1.pdf',
    'BILLS-119-OversightPlan-B00012X-Amdt-1.pdf',
    'BILLS-119-HR12-000123-Amdt-1.pdf',
])
def test_explicit_committee_amendment_has_its_convention_meaning(engine, filename):
    field = next(f for f in fields(engine, filename, 'amendment_marker') if f['context'])
    assert field['code'] == 'amdt' and field['context'] == 'amendment'
    assert field['label'] == 'Amendment considered in committee'


@pytest.mark.parametrize('filename', ['Amendment-1.pdf', 'BILLS-119HR12-ANS1.pdf'])
def test_generic_amendment_wording_does_not_prove_committee_consideration(engine, filename):
    assert all(f['code'] is None for f in fields(engine, filename, 'amendment_marker'))


@pytest.mark.parametrize('marker,chamber', [('HAmdt', 'House'), ('SAmdt', 'Senate')])
@pytest.mark.parametrize('suffix,degree', [('', 'first'), ('2', 'second'), ('3', 'third')])
def test_interchamber_degree_label_preserves_raw_catalog_entry(engine, marker, chamber, suffix, degree):
    field = fields(engine, f'BILLS-112hr2847ih-{marker}{suffix}.pdf', 'amendment_marker')[0]
    assert field['label'] == f'{chamber} amendment ({degree} degree)'
    assert field['raw'] == marker and field['code'] == (marker + suffix).lower()
    assert engine.lookup(field['context'], field['code'])['label'] == marker + suffix


def test_other_amendment_numbers_are_not_degrees(engine):
    field = fields(engine, 'BILLS-112hr2847ih-HAmdt002.pdf', 'amendment_marker')[0]
    assert field['code'] is None and field['label'] is None


def test_orh_requires_the_right_filename_slot(engine):
    bare = fields(engine, 'BILLS-119hrTITLE-ORH.pdf', 'local_code_token')[0]
    assert bare['raw'] == 'ORH' and bare['code'] is None
    rules = fields(engine, 'BILLS-112HRes-ORH-Rule-HR10.pdf', 'local_code_token')[0]
    assert rules['context'] == 'consideration' and rules['code'] == 'orh-rule-legis-num'
    appropriation = fields(engine, 'BILLS-112HR-ORH-AP-FY13-Agriculture.pdf', 'scope_token')[0]
    assert appropriation['context'] == 'appropriation' and appropriation['code'] == 'orh'


@pytest.mark.parametrize('filename,name,code,label,context', [
    ('BILLS-112HR12ih-U1.pdf', 'revision_marker', 'u', 'Document update', 'revision'),
    ('CRPT-112hrpt-HR2055-SOM.pdf', 'report_component', 'som', 'Joint statement of managers', 'report'),
    ('CRPT-112hrpt-HR2055-frontmatter.pdf', 'report_component', 'frontmatter', 'Report front matter', 'report'),
    ('CRPT-112hrpt-HR2055-signaturesheets.pdf', 'report_component', 'signaturesheets', 'Report signature sheets', 'report'),
    ('CRPT-112hrpt-HR2055-DivisonA.pdf', 'division_marker', 'divison', 'Report division', 'report'),
    ('CRPT-112hrpt-HR2055-DivisionA.pdf', 'division_marker', 'division', 'Report division', None),
])
def test_interpreted_labels_link_only_to_existing_catalog_codes(engine, filename, name, code, label, context):
    field = fields(engine, filename, name)[0]
    assert (field['code'], field['label'], field['context']) == (code, label, context)


@pytest.mark.parametrize('filename,name,note', [
    ('HRPT-112-HR123-p2.pdf', 'part_number', 'Part of the report; not the report number.'),
    ('BILLS-112HRes-ORH-Rule-HR10.pdf', 'covered_measure_number', 'Number of the measure covered by the Rules resolution; not the resolution number.'),
    ('BILLS-112HR-ORH-AP-FY13-suppl-01.pdf', 'appropriation_sequence', 'Sequence within the stated fiscal year; not a bill number.'),
    ('BILLS-112-HR2608-R000395-Amdt-001-Enbloc-002.pdf', 'enbloc_number', 'Printed en bloc group number; not the individual amendment identifier.'),
    ('HMTG-112-HHRG-AG00-20111205-2.pdf', 'meeting_sequence', 'Distinguishes meetings of this committee on the same date.'),
    ('CPRT-112hrpt-activities-Q1-RU.pdf', 'quarter_number', 'Quarter of the committee activity report.'),
])
def test_number_role_is_explicit(engine, filename, name, note):
    assert fields(engine, filename, name)[0]['note'] == note


@pytest.mark.parametrize('raw,candidates,warning', [
    ('20111205', ['2011-12-05'], ''),
    ('20111206', ['2011-12-06'], 'Printed date is not Monday'),
    ('20110230', [], 'No valid supported calendar reading'),
])
def test_week_start_role_and_invalid_values_stay_visible(engine, raw, candidates, warning):
    field = fields(engine, f'HMTG-112-AG-Weekof{raw}.pdf', 'date_token')[0]
    assert field['raw'] == raw and field['candidates'] == candidates
    assert field['note'].startswith('Week start date; the House guide specifies Monday')
    assert warning in field['note']
    if not warning:
        assert 'not Monday' not in field['note']


def test_inferred_version_boundary_remains_explicit(engine):
    field = fields(engine, 'BILLS-119HR12EnergyActih.pdf', 'version_token')[0]
    assert field['code'] == 'ih' and field['candidates'] == ['ih']
    assert 'boundary is inferred' in field['note']
    uncertain = fields(engine, 'BILLS-119ANSServices.pdf', 'version_token')[0]
    assert uncertain['code'] is None and uncertain['candidates'] == ['es']
    assert 'Possible word ending' in uncertain['note']


@pytest.mark.parametrize('filename,raw,ending', [
    ('BILLS-112HRES-ORH-Rule-HR10.pdf', 'HRES-ORH', 'RH'),
    ('BILLS-119AB-SERIES.pdf', 'AB-SERIES', 'ES'),
])
def test_compound_identifier_word_ending_is_not_a_version(engine, filename, raw, ending):
    field = fields(engine, filename, 'version_token')[0]
    assert field['raw'] == ending and field['code'] is None
    assert field['candidates'] == [ending.lower()]
    assert fields(engine, filename, 'local_identifier')[0]['raw'] == raw


def test_separated_version_wins_over_compound_word_ending(engine):
    filename = 'BILLS-119AB-SERIES-RH.pdf'
    field = fields(engine, filename, 'version_token')[0]
    assert field['raw'] == 'RH' and field['code'] == 'rh'
    assert fields(engine, filename, 'local_identifier')[0]['raw'] == 'AB-SERIES-'


@pytest.mark.parametrize('filename,version', [
    ('BILLS-114114-XXrth.pdf', 'rth'),
    ('BILLS-116Barr1Aih.pdf', 'ih'),
    ('BILLS-112114-22rh.pdf', 'rh'),
])
def test_real_compound_identifiers_keep_their_version_boundary(engine, filename, version):
    assert fields(engine, filename, 'version_token')[0]['code'] == version


def test_format_wording_is_separate_from_actual_extension(engine):
    filename = 'BILLS-113-HR1256rh-FS_xml.pdf'
    field = fields(engine, filename, 'filename_format_token')[0]
    assert field['raw'] == 'xml' and 'neither an extension' in field['note']
    assert fields(engine, filename, 'extension')[0]['raw'] == 'pdf'


@pytest.mark.parametrize('filename,identifier,version', [
    ('BILLS-117SubtitleArth.pdf', 'A', 'rth'),
    ('BILLS-117SubtitleBrth.pdf', 'B', 'rth'),
    ('BILLS-117SubtitleCrth.pdf', 'C', 'rth'),
    ('BILLS-117SubtitleDrth.pdf', 'D', 'rth'),
    ('BILLS-119CommitteePrintSubtitleApp-U1.pdf', 'A', 'pp'),
    ('BILLS-119CommitteePrintSubtitleBpp.pdf', 'B', 'pp'),
    ('BILLS-119CommitteePrintSubtitleCpp.pdf', 'C', 'pp'),
])
def test_structured_subtitle_letter_is_not_free_text(engine, filename, identifier, version):
    assert fields(engine, filename, 'local_identifier')[0]['raw'] == identifier
    assert fields(engine, filename, 'version_token')[0]['code'] == version
