"""Source models retain publisher values before normalization and storage."""
import gzip
import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from congress_api.acquisition import senate as records
from congress_api.adapters.senate import records as adapt_records
from congress_api.models.content import RawContent
from congress_api.models.media import HLSRendition, SenateCaptionSources
from congress_api.models.senate import WORDPRESS_POSTS, SenatePage, SenateSite, WordPressPost, WordPressType
from congress_api.parsers.captions import IncompleteCaptionsError as captions_IncompleteCaptionsError
from congress_api.parsers.captions import _subtitle_uri as captions__subtitle_uri
from congress_api.parsers.captions import parsed_cues as captions_parsed_cues
from congress_api.parsers.senate import parse_page as records_parse_page
from congress_api.retention.captions import receipt_path as captions_receipt_path
from congress_api.retention.tables import read_state
from congress_api.transcripts import senate as captions
from congress_api.transport import http as records_http
from congress_api.transport.senate import sess as captions_sess
from pydantic import ValidationError
from test_explorer_senate_adapter import adapt, context, of_kind, retained_page
from test_senate_caption_checks import MASTER, MASTER_BODY, PLAYER, responses
from test_senate_record_receipts import HOST, HTML, PAGE, setup_inputs

FIXTURES = Path(__file__).parent / 'fixtures'
SOURCES = FIXTURES / 'source_models'


def test_original_link_occurrences_are_typed_and_lossless():
    raw = b'<title>Hearing</title><section><h2>Related Files</h2><a href="/a.pdf">Article</a></section>'
    model = records_parse_page(raw, PAGE)
    metadata = model.document_metadata[PAGE.split('/hearings')[0] + '/a.pdf']
    assert metadata.occurrences[0].headings == ['Related Files']
    assert metadata.occurrences[0].labels == ['Article']
    assert not metadata.model_extra
    assert SenatePage.model_validate(model.source_dict()).source_dict() == model.source_dict()


@pytest.mark.parametrize('fixture', sorted((FIXTURES / 'meeting_inventory').glob('senate-*.html')))
def test_every_retained_page_layout_is_a_lossless_native_model(fixture):
    original = fixture.read_bytes()
    model = records_parse_page(original, 'https://example.senate.gov/hearings/evidence')
    assert isinstance(model, SenatePage)
    assert model.raw_html.body_bytes() == original
    assert model.raw_html.sha256 == RawContent.from_bytes(original, 'text/html').sha256
    expected = model.source_dict()
    source, = of_kind(adapt(model), 'source_record')
    assert source.payload == expected
    assert SenatePage.model_validate_json(json.dumps(source.payload)).source_dict() == expected


def test_html_bytes_that_are_not_utf8_fail_instead_of_replacing():
    raw = b'<title>Source title</title>\r\n<p>Original \x96 bytes</p><script>all original JS</script>'
    with pytest.raises(UnicodeDecodeError):
        records_parse_page(raw, PAGE)
    # Valid UTF-8 still retains exact source bytes beside the parse.
    utf8 = '<title>Source title</title>\r\n<p>Original – bytes</p><script>all original JS</script>'.encode()
    page = records_parse_page(utf8, PAGE)
    assert page.raw_html.body_bytes() == utf8
    source, = of_kind(adapt(page), 'source_record')
    assert RawContent.model_validate(source.payload['raw_html']).body_bytes() == utf8


def test_archived_help_page_keeps_displayed_event_date_and_type():
    raw = (SOURCES / 'senate-help-executive-session-20230615.html').read_bytes()
    url = 'https://www.help.senate.gov/hearings/s-133-s-134-s-265-s-1844-s-1852-and-s-1855'
    page = records_parse_page(raw, url)
    assert page.event.date == '2023-06-15'
    assert page.event.date_text == 'Thursday, June 15th, 2023'
    assert page.event.type == 'Executive Session'
    assert page.event.title == 'S. 133, S. 134, S. 265, S. 1844, S. 1852, and S. 1855'
    assert len(page.documents) == 3
    assert SenatePage.model_validate(page.source_dict()).source_dict() == page.source_dict()
    assert page.raw_html.body_bytes() == raw
    # An unrelated date outside the recognized hearing details cannot admit an event.
    unrelated = raw.replace(b'Hearing__details', b'Unrelated__details')
    assert records_parse_page(unrelated, url).event is None


def test_native_site_and_page_models_have_the_same_normalization_as_dictionaries():
    page = records_parse_page(HTML, PAGE)
    state = {HOST: {'pages': {PAGE: page.source_dict()}}}
    modeled = {HOST: SenateSite(pages={PAGE: page})}
    assert list(adapt_records(state, context(), meetings={})) == list(adapt_records(modeled, context(), meetings={}))


