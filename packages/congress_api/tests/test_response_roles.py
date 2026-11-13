"""Role observations must not turn document phrases or refusal into rejection."""
from hashlib import sha256

import pytest

from congress_api.parsers.response_roles import assess_response


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
