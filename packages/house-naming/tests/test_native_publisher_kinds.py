"""Complete publisher layouts, with source and topic boundaries checked."""
import pytest

from house_naming import Engine, document_families


@pytest.fixture(scope='module')
def engine():
    return Engine()


@pytest.mark.parametrize('name,host,kind', [
    ('PLAW-115publ401.pdf', 'www.congress.gov', 'public-law'),
    ('PLAW-113publ28.pdf', 'www.govinfo.gov', 'public-law'),
    ('PLAW-112publ25.pdf', 'www.gpo.gov', 'public-law'),
    ('h2001_rh_xml.pdf', 'docs.house.gov', 'legislative-text'),
    ('H2317NR_RH_xml.pdf', 'docs.house.gov', 'legislative-text'),
    ('h2978fs_rh_xml.pdf', 'docs.house.gov', 'legislative-text'),
    ('H5109_SUS_xml.pdf', 'docs.house.gov', 'legislative-text'),
    ('H807_SUS_xml.pdf', 'docs.house.gov', 'legislative-text'),
    ('112-12.pdf', 'financialservices.house.gov', 'published-hearing'),
    ('103-3.pdf', 'financialservices.house.gov', 'published-hearing'),
])
def test_checked_native_layout(engine, name, host, kind):
    result = engine.extract(name, source_url=f'https://{host}/files/{name}')
    assert result['metadata']['document_kind'] == [kind]
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    for observation in result['observations']:
        for field in observation['fields']:
            assert name[field['start']:field['end']] == field['raw']
    assert {key: result[key] for key in engine.parse(name)} == engine.parse(name)


@pytest.mark.parametrize('name,host,forbidden', [
    ('PLAW-115publ401.pdf', 'example.org', 'public-law'),
    ('PLAW-115publ401.pdf', 'www.govinfo.gov.evil.test', 'public-law'),
    ('PLAW-115publ401_summary.pdf', 'www.govinfo.gov', 'public-law'),
    ('PLAW-115priv401.pdf', 'www.govinfo.gov', 'public-law'),
    ('PLAW-115publ0.pdf', 'www.govinfo.gov', 'public-law'),
    ('PLAW-115publ401.xml', 'www.govinfo.gov', 'public-law'),
    ('PLAW-115publ401.pdf.jpg', 'www.govinfo.gov', 'public-law'),
    ('h2001_rh_xml.pdf', 'example.org', 'legislative-text'),
    ('h2001_rh_xml.pdf.jpg', 'docs.house.gov', 'legislative-text'),
    ('h2001_rh_xml_summary.pdf', 'docs.house.gov', 'legislative-text'),
    ('h2001_rh_xml_AMD.pdf', 'docs.house.gov', 'legislative-text'),
    ('h2001_sub_xml.pdf', 'docs.house.gov', 'legislative-text'),
    ('h2001_cpt_xml.pdf', 'docs.house.gov', 'legislative-text'),
    ('H807_SUS_xml_memo.pdf', 'docs.house.gov', 'legislative-text'),
    ('112-12.pdf', 'veterans.house.gov', 'published-hearing'),
    ('112-12.pdf', 'financialservices.house.gov.evil.test', 'published-hearing'),
    ('112-12_memo.pdf', 'financialservices.house.gov', 'published-hearing'),
    ('112-12.pdf.jpg', 'financialservices.house.gov', 'published-hearing'),
    ('112-12.xml', 'financialservices.house.gov', 'published-hearing'),
])
def test_complete_source_qualified_pdf_only(engine, name, host, forbidden):
    assert forbidden not in engine.extract(name, source_url=f'https://{host}/{name}')['metadata'].get('document_kind', [])


def test_serial_does_not_establish_congress_or_gpo_identity(engine):
    # Retained cover says serial 113-3 despite publisher filename 103-3.pdf.
    metadata = engine.extract('103-3.pdf', source_url='https://financialservices.house.gov/uploadedfiles/103-3.pdf')['metadata']
    assert metadata['document_kind'] == ['published-hearing']
    assert metadata['serial_token'] == ['103-3']
    assert not metadata.get('congress')
    assert not metadata.get('publication_number')


def test_existing_literal_bill_fields_survive(engine):
    name = 'h2978fs_rh_xml.pdf'
    before = engine.extract(name)['metadata']
    after = engine.extract(name, source_url='https://docs.house.gov/' + name)['metadata']
    for field in ('measure_token', 'measure_number', 'version_token', 'version_token_label', 'filename_format_token', 'local_modifier', 'extension'):
        assert after.get(field) == before.get(field)
    assert not after.get('congress')


def test_enacted_law_has_its_own_kind_and_legislation_family():
    assert document_families(['public-law']) == ['legislation']
