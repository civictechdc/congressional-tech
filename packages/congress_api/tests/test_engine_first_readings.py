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


# The anchor of body 5e9b5643 (direct CHRG-119hhrg64404 HTML, line 624) and the
# same line in its ZIP member b14d49d9, which carries the plain address.
CLOUDFLARE_ANCHOR = ('<a href="/cdn-cgi/l/email-protection" class="__cf_email__" '
                     'data-cfemail="4d09222e38202823393e19040d202c2421632522383e28632a223b">[email&#160;protected]</a>')
TRANSCRIPT = ('    As a reminder, if Members wish to insert a document into \nthe record, please also email it to {}.\n'
              + '    The committee received testimony on rural transportation and public lands. \n' * 40)


def transcript(text, tail=''):
    return f'<html><head><title>Hearing</title></head><body><pre>{text}{tail}</pre></body></html>'.encode()


def test_cloudflare_obfuscated_address_reads_as_the_plain_address():
    from congress_api.parsers.archive_readings import read_page

    direct = read_page(transcript(TRANSCRIPT.format(CLOUDFLARE_ANCHOR)), 'html')
    member = read_page(transcript(TRANSCRIPT.format('DocumentsTI@mail.house.gov')), 'html')
    assert member['fingerprint'] is not None and direct['fingerprint'] == member['fingerprint']
    assert 'DocumentsTI@mail.house.gov' in direct['text_head']
    assert {key for key in direct if direct[key] != member[key]} == {'fields'}
    assert {'field': 'cloudflare_emails', 'value': '1'} in direct['fields']
    other = read_page(transcript(TRANSCRIPT.format(CLOUDFLARE_ANCHOR.replace('4d0922', '4e0922'))), 'html')
    assert other['fingerprint'] != direct['fingerprint']


def test_cloudflare_protected_mailto_reads_as_mailto():
    from congress_api.parsers.archive_readings import read_page

    body = transcript(TRANSCRIPT.format(
        '<a href="/cdn-cgi/l/email-protection#4d09222e38202823393e19040d202c2421632522383e28632a223b">write to us</a>'))
    links = read_page(body, 'html')['links']
    assert [link['href'] for link in links] == ['mailto:DocumentsTI@mail.house.gov']


def test_malformed_cloudflare_token_is_left_as_written():
    from congress_api.parsers.archive_readings import browser_body

    for token in ('4d0', 'zz', ''):
        body = f'<p><a href="/cdn-cgi/l/email-protection" data-cfemail="{token}">[email protected]</a></p>'.encode()
        assert browser_body(body) == (body, 0)


@pytest.mark.parametrize('tail', ['\x1a\n', '\n<GRAPHIC(S) NOT AVAILABLE IN TIFF FORMAT>\n'])
def test_transcript_with_a_control_or_graphic_marker_has_a_fingerprint(tail):
    from congress_api.parsers.archive_readings import read_page

    text = TRANSCRIPT.format('DocumentsTI@mail.house.gov')
    plain = read_page(transcript(text), 'html')
    marked = read_page(transcript(text, tail), 'html')
    assert marked['fingerprint'] is not None
    basis = {f['value'] for f in marked['fields'] if f['field'] == 'fingerprint_basis'}
    assert basis == ({'main_without_controls'} if tail.startswith('\x1a') else {'visible'})
    if tail.startswith('\x1a'):
        assert marked['fingerprint'] == plain['fingerprint']


def test_controls_a_member_shares_with_its_obfuscated_copy_read_the_same():
    """R1: 95 GovInfo members carry the same vertical tab as their direct copy; the member reads
    plainly, so the decoded direct copy must keep the control too."""
    from congress_api.parsers.archive_readings import read_page

    text = TRANSCRIPT + 'The Watch Desk is staffed 24\x0b7.\n'
    direct = read_page(transcript(text.format(CLOUDFLARE_ANCHOR)), 'html')
    member = read_page(transcript(text.format('DocumentsTI@mail.house.gov')), 'html')
    assert not member['fields'] and member['fingerprint'] == direct['fingerprint']


def test_no_visible_text_gives_no_fingerprint():
    from congress_api.parsers.archive_readings import read_page

    row = read_page(b'<html><body><script>var a=1;</script></body></html>', 'html')
    assert row['status'] == 'completed' and row['fingerprint'] is None


def test_reader_changes_only_readings_in_the_reread_set():
    """A reading outside HTML_REREAD_SQL is the plain reader's output, unchanged."""
    from congress_api.parsers import archive_readings as reader

    bodies = [transcript(TRANSCRIPT.format('a@b.gov')), transcript(TRANSCRIPT.format(CLOUDFLARE_ANCHOR)),
              transcript(TRANSCRIPT.format('x'), '\x1a'), b'<html><p>short</p></html>',
              b'<html><body><p>see data-cfemail="00" here</p></body></html>' + b'<p>words</p>' * 50]
    for body in bodies:
        plain, _ = reader._plain_reading(body, 'html')
        row = reader.read_page(body, 'html')
        assert (row == plain) is (not reader.needs_browser_reading(plain))
    for parser, body in [('xml', b'<a>\x1a</a>'), ('json', b'{"a":"\x1a"}'), ('xml', b'<meeting/>')]:
        assert reader.read_page(body, parser) == reader._plain_reading(body, parser)[0]


def test_a_decoded_address_is_text_not_markup():
    """Cloudflare's decoder inserts a text node; markup characters in the address stay characters."""
    from congress_api.parsers.archive_readings import read_page

    address = 'x<y&z@house.gov'
    token = bytes([0x21]) + bytes(b ^ 0x21 for b in address.encode())
    anchor = f'<a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="{token.hex()}">[email&#160;protected]</a>'
    row = read_page(transcript(TRANSCRIPT.format(anchor)), 'html')
    assert address in row['text_head']
