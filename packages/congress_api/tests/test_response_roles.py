"""Role observations must not turn document phrases or refusal into rejection."""
from hashlib import sha256
from pathlib import Path

import pytest

from congress_api.parsers.response_roles import MAX_EVIDENCE_FIELDS, MAX_EVIDENCE_TEXT_CHARS, assess_response


def house_html(kind):
    # Reduced visible templates from retained originals M004 (meeting) and
    # M002 (file); full-source identities/replay live in ct-fb7k's evidence.
    return (Path(__file__).parent / 'fixtures/response_roles' / f'house-{kind}-not-found.html').read_bytes()


@pytest.mark.parametrize('kind', ['meeting', 'file'])
def test_house_errors_require_a_complete_primary_meeting_area(kind):
    source = house_html(kind)
    row = assess_response(source, format='html')
    assert (row.role, row.reason) == ('error_response', f'house_{kind}_not_found')
    assert row.policy_version == 'ct-response-roles-v2'
    assert row.body_sha256 == sha256(source).hexdigest()
    panel, = [field for field in row.evidence if field['field'] == 'house_error_alert']
    assert source[panel['byte_start']:panel['byte_end']].startswith(b"<div class='alert alert-error'>")
    assert 'exception category:' in panel['text'] and 'meeting id:' in panel['text']
    if kind == 'file':
        assert 'sst full committee markup' in next(f['text'] for f in row.evidence if f['field'] == 'h1')
        assert 'publish id: hmkp118348' in panel['text']


@pytest.mark.parametrize(('before', 'after'), [
    (b'[Meeting Not Found]', b'[Meeting schedule updated]'),
    (b'No meeting data is available for display.', b'Meeting documents are available below.'),
    (b'<title>Event |', b'<title>Report about web errors |'),
    (b"class='alert alert-error'", b"class='well'"),
    (b'<strong>Exception Category</strong>: General', b'<strong>Exception Category</strong>: Quoted example'),
    (b'<div id="DivMeetingContent">', b'<div id="DivMeetingContent"><p>Substantive testimony remains here.</p>'),
    (b'<div id="DivMeetingContent">', b'<div id="other" id="DivMeetingContent">'),
    (b'</div></div></body>', b'</body>'),
])
def test_partial_or_mixed_house_diagnostics_stay_unassessed(before, after):
    source = house_html('meeting')
    assert before in source
    assert assess_response(source.replace(before, after), format='html').role == 'unassessed'


@pytest.mark.parametrize('attribute', [b'hidden', b'aria-hidden="true"', b'style="display: none"',
                                      b'style="color: red; VISIBILITY: hidden !important;"'])
@pytest.mark.parametrize('element', [b'<div id="DivMeetingContent"', b"<div class='alert alert-error'"])
def test_hidden_house_diagnostics_cannot_supply_a_role(attribute, element):
    source = house_html('meeting').replace(element, element+b' '+attribute)
    assert assess_response(source, format='html').role == 'unassessed'


@pytest.mark.parametrize('element', [b'blockquote', b'q', b'pre', b'code', b'article', b'template', b'script'])
def test_house_template_quoted_in_a_document_is_not_the_response(element):
    source = house_html('meeting').replace(b'<div id="body">', b'<div id="body"><'+element+b'>')
    source = source.replace(b'</body>', b'</'+element+b'></body>')
    assert assess_response(source, format='html').role == 'unassessed'


@pytest.mark.parametrize(('before', 'after'), [
    (b'<div id="body">', b'<div id="body" style="display:none" style="display:block">'),
    (b'<div id="body">', b'<div id="body" style="display:block" style="display:none">'),
    (b'<div id="body">', b'<div id="different" id="body">'),
    (b'<h1>', b'<h1 style="display:none" style="display:block">'),
    (b'<h1>', b'<h1 aria-hidden="false" aria-hidden="true">'),
    (b'<strong>Error Encountered', b'<strong style="display:block" style="display:none">Error Encountered'),
    (b'<div id="DivMeetingContent">', b'<div id="DivMeetingContent">'
        b'<p style="display:none" style="display:block">Possibly visible testimony.</p>'),
])
@pytest.mark.parametrize('kind', ['meeting', 'file'])
def test_ambiguous_ancestor_heading_or_diagnostic_cannot_qualify_house_role(kind, before, after):
    source = house_html(kind)
    assert before in source
    row = assess_response(source.replace(before, after), format='html')
    assert row.role == 'unassessed'


