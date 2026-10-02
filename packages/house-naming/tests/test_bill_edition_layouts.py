"""Reviewed Senate bill covers support complete edition layouts, not bare references."""
import pytest
from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


@pytest.mark.parametrize('name', [
    'S. 1000 (Reported Out).pdf', 'S. 1678 As Reported.pdf',
    'S1829_asreported_WAL25565.pdf', 'S.1801 (Reported Out).pdf',
    'S. 2355 Text_4d34c357-63f0-4fe0-92bb-2bf70d8ced47.pdf',
    'S. 4726 (Reported Out)_c6bf2c07-df2b-4eed-bd2f-1674d052db8f.pdf',
])
def test_bill_edition_is_legislative_text(engine, name):
    result = engine.extract(name)
    assert result['metadata']['document_kind'] == ['legislative-text']
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for observation in result['observations']:
        for field in observation['fields']:
            assert name[field['start']:field['end']] == field['raw']
    assert not result['metadata'].get('version_token')
    assert not result['metadata'].get('congress')


@pytest.mark.parametrize('number', ['111111', '12345'])
def test_bill_number_is_not_reinterpreted_as_a_date(engine, number):
    row = engine.extract(f'S. {number} Text.pdf')['metadata']
    assert row['measure_references'] == ['s'+number]
    assert row['document_kind'] == ['legislative-text']
    assert not row.get('date_token') and not row.get('short_date_token')


@pytest.mark.parametrize('name', [
    'S. 1000.pdf', 's-1000', 'S. 1000 Text Summary.pdf',
    'S. 1000 Reported Out Amendment.pdf', 'Testimony on S. 1000 Text.pdf',
    'S. 1173 Introduced Species Act.pdf', 'S. 1000 - Smith Substitute.pdf',
])
def test_reference_or_extra_document_wording_is_not_a_complete_bill_layout(engine, name):
    assert 'legislative-text' not in engine.extract(name)['metadata'].get('document_kind', [])