def test_real_wordpress_posts_and_nested_acf_roundtrip_without_changes():
    for file in ('senate-wordpress-post-response.json', 'senate-wordpress-posts.json'):
        raw = json.loads((SOURCES / file).read_text())
        models = WORDPRESS_POSTS.validate_python(raw)
        assert [model.source_dict() for model in models] == raw
        assert all(not model.model_extra for model in models)
    raw = json.loads((SOURCES / 'senate-wordpress-type.json').read_text())
    model = WordPressType.model_validate(raw)
    assert model.yoast_head_json.schema_data.graph
    assert model.source_dict() == raw


def test_new_source_fields_and_python_alias_collisions_are_never_renamed_or_lost():
    raw = json.loads((SOURCES / 'senate-wordpress-type.json').read_text())
    raw['links'] = {'publisher_added': [None, False, 12, 'literal']}
    raw['yoast_head_json']['schema_data'] = 'separate publisher key'
    raw['yoast_head_json']['schema']['graph'] = 'also separate'
    assert WordPressType.model_validate(raw).source_dict() == raw
    raw.pop('_links')
    assert WordPressType.model_validate(raw).source_dict() == raw


def test_malformed_nested_source_values_fail_without_string_coercion():
    post = json.loads((SOURCES / 'senate-wordpress-post-response.json').read_text())[0]
    post = deepcopy(post)
    post['acf']['witness_1'] = [{'witness_name': 123}]
    with pytest.raises(ValidationError, match='witness_name'):
        WordPressPost.model_validate(post)
    page = records_parse_page(HTML, PAGE).source_dict()
    page['document_metadata'] = {'https://example.gov/doc.pdf': {'labels': [], 'attributes': [], 'container_attributes': [], 'witness_indexes': [-1]}}
    with pytest.raises(ValidationError, match='witness_indexes'):
        SenatePage.model_validate(page)
    with pytest.raises(ValidationError, match='URI'):
        HLSRendition.model_validate({'TYPE': 'SUBTITLES', 'URI': {'url': 'bad'}})


def test_collector_retains_complete_wordpress_response_through_saved_state_and_adapter(tmp_path, monkeypatch):
    args = setup_inputs(tmp_path, saved=False)
    url = 'https://www.hsgac.senate.gov/wp-json/wp/v2/hearings_bmfwra?per_page=100&page=1&_fields=link,title,acf'
    raw = (SOURCES / 'senate-wordpress-post-response.json').read_bytes()
    def listing(host, get, saved):
        captured = get(url)
        assert [post.source_dict() for post in WORDPRESS_POSTS.validate_json(captured)] == json.loads(raw)
        return [(date(2026, 9, 20), PAGE, 'Retained hearing')], {'wordpress': True}
    def request(_session, requested, **kwargs):
        return SimpleNamespace(status_code=200, content=raw if requested == url else HTML)
    monkeypatch.setattr(records, 'listed', listing)
    monkeypatch.setattr(records_http, 'get_with_retry', request)
    monkeypatch.setattr("congress_api.matching.senate_pages.match_pages", lambda *args: ([], [], []))
    records.main(**args)
    state = read_state(tmp_path / 'senate.json.gz')
    body = state[HOST]['source_bodies'][url]
    assert RawContent.model_validate(body).body_bytes() == raw
    sources = of_kind(list(adapt_records(state, context(), meetings={})), 'source_record')
    source, = [source for source in sources if 'source_bodies' in source.payload]
    assert source.payload['source_bodies'][url] == body
    assert RawContent.model_validate(source.payload['source_bodies'][url]).body_bytes() == raw


def test_caption_response_bytes_and_uninterpreted_source_metadata_are_retained(tmp_path, monkeypatch):
    serve = responses()
    original_master = ('\ufeff' + MASTER_BODY.replace('\n', '\r\n') + '#PUBLISHER-EXTENSION:literal=12\r\n').encode()
    def get(url, **kwargs):
        response = serve(url, **kwargs)
        body = original_master if url == MASTER else response.text.encode()
        return SimpleNamespace(status_code=response.status_code, text=body.decode(), content=body, headers={})
    monkeypatch.setattr(captions_sess, 'get', get)
    captions.fetch_one(PLAYER, tmp_path)
    raw = json.loads(gzip.decompress((tmp_path / 'epw120623.captions.json.gz').read_bytes()))
    source = SenateCaptionSources.model_validate(raw)
    assert source.source_dict() == raw
    assert source.master.raw_body.body_bytes() == original_master
    assert all(part.raw_body.body_bytes() == part.text.encode() for part in source.segments)