@pytest.mark.parametrize('element', [b'blockquote', b'q', b'pre', b'code', b'article'])
@pytest.mark.parametrize('kind', ['meeting', 'file'])
def test_quoted_alert_descendants_cannot_supply_house_diagnostics(kind, element):
    source = house_html(kind)
    source = source.replace(b"<div class='alert alert-error'>", b"<div class='alert alert-error'><"+element+b'>')
    source = source.replace(b'</span></div>', b'</span></'+element+b'></div>')
    row = assess_response(source, format='html')
    assert row.role == 'unassessed'
    panel, = [field for field in row.evidence if field['field'] == 'house_error_alert']
    assert panel['quoted_content'] is True


def test_quoted_diagnostic_phrase_is_unknown_but_real_heading_annotation_is_supported():
    source = house_html('meeting')
    assert b"<small class='text-tiny'><blockquote>" in source
    assert assess_response(source, format='html').reason == 'house_meeting_not_found'
    source = source.replace(b'[Meeting Not Found]', b'[<q>Meeting Not Found</q>]')
    assert assess_response(source, format='html').role == 'unassessed'


def test_house_panel_must_not_use_hidden_diagnostic_or_another_meetings_title():
    source = house_html('meeting').replace(b'[Meeting Not Found]', b'[<span hidden>Meeting Not Found</span>]')
    assert assess_response(source, format='html').role == 'unassessed'
    source = house_html('file').replace(b'<title>SST Full Committee Markup', b'<title>Other substantive meeting')
    assert assess_response(source, format='html').role == 'unassessed'


def test_house_content_uses_the_existing_evidence_budget():
    source = house_html('meeting').replace(b'<div id="DivMeetingContent">',
        b'<div id="DivMeetingContent">'+b'x'*MAX_EVIDENCE_TEXT_CHARS)
    row = assess_response(source, format='html')
    assert (row.role, row.reason) == ('unassessed', 'evidence_exceeds_assessment_bound')


def test_storage_error_requires_root_code_and_request_identity():
    source = b'<Error><Code>NoSuchKey</Code><Message/><RequestId>record-17</RequestId></Error>'
    row = assess_response(source, format='xml')
    assert (row.role, row.reason) == ('error_response', 'storage_NoSuchKey')
    assert row.body_sha256 == sha256(source).hexdigest()
    assert row.evidence[0] == dict(field='Code', byte_start=7, text='NoSuchKey')
    for body in [b'<hearing><title>NoSuchKey</title></hearing>',
                 b'<Error><Code>NoSuchKey</Code></Error>',
                 b'<Error><Code><quote>NoSuchKey</quote></Code><RequestId>x</RequestId></Error>',
                 b'<Error><Code>NoSuchKey</Code><Code>AccessDenied</Code><RequestId>x</RequestId></Error>']:
        assert assess_response(body, format='xml').role == 'unassessed'


def test_known_html_error_requires_publisher_heading_and_explanation():
    source = b'''<html><head><title>Error | House Committee on Natural Resources</title></head>
    <body><h1>Error</h1><h2>PAGE NOT FOUND</h2><p>It seems that you're looking for something
    that's either not here or has been moved.</p></body></html>'''
    assert assess_response(source, format='html').reason == 'natural_resources_not_found'
    for body in [source.replace(b'PAGE NOT FOUND', b'Hearing record'),
                 source.replace(b'Error | House Committee on Natural Resources', b'Testimony about web errors'),
                 b'<html><title>Access Denied</title><h1>Access Denied</h1><p>Hearing on barriers to health care.</p></html>',
                 b'<html><title>Response example</title><pre>&lt;Error&gt;NoSuchKey&lt;/Error&gt;</pre></html>']:
        assert assess_response(body, format='html').role == 'unassessed'


@pytest.mark.parametrize('source', [b'', b'<html><body></body></html>', b'<meeting/>', b'<playlist/>',
                                   b'<rss version="2.0"><channel/></rss>', b'%PDF-1.7 portfolio',
                                   b'<html><title>Short statement</title><p>I agree.</p></html>'])
def test_short_empty_and_container_inputs_are_not_error_documents(source):
    kind = 'html' if b'html' in source else 'xml'
    assert assess_response(source, format=kind).role in {'unassessed', 'empty_response'}


