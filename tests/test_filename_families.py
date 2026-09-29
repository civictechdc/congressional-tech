"""Declared filename-family examples; syntax labels, not document-content truth."""
import pytest

from congress_api.filenames import parse_filename, RULES


@pytest.mark.parametrize(('filename', 'expected'), [
    ('BILLS-113-HR-FC-AP-FY2014-AP00-Amdt-001.pdf',
     {'measure_token': 'HR', 'scope_token': 'FC', 'committee_token': 'AP', 'fiscal_year_token': '2014', 'committee_code': 'AP00'}),
    ('BILLS-118--AP--AP00-FY24DefenseFullCommitteeMark.pdf',
     {'scope_token': '', 'committee_token': 'AP', 'committee_code': 'AP00'}),
    ('BILLS-1161-ORH-AP--MilCon-FY2021MILCON-VASubcommitteeBill.pdf',
     {'scope_token': 'ORH', 'committee_token': 'AP'}),
    ('BILLS-1165245-HAmdt2.pdf', {'amendment_marker': 'HAmdt', 'amendment_token': '2'}),
    ('BILLS-116ANStoHR1988ih.pdf', {'amendment_marker': 'ANS', 'measure_token': 'HR', 'measure_number': '1988', 'version_token': 'ih'}),
    ('BILLS-116-5308-KOOO395-Amdt-14.pdf', {'sponsor_identifier_token': 'KOOO395', 'amendment_token': '14'}),
    ('BILLS-119HRih.pdf', {'measure_token': 'HR', 'version_token': 'ih'}),
    ('BILLS-118XXXXXXXXih.pdf', {'number_placeholder': 'XXXXXXXX', 'version_token': 'ih'}),
    ('BILLS-119____A2ih.pdf', {'number_placeholder': '____A2', 'version_token': 'ih'}),
    ('BILLS-118118-30rh.pdf', {'local_identifier': '118-30', 'version_token': 'rh'}),
    ('BILLS-117CmtePrint117-1ih.pdf', {'print_token': 'CmtePrint', 'print_identifier': '117-1', 'version_token': 'ih'}),
    ('BILLS-117RCP35-JES-DIVISION-C_Part1.pdf', {'print_token': 'RCP', 'print_identifier': '35', 'division_token': 'C'}),
    ('BILLS-119D1ih.pdf', {'local_identifier': 'D1', 'version_token': 'ih'}),
    ('BILLS-117SubtitleArth.pdf', {'draft_label': 'Subtitle', 'local_identifier': 'A', 'version_token': 'rth'}),
    ('BILLS-117ResolutiontoreauthorizetheArtificialIntelligenceTaskForceih.pdf', {'version_token': 'ih'}),
    ('BILLS-115HR-REINS17-PIH.pdf', {'measure_token': 'HR', 'descriptor': 'REINS17', 'version_token': 'PIH'}),
    ('BILLS-113HConRes-PIH-BudgetRes.pdf', {'measure_token': 'HConRes', 'version_token': 'PIH', 'suffix': '-BudgetRes'}),
    ('BILLS-113hjres-FEMA.pdf', {'measure_token': 'hjres', 'descriptor': 'FEMA'}),
    ('BILLS-115hres-Israel-PIH.pdf', {'measure_token': 'hres', 'descriptor': 'Israel', 'version_token': 'PIH'}),
    ('BILLS-113TextofHR3981ih.pdf', {'reference_marker': 'Textof', 'measure_token': 'HR', 'measure_number': '3981', 'version_token': 'ih'}),
])
def test_declared_family_fields(filename, expected):
    scopes = {r.id: r.scope for r in RULES}
    parsed = parse_filename(filename)
    matches = [m for m in parsed.matches if scopes.get(m.rule) == 'legislative-payload']
    assert len(matches) == 1
    fields = {f.name: f.raw for f in matches[0].fields}
    assert fields.items() >= expected.items()
    for match in parsed.matches:
        for field in match.fields:
            assert filename[field.start:field.end] == field.raw


@pytest.mark.parametrize('name', ['Services', 'Earth', 'Smith', 'Photographs', 'BudgetEstimates'])
def test_ordinary_words_do_not_become_bill_versions(name):
    parsed = parse_filename(f'BILLS-119{name}.pdf')
    assert not any(f.name == 'version_token' for m in parsed.matches for f in m.fields)


@pytest.mark.parametrize('payload', ['HRih', 'XXXXXXXXih', '____A2ih', '118-30rh', 'D1ih', 'SubtitleArth'])
def test_local_identifiers_and_placeholders_do_not_become_bill_numbers(payload):
    parsed = parse_filename(f'BILLS-119{payload}.pdf')
    assert not any(f.name == 'measure_number' for m in parsed.matches for f in m.fields)


def test_defective_sponsor_is_preserved_without_inventing_a_bioguide_id():
    parsed = parse_filename('BILLS-116-5308-KOOO395-Amdt-14.pdf')
    assert not any(f.name == 'bioguide_token' for m in parsed.matches for f in m.fields)


def test_appropriations_descriptors_do_not_receive_terminal_word_versions():
    parsed = parse_filename('BILLS-119--AP--FServices.pdf')
    assert not any(f.name == 'version_token' for m in parsed.matches for f in m.fields)


def test_print_explanation_marker_is_not_a_bill_version():
    parsed = parse_filename('BILLS-117RCP35-JES-DIVISION-C_Part1.pdf')
    assert not any(f.name == 'version_token' for m in parsed.matches for f in m.fields)


def test_committee_code_is_not_a_sponsor_identifier():
    parsed = parse_filename('BILLS-113-HR-FC-AP-FY2014-AP00-Amdt-001.pdf')
    assert not any(f.name == 'sponsor_identifier_token' for m in parsed.matches for f in m.fields)


@pytest.mark.parametrize('payload', [
    '____pih-DHSIllicitCross-BorderTunnelDefenseAct',
    'Xpih-PromotingFreeandFairElectionsActof2023-U9',
    'XXXXXpih-RNA', 'D1pih', 'D1pis', 'D1rih', '____PIH', '____pis', '____rih',
    'PCA-01-SJ20PIH', 'GSA2020-37PIH',
])
def test_optional_identifier_letters_do_not_shorten_version_codes(payload):
    # The first three are observed failures; the rest are constructed boundaries.
    parsed = parse_filename(f'BILLS-119{payload}.pdf')
    versions = [f for m in parsed.matches for f in m.fields if f.name == 'version_token']
    assert len(versions) == 1
    expected = next(code for code in ('pih', 'pis', 'rih') if code in payload.lower())
    assert versions[0].raw.lower() == expected
    if expected == 'pis':
        assert versions[0].label is None
    elif expected == 'pih':
        assert versions[0].label == 'Pre-introduced measure'
