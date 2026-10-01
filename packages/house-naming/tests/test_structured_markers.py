"""Correct marker roles without repairing source bytes or inventing formats."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in result['observations']:
        for f in m['fields']:
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
            assert name[f['start']:f['end']] == f['raw']
    return result


def fields(result, name):
    return [f for m in result['observations'] for f in m['fields'] if f['name'] == name]


@pytest.mark.parametrize('name', [
    'bills-118s3679ispdf', 'bills-118s3757ispdf', 'bills-118s3765ispdf',
    'bills-118s3775ispdf', 'bills-118s4045ispdf', 'bills-119s163ispdf',
    'bills-119s558ispdf',
])
def test_observed_hanging_pdf_does_not_hide_the_version(engine, name):
    result = checked(engine, name)
    version, = fields(result, 'version_token')
    assert version['raw'] == version['code'] == 'is'
    assert version['label'] == engine.lookup('version', 'is')['label']
    suffix, = fields(result, 'ignored_suffix')
    assert suffix['raw'] == 'pdf'
    assert 'not an actual extension' in suffix['note']
    assert fields(result, 'extension') == []
    assert 'missing-or-unsupported-extension' in result['issues']
    assert [m['rule'] for m in result['observations'] if m['scope'] == 'legislative-payload'] == ['legislative-text']


@pytest.mark.parametrize('version', sorted(Engine().guide['codes']['version']))
def test_same_hanging_suffix_rule_applies_to_each_known_version(engine, version):
    name = f'BILLS-119hr123{version}pdf'
    result = checked(engine, name)
    actual, = fields(result, 'version_token')
    assert actual['raw'] == actual['code'] == version
    assert fields(result, 'ignored_suffix')[0]['raw'] == 'pdf'
    assert not fields(result, 'extension')


@pytest.mark.parametrize('name,extensions', [
    ('BILLS-119hr123eas2pdf.pdf', ['pdf']),
    ('BILLS-119hr123eas2pdf.pdf.pdf', ['pdf', 'pdf']),
    (' BILLS-119hr123eas2(asfiled)PDF.pdf ', ['pdf']),
    ('BILLS-119hr123eas2pdf&download=1', []),
])
def test_numeric_modifier_annotation_and_transport_keep_original_spans(engine, name, extensions):
    result = checked(engine, name)
    assert [f['raw'] for f in fields(result, 'version_token')] == ['eas']
    assert [f['raw'] for f in fields(result, 'version_number_token')] == ['2']
    assert [f['raw'] for f in fields(result, 'extension')] == extensions
    assert fields(result, 'ignored_suffix')[0]['raw'].lower() == 'pdf'
    if 'asfiled' in name:
        assert fields(result, 'annotation')[0]['raw'] == 'asfiled'
        assert fields(result, 'qualifier_wording')[0]['raw'] == 'asfiled'


@pytest.mark.parametrize('token,context,field_name', [
    ('SUS', 'consideration', 'local_code_token'),
    ('sus', 'consideration', 'local_code_token'),
    ('UConsent', 'consideration', 'local_code_token'),
    ('uconsent', 'consideration', 'local_code_token'),
    ('ANS', None, 'amendment_marker'),
    ('AINS', None, 'amendment_marker'),
])
def test_whole_marker_reuses_its_existing_role(engine, token, context, field_name):
    name = f'BILLS-119HR123{token}-RCP119-7.pdf'
    result = checked(engine, name)
    field, = fields(result, field_name)
    assert field['raw'] == token
    assert not fields(result, 'version_token')
    assert field['context'] == context
    if context:
        entry = engine.lookup(context, token)
        assert field['code'] == token.lower()
        assert field['label'] == entry['label']
        assert field['vocabulary_url'].endswith('#page=7')
    else:
        assert field['code'] is None
        assert field['label'] == 'Amendment in the nature of a substitute'
    assert fields(result, 'print_number')[0]['raw'] == '7'


def test_observed_ans_does_not_replace_the_separate_interchamber_marker(engine):
    result = checked(engine, 'BILLS-119HR3334ANS-HAmdt.pdf')
    markers = fields(result, 'amendment_marker')
    assert [f['raw'] for f in markers] == ['ANS', 'HAmdt']
    assert markers[0]['code'] is None
    assert markers[1]['code'] == 'hamdt'
    assert not fields(result, 'version_token')


@pytest.mark.parametrize('token', ['SA', 'or', 'XYZ', 'SUSPECT', 'UConsented'])
def test_unknown_and_longer_tokens_do_not_acquire_known_meanings(engine, token):
    result = checked(engine, f'BILLS-119HR123{token}.pdf')
    assert not fields(result, 'local_code_token')
    assert not fields(result, 'amendment_marker')
    if token in {'SA', 'or', 'XYZ'}:
        version, = fields(result, 'version_token')
        assert version['raw'] == token and version['code'] is None


@pytest.mark.parametrize('name', [
    'BILLS-119hr123ihxml', 'BILLS-119hr123ihpdfextra',
    'BILLS-119hr123ispdfpdf', 'BILLS-119hr123ihpdf-U1.pdf',
    'BILLS-119hr123Farmingpdf', 'BILLS-119hr123ih-Titlepdf.pdf',
    'HHRG-119-IF00-Wstate-ispdf-20260101.pdf',
])
def test_hanging_format_does_not_strip_other_slots_or_extra_letters(engine, name):
    result = checked(engine, name)
    assert not any(m['rule'] == 'legislative-text' and f['name'] == 'ignored_suffix'
                   for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    'Biography-SUS.pdf', 'Biography-ANS.pdf',
    'HHRG-119-IF00-Wstate-SUS-20260101.pdf',
    'BILLS-119-HR123-A000001-Amdt-SUS.pdf',
])
def test_known_marker_mapping_does_not_escape_the_short_marker_slot(engine, name):
    result = checked(engine, name)
    assert not fields(result, 'local_code_token')


def test_real_extension_and_free_suffix_unchanged(engine):
    result = checked(engine, 'BILLS-119hr123is-Titlepdf.pdf')
    assert fields(result, 'extension')[0]['raw'] == 'pdf'
    assert fields(result, 'version_token')[0]['raw'] == 'is'
    assert fields(result, 'suffix')[0]['raw'] == '-Titlepdf'
    assert not fields(result, 'ignored_suffix')