def test_feed_and_malformed_source_keep_different_outcomes():
    assert assess_response(b'<feed xmlns="http://www.w3.org/2005/Atom"><entry/></feed>', format='xml').role == 'feed'
    refused = assess_response(b'<!DOCTYPE Error [<!ENTITY x "NoSuchKey">]><Error>&x;</Error>', format='xml')
    assert refused.role == 'unassessed' and refused.reason == 'markup_reader_refused'
    assert assess_response(b'<html>\xff</html>', format='html').role == 'unassessed'
    assert assess_response(b'<Error/>', format='xml', max_bytes=4).reason == 'source_exceeds_assessment_bound'


def test_publisher_maintenance_is_waiting_not_missing():
    source = b'''<html><title>U.S. Senate: Site Under Maintenance</title><body><h1>
    WEBSITE TEMPORARILY UNAVAILABLE DUE TO MAINTENANCE.<br><br>Normal service will return soon.
    </h1></body></html>'''
    assert assess_response(source, format='html').role == 'wait_response'


def test_edge_error_is_distinct_from_access_denied_hearing_title():
    source = b'''<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD><BODY><H1>Access Denied</H1>
    You don't have permission to access this URL on this server.<P>https://errors.edgesuite.net/18.example</P>
    </BODY></HTML>'''
    assert assess_response(source, format='html').reason == 'edge_access_denied'
    assert assess_response(source.replace(b'https://errors.edgesuite.net/',
        b'https&#58;&#47;&#47;errors&#46;edgesuite&#46;net&#47;'), format='html').reason == 'edge_access_denied'
    assert assess_response(source.replace(b'You don\'t have permission to access', b'The witness explains access to'),
                           format='html').role == 'unassessed'


def test_inert_text_cannot_supply_error_heading_or_body():
    source = b'''<html><title>Error | House Committee on Natural Resources</title>
    <script>PAGE NOT FOUND either not here or has been moved</script><p>Substantive transcript.</p></html>'''
    assert assess_response(source, format='html').role == 'unassessed'


def test_cli_displays_original_identity_and_observation(tmp_path, capsys):
    import json
    from congress_api.cli.response_roles import main
    source = tmp_path / 'retained.xml'
    source.write_bytes(b'<Error><Code>NoSuchKey</Code><RequestId>x</RequestId></Error>')
    assert main([str(source), '--format', 'xml']) == 0
    row = json.loads(capsys.readouterr().out)
    assert row['source'] == str(source)
    assert row['body_sha256'] == sha256(source.read_bytes()).hexdigest()
    assert row['role'] == 'error_response'
    assert row['evidence'][0]['text'] == 'NoSuchKey'


def test_closed_ancestor_and_empty_headings_cannot_capture_later_text():
    source = (b'<html><title>Ordinary source</title>' + b'<div><h1></div>' * 100
              + b'<h2/>' + b'x' * 10_000 + b'</html>')
    row = assess_response(source, format='html')
    assert row.role == 'unassessed'
    assert sum(len(item['text']) for item in row.evidence) == len('ordinary source')
    assert all(not item['text'] for item in row.evidence if item['field'] != 'title')


def test_heading_evidence_has_its_own_text_and_field_bounds():
    for source in [b'<title>source</title>' + b'<h1>x</h1>' * MAX_EVIDENCE_FIELDS,
                   b'<h1>' * 10 + b'x' * (MAX_EVIDENCE_TEXT_CHARS // 10 + 1) + b'</h1>' * 10]:
        row = assess_response(source, format='html')
        assert (row.role, row.reason) == ('unassessed', 'evidence_exceeds_assessment_bound')


@pytest.mark.parametrize('source', [
    b'<Error>Substantive source text<Code>NoSuchKey</Code><RequestId>x</RequestId></Error>',
    b'<Error><Code>NoSuchKey</Code><Message/>Substantive source text<RequestId>x</RequestId></Error>',
    b'<Error><Code xmlns="urn:hearing-example">NoSuchKey</Code><RequestId>x</RequestId></Error>',
    b'<Error><Code>NoSuchKey</Code><RequestId xmlns="urn:hearing-example">x</RequestId></Error>',
    b'<Error xmlns:q="urn:hearing-example"><q:Code>NoSuchKey</q:Code><q:RequestId>x</q:RequestId></Error>',
])
def test_storage_role_rejects_mixed_root_content_and_foreign_fields(source):
    row = assess_response(source, format='xml')
    assert (row.role, row.reason) == ('unassessed', 'unqualified_error_structure')