def test_real_webvtt_cues_keep_timing_identifier_settings_and_literal_text():
    body = (FIXTURES / 'captions/senate-jec011724-segment101.vtt').read_text()
    cues = captions_parsed_cues(body)
    assert len(cues) == 25
    assert cues[0].start and cues[0].end
    raw = 'WEBVTT\n\nsource-cue-1\n00:00:01.000 --> 00:00:03.000 align:start line:90%\n<v Speaker>A &amp; B</v>\n'
    cue, = captions_parsed_cues(raw)
    assert cue.source_dict() == {'start': '00:00:01.000', 'end': '00:00:03.000', 'text': ['<v Speaker>A &amp; B</v>'], 'identifier': 'source-cue-1', 'settings': 'align:start line:90%'}


@pytest.mark.parametrize('body', [b'<p>Unknown new layout with source facts</p>', b'%PDF-1.7\nunsupported binary\x00\xff'])
def test_rejected_senate_response_preserves_exact_attempt_without_replacing_prior_page(tmp_path, monkeypatch, body):
    args = setup_inputs(tmp_path)
    original = read_state(tmp_path / 'senate.json.gz')[HOST]['pages'][PAGE]
    monkeypatch.setattr(records_http, 'get_with_retry', lambda *args, **kwargs: SimpleNamespace(status_code=200, content=body, headers={}))
    with pytest.raises(RuntimeError):
        records.main(**args)
    host = read_state(tmp_path / 'senate.json.gz')[HOST]
    saved = host['pages'][PAGE]
    assert all(saved[key] == value for key, value in original.items() if key not in ('events', 'candidate_events', 'match_details', 'last_check', 'observation_check', 'cache_replay'))
    assert 'events' not in saved and host['workflow'][PAGE]['events'] == original['events']
    receipt, = host['workflow'][PAGE]['last_check']['receipts']
    assert RawContent.model_validate(receipt['raw_body']).body_bytes() == body
    source, = of_kind(list(adapt_records({HOST: {'pages': {PAGE: SenatePage.model_validate(saved)}}}, context(), meetings={})), 'source_record')
    assert source.payload == saved


def test_rejected_caption_body_is_retained_with_failure_receipt(tmp_path, monkeypatch):
    body = b'<html>Unrecognized stream response\r\n</html>'
    monkeypatch.setattr(captions_sess, 'get', lambda *args, **kwargs: SimpleNamespace(status_code=200, text=body.decode(), content=body, headers={'Content-Type': 'text/html'}))
    with pytest.raises(captions_IncompleteCaptionsError):
        captions.fetch_one(PLAYER, tmp_path)
    receipt = json.loads(captions_receipt_path(tmp_path, PLAYER).read_text())
    from congress_api.parsers.senate_player import archive_url
    assert [source['url'] for source in receipt['source_responses']] == [MASTER, archive_url('epw', 'epw120623')]
    for source in receipt['source_responses']:
        assert RawContent.model_validate(source['raw_body']).body_bytes() == body
    assert receipt['outcome'] == 'error' and 'kind' not in receipt
    assert not (tmp_path / 'epw120623.txt').exists()


def test_real_appropriations_section_heading_is_not_the_testimony_title():
    page = records_parse_page((FIXTURES / 'meeting_inventory/senate-2.html').read_bytes(), PAGE)
    saved = page.source_dict()
    saved['events'] = ['12']
    assert page.documents[0][1] == 'Witnesses'
    assert page.document_metadata[page.documents[0][2]].labels == ['Download Testimony']
    result = adapt(saved)
    material, = of_kind(result, 'material')
    assert material.title == 'Deb Haaland — Witness statement'
    # Normalized presentation does not mutate source triples, hash-based IDs or labels.
    source = retained_page(result, saved)
    assert source.payload == page.source_dict()
    assert saved == {**page.source_dict(), 'events': ['12']}
    previous = page.source_dict()
    previous.pop('document_metadata')  # Same source document, without the explicit owner correction.
    material_again, = of_kind(adapt(previous), 'material')
    assert material_again.title == 'Witnesses'
    assert material_again.id == material.id


def test_real_appropriations_player_keeps_empty_start_and_wmode():
    from congress_api.parsers.senate_player import parse_player_query, parse_player_url
    url = 'https://www.senate.gov/isvp/?comm=approps&type=arch&stt=&filename=appropsA032923&auto_play=false&wmode=transparent&poster=https%3A%2F%2Fwww%2Eappropriations%2Esenate%2Egov%2Fthemes%2Fappropriations%2Fimages%2Fvideo%2Dposter%2Dflash%2Dfit%2Epng'
    query = parse_player_query(url)
    assert query.source_dict()['stt'] == ''
    assert query.wmode == 'transparent' and not query.model_extra
    assert query.type == 'arch' and query.auto_play == 'false'
    assert parse_player_url(url) == ('approps', 'appropsA032923')


