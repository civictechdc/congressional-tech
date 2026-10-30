"""Diagnostic candidates stay retained without becoming routine downloads."""

import pytest

from congress_api.parsers.archive_links import allowed_url, capture_links, json_links, related_links


@pytest.mark.parametrize('url', [
    'https://example.gov/a.xmlhttps://example.gov/b.xml',
    'https://example.gov/a.xmlhttps:/example.gov/b.xml',
    'https://example.gov/a.xmlhttp://example.gov/b.xml',
])
def test_concatenated_schemes_in_path_are_not_download_urls(url):
    assert allowed_url(url) is None


def test_query_embedded_url_remains_a_valid_download_url():
    url = 'https://example.gov/download?url=https://example.gov/file.xml'
    assert allowed_url(url) == url


@pytest.mark.parametrize('prefix', [
    'https://web.archive.org/web/20250610160415id_/',
    'https://web.archive.org/web/20250610160415/',
    'https://webarchive.loc.gov/all/20110707213402/',
])
def test_timestamped_archive_replay_retains_archive_and_original_urls(prefix):
    url = prefix + 'https://example.gov/statement.pdf?edition=1'
    assert allowed_url(url) == url
    assert capture_links({'url': url}) == [{'url': url}]


@pytest.mark.parametrize('url', [
    'https://web.archive.org.evil.example/web/20250610160415/https://example.gov/a.pdf',
    'https://web.archive.org:8443/web/20250610160415/https://example.gov/a.pdf',
    'https://web.archive.org/web/*/https://example.gov/a.pdf',
    'https://web.archive.org/web/2025/https://example.gov/a.pdf',
    'https://web.archive.org/save/https://example.gov/a.pdf',
    'https://webarchive.loc.gov/other/20110707213402/https://example.gov/a.pdf',
    'https://web.archive.org/web/20250610160415/http://127.0.0.1/a.pdf',
    'https://web.archive.org/web/20250610160415/http://localhost/a.pdf',
    'https://web.archive.org/web/20250610160415/https://user:pass@example.gov/a.pdf',
    'https://web.archive.org/web/20250610160415/https://example.gov/a.pdf?token=secret',
    'https://web.archive.org/web/20250610160415/https://example.gov/a.xmlhttps://example.gov/b.xml',
    'https://web.archive.org/web/20250610160415/https://example.gov/a.mp4',
    'https://web.archive.org/web/20250610160415/https://api.govinfo.gov/a.xml',
    'https://web.archive.org/web/20250610160415/https://webarchive.loc.gov/all/20110707213402/https://example.gov/a.pdf',
    'https://web.archive.org/web/20250610160415/https://[bad/a.pdf',
])
def test_archive_layout_does_not_bypass_original_url_restrictions(url):
    assert allowed_url(url) is None


# Literal malformed publisher values found in failed CI run 37420553827.
GPO_PDF = 'https://www.gpo.gov/fdsys/pkg/BILLS-114hr456ih/pdf/BILLS-114hr456ih.pdf'
GPO_XML = [f'https://www.gpo.gov/fdsys/pkg/BILLS-115s585{version}/xml/BILLS-115s585{version}.xml'
           for version in ('rfh', 'es')]
LIS_WRAPPER = 'https://www.lis.gov/cgi-lis/t2GPO/' + GPO_PDF
CONCATENATED = ''.join(GPO_XML)


@pytest.mark.parametrize('original, targets, reason', [
    (LIS_WRAPPER, [GPO_PDF], 'lis_gpo_wrapper'),
    (CONCATENATED, GPO_XML, 'concatenated_file_urls'),
])
def test_known_source_defects_recover_literal_targets_with_provenance(original, targets, reason):
    item = {'url': original, 'pointer': ['documents', 0], 'text': 'Publisher label'}
    links = capture_links(item)
    assert [link['url'] for link in links] == targets
    for position, link in enumerate(links):
        assert link == {**item, 'url': targets[position], 'original_url': original,
                        'url_repair': reason, 'url_position': position}
    assert allowed_url(original) is None  # The transport guard remains strict.
    assert item['url'] == original


@pytest.mark.parametrize('value', [
    'https://example.gov/a.xmlhttps:/example.gov/b.xml',
    'https://example.gov/wrapper/https://example.gov/b.xml',
    'https://example.gov/a.xmlhttps://127.0.0.1/b.xml',
    'https://example.gov/a.xmlhttps://user:pass@example.gov/b.xml',
    'https://example.gov/a.xmlhttps://example.gov/b.mp4',
    'https://example.gov/a.xmlhttps://api.govinfo.gov/b.xml',
    'https://example.gov/a.xmlhttps://example.gov/b.xml?token=secret',
    'https://example.gov/a.xmlhttps://example.gov/b.xml#fragment',
    'https://example.gov/a.xml https://example.gov/b.xml',
    'https://www.lis.gov/cgi-lis/t2GPO/https://example.gov/b.pdf',
    'https://www.lis.gov/cgi-lis/t2GPO/https://www.gpo.gov/other/b.pdf',
    'https://www.lis.gov/cgi-lis/t2GPO/https://[bad/b.pdf',
    'https://lis.gov.evil.example/cgi-lis/t2GPO/' + GPO_PDF,
    'https://user:pass@www.lis.gov/cgi-lis/t2GPO/' + GPO_PDF,
    'not-a-url' + GPO_PDF,
])
def test_ambiguous_or_disallowed_values_are_not_partially_repaired(value):
    assert capture_links({'url': value}) == []


def test_valid_query_embedded_url_is_not_split_or_unwrapped():
    url = 'https://example.gov/download?url=https://example.gov/file.xml'
    assert capture_links({'url': url}) == [{'url': url}]


@pytest.mark.parametrize('original, targets', [(LIS_WRAPPER, [GPO_PDF]), (CONCATENATED, GPO_XML)])
def test_discovery_repairs_json_xml_html_and_keeps_source_evidence(original, targets):
    import json
    native = {'url': original, 'label': 'Original label'}
    json_items = list(json_links({'documents': [native]}, 'fixture.json'))
    xml_items = related_links(f'<bill><document href="{original}"/></bill>'.encode(),
                             'https://example.gov/bill.xml', 'xml')
    html_items = related_links(f'<a href="{original}">Download</a>'.encode(),
                              'https://example.gov/bill.html', 'html')
    for links in (json_items, xml_items, html_items):
        assert [link['url'] for link in links] == targets
        assert all(link['original_url'] == original for link in links)
    assert json_items[0]['native'] == native
    assert xml_items[0]['attributes']['href'] == original
    assert html_items[0]['attributes']['href'] == original
    # The same JSON source path is used by retained body discovery.
    assert related_links(json.dumps({'documents': [native]}).encode(), 'fixture.json', 'json') == json_items
