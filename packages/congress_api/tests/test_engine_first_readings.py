"""S1 parser fixtures: expected evidence precedes the parser and model SQL."""

import json
from pathlib import Path

import pytest


CASES = json.loads((Path(__file__).parents[3] / 'model/fixtures/parser-cases.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_reading_preserves_unresolved_publisher_evidence(case):
    from congress_api.parsers.archive_readings import read_page

    actual = read_page(case['body'].encode(), case['parser'])
    assert actual['status'] == 'completed'
    for field, expected in case['expected'].items():
        if field == 'links':
            assert len(actual[field]) == len(expected)
            for value, wanted in zip(actual[field], expected, strict=True):
                assert {key: value[key] for key in wanted} == wanted
        else:
            assert actual[field] == expected
    assert read_page(case['body'].encode(), case['parser']) == actual


def test_main_content_ignores_furniture_but_keeps_substantive_changes():
    from congress_api.parsers.archive_readings import read_page

    paragraph = 'The committee received evidence on public transportation and its effect on rural communities. '
    def page(menu, evidence):
        return (f'<html><body><nav>{menu}</nav><main><article><h1>Hearing record</h1>'
                f'<p>{paragraph * 12}</p><p>{evidence}</p></article></main><footer>{menu}</footer></body></html>').encode()
    a = read_page(page('Home Search', 'The nominee is Alice Smith.'), 'html')
    b = read_page(page('Menu Archive', 'The nominee is Alice Smith.'), 'html')
    c = read_page(page('Home Search', 'The nominee is Bob Jones.'), 'html')
    assert a['fingerprint'] is not None
    assert a['fingerprint'] == b['fingerprint']
    assert a['fingerprint'] != c['fingerprint']


def test_invalid_json_fails_without_emitting_input_text():
    from congress_api.parsers.archive_readings import read_page

    for body in (b'{"private-value":', b'{"number":NaN}', b'\xff'):
        actual = read_page(body, 'json')
        assert actual['status'] == 'error'
        assert actual['fingerprint'] is None
        assert 'private-value' not in json.dumps(actual)


def test_empty_display_facts_use_the_native_fold_shape():
    from congress_api.parsers.archive_readings import read_page
    from congress_api.retention.sniff import read_sniff

    for parser, body in [('html', b'<html><p>Hearing record</p></html>'),
                         ('xml', b'<meeting/>'), ('json', b'{"meeting":1}')]:
        assert read_page(body, parser)['fields'] == []
    body = b'%PDF-1.7\n%%EOF'
    assert read_sniff(lambda start, length: body[start:start + length],
                      stored_size=len(body))['fields'] == []