@pytest.mark.parametrize('fixture,host,form,expected', [
    ('senate-listing-anchor-time.html', 'foreign.senate.gov', '/hearings?PageNum_rs={}', ['2019-06-26', '2019-06-25', '2019-06-20']),
    ('senate-listing-table-date.html', 'epw.senate.gov', '/public/index.cfm/hearings?page={}', ['2019-10-16', '2019-09-25', '2019-09-18']),
])
def test_real_listing_rows_use_their_own_date_not_the_previous_row(fixture, host, form, expected):
    body = (SOURCES / fixture).read_text()
    rows = records.listing_page(host, form, 1, lambda url: body)
    assert [day.isoformat() for day, url, title in rows] == expected


def test_real_hls_rendition_and_empty_segment_remain_distinct_from_absence():
    import re
    master = (FIXTURES / 'captions/senate-jec011724-master.m3u8').read_text()
    attrs = dict((name, value.strip('"')) for name, value in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', master.split('#EXT-X-MEDIA:', 1)[1]))
    model = HLSRendition.model_validate(attrs)
    assert model.source_dict() == attrs
    assert model.language == 'eng' and model.group_id == 'subs' and model.default == 'YES'
    assert captions__subtitle_uri(master) == 'master/text_1.m3u8'
    empty = (FIXTURES / 'captions/senate-jec011724-segment1.vtt').read_text()
    assert 'MPEGTS:183000' in empty
    assert captions_parsed_cues(empty) == []


def test_real_forbidden_html_does_not_replace_a_good_hearing_under_http200(tmp_path, monkeypatch):
    raw = (SOURCES / 'senate-error-forbidden.html').read_bytes()
    model = records_parse_page(raw, PAGE)
    assert model.title == '403 Forbidden' and model.raw_html.body_bytes() == raw
    args = setup_inputs(tmp_path)
    previous = read_state(tmp_path / 'senate.json.gz')[HOST]['pages'][PAGE]
    monkeypatch.setattr(records_http, 'get_with_retry', lambda *args, **kwargs: SimpleNamespace(status_code=200, content=raw))
    with pytest.raises(RuntimeError, match='Unrecognized'):
        records.main(**args)
    host = read_state(tmp_path / 'senate.json.gz')[HOST]
    retained = host['pages'][PAGE]
    assert all(retained[key] == value for key, value in previous.items() if key not in ('events', 'candidate_events', 'match_details', 'last_check', 'observation_check', 'cache_replay'))
    assert host['workflow'][PAGE]['events'] == previous['events']
    receipt, = host['workflow'][PAGE]['last_check']['receipts']
    assert receipt['outcome'] == 'unrecognized_page'
    assert RawContent.model_validate(receipt['raw_body']).body_bytes() == raw


def test_real_coldfusion_listing_error_retains_old_listing_and_error_body(tmp_path, monkeypatch):
    raw = (SOURCES / 'senate-error-listing.html').read_bytes()
    assert records.listing_page(HOST, '/hearings?PageNum_rs={}', 0, lambda url: raw.decode()) == []
    args = setup_inputs(tmp_path, listing_checked='2026-09-01')
    previous = read_state(tmp_path / 'senate.json.gz')[HOST]
    url = 'https://www.budget.senate.gov/hearings?PageNum_rs=0'
    monkeypatch.setattr(records, 'listed', lambda host, get, saved: (records.listing_page(host, '/hearings?PageNum_rs={}', 0, get), {}))
    monkeypatch.setattr(records_http, 'get_with_retry', lambda *args, **kwargs: SimpleNamespace(status_code=200, content=raw))
    with pytest.raises(RuntimeError, match='returned no hearings'):
        records.main(**args)
    retained = read_state(tmp_path / 'senate.json.gz')[HOST]
    assert retained['listings'] == previous['listings']
    assert {url: {key: value for key, value in page.items() if key != 'events'} for url, page in retained['pages'].items()} == {
        url: {key: value for key, value in page.items() if key != 'events'} for url, page in previous['pages'].items()}
    assert retained['workflow'][PAGE]['events'] == ['1'] and 'events' not in retained['pages'][PAGE]
    assert retained['checked'] == previous['checked']
    assert retained['last_check']['outcome'] == 'error'
    assert RawContent.model_validate(retained['source_bodies'][url]).body_bytes() == raw
