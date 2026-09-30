"""Filename extensions do not establish response content or successful capture."""
import pytest

from house_naming import Engine
from house_naming.filenames import parse_filename


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    assert parse_filename(name).model_dump(mode='json')['matches'] == result['observations']
    for m in result['observations']:
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    return result


def fields(result, key):
    return [f for m in result['observations'] for f in m['fields'] if f['name'] == key]


@pytest.mark.parametrize('name,stem,extension', [
    ('ByEvent.aspx', 'ByEvent', 'aspx'),
    ('Default.aspx', 'Default', 'aspx'),
    ('Download.aspx', 'Download', 'aspx'),
    ('Error.aspx', 'Error', 'aspx'),
    ('index.cfm', 'index', 'cfm'),
    ('master.m3u8', 'master', 'm3u8'),
    ('Middle East UAP.mp4', 'Middle East UAP', 'mp4'),
    ('FOREIGN_2024-05-09 (Nominations Hearing).MP3', 'FOREIGN_2024-05-09 (Nominations Hearing)', 'MP3'),
])
def test_source_names_keep_literal_suffix_and_stem(engine, name, stem, extension):
    result = checked(engine, name)
    ext, = fields(result, 'extension')
    assert (ext['raw'], ext['start'], ext['end']) == (extension, len(stem)+1, len(name))
    assert result['stem_end'] == len(stem)
    assert fields(result, 'name_token')[0]['raw'] == stem
    assert ext['code'] is None and ext['label'] is None and not ext['candidates']
    assert 'does not verify' in result['observations'][0]['description']
    assert not result['valid'] and result['matches'] == []


@pytest.mark.parametrize('number', ['1', '2'])
def test_media_numeric_tail_keeps_the_existing_fallback_policy(engine, number):
    result = checked(engine, f'South Asia UAP {number}.mp4')
    assert fields(result, 'extension')[0]['raw'] == 'mp4'
    assert fields(result, 'name_token')[0]['raw'] == 'South Asia UAP'
    identifier, = fields(result, 'generic_identifier')
    assert identifier['raw'] == number and 'assumption' in identifier['note'].lower()
    assert not any(fields(result, key) for key in ['part_number', 'recording_number', 'meeting_sequence'])


@pytest.mark.parametrize('extension', ['MP3', 'Mp4', 'M3U8', 'ASPX', 'CfM'])
def test_case_padding_stacked_extensions_and_query_text(engine, extension):
    name = f' sample.{extension}.pdf?download=1  '
    result = checked(engine, name)
    assert [f['raw'] for f in fields(result, 'extension')] == ['pdf', extension]
    assert fields(result, 'name_token')[0]['raw'] == 'sample'
    assert fields(result, 'query_text')[0]['raw'] == '?download=1'
    assert name[result['stem_end']:] == f'.{extension}.pdf?download=1  '


def test_audio_filename_date_and_nomination_wording_survive(engine):
    result = checked(engine, 'FOREIGN_2024-05-09 (Nominations Hearing).MP3')
    date, = fields(result, 'date_token')
    assert date['raw'] == '2024-05-09' and date['candidates'] == ['2024-05-09']
    assert fields(result, 'label')[0]['raw'] == 'Nominations'
    assert not any(fields(result, key) for key in ['mime_type', 'content_type', 'capture_status', 'recording_status'])


def test_handler_query_is_separate_from_its_literal_suffix(engine):
    result = checked(engine, 'index.cfm?a=Files.Serve&File_id=553B11AA-B3B7-42B4-974B-48188BCF660B')
    assert fields(result, 'extension')[0]['raw'] == 'cfm'
    assert fields(result, 'name_token')[0]['raw'] == 'index'
    assert fields(result, 'query_text')[0]['raw'].startswith('?a=Files.Serve')
    assert not fields(result, 'opaque_uuid')


@pytest.mark.parametrize('name', ['recordingmp4', 'clip.mp34', 'clip.mp4a', 'clip.m3u81', 'Default.aspxx', 'index.cfmx', 'clip.mp4.', 'clip.unknown'])
def test_suffix_must_be_complete_and_recognized(engine, name):
    assert not fields(checked(engine, name), 'extension')


def test_literal_support_does_not_widen_canonical_house_formats(engine):
    result = checked(engine, 'BILLS-119hr1ih.mp4')
    assert not result['valid'] and 'missing-or-unsupported-extension' in result['issues']
    assert fields(result, 'extension')[0]['raw'] == 'mp4'
    assert fields(result, 'measure_number')[0]['raw'] == '1'


def test_damaged_transport_uses_the_same_extension_recognizer(engine):
    result = checked(engine, 'BILLS-119hr1ih.mp4https:')
    assert not fields(result, 'extension')
    assert fields(result, 'embedded_extension')[0]['raw'] == 'mp4'
    assert fields(result, 'protocol_marker')[0]['raw'] == 'https:'
    assert any(m['scope'] == 'legislative-payload-fragment' for m in result['observations'])
