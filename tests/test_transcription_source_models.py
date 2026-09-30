"""Typed transcription inputs preserve source facts before normalization."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from congress_api.models.transcription import GeminiResponseCapture, Transcript, YoutubeVideoResponse, YtdlpVideoInfo
from congress_api.parsers.gemini import parse_generated_response as gemini_parse_generated_response
from congress_api.transcripts.render import TRANSCRIPT_JSON_SCHEMA
from congress_api.transport import gemini
from pydantic import ValidationError

RESEARCH = Path(__file__).parents[1] / 'docs/youtube-coverage/research/data/transcribe_compare'


@pytest.mark.parametrize('filename', ['routeA_text.json', 'routeA_video.json', 'gpo.json',
    'routeB.json', 'example_senate_audio.json', 'example_house_video.json'])
def test_existing_transcript_json_has_exact_semantic_roundtrip(filename):
    text = (RESEARCH / filename).read_text()
    source = Transcript.from_json(text)
    assert json.loads(source.to_json()) == json.loads(text)
    assert source.model_dump(mode='json') == json.loads(text)


def test_generated_response_preserves_unknown_fields_roles_and_numeric_kinds():
    payload = {'turns': [{'speaker': 'Someone', 'role': 'future-role', 'confidence': 0,
        'start': 0, 'end': 3.5, 'text': 'Original text', 'future': {'keep': [None]}}],
        'events': [{'seconds': 0.5, 'kind': 'future-event', 'text': 'Native event'}], 'new': False}
    source = gemini_parse_generated_response(json.dumps(payload))
    assert source.source_dict() == payload
    assert type(source.turns[0].start) is int
    payload['turns'][0]['start'] = '0'
    with pytest.raises(ValidationError):
        gemini_parse_generated_response(json.dumps(payload))


def test_successful_call_retains_complete_sdk_http_text_before_parse(tmp_path, monkeypatch):
    generated = '{ "turns": [], "events": [], "future": null }'
    raw = '{"candidates":[{"content":{"parts":[{"text":' + json.dumps(generated) + '} ]}}],"providerNew":{"a":1}}'
    response = SimpleNamespace(text=generated, sdk_http_response=SimpleNamespace(body=raw),
        candidates=[], usage_metadata=SimpleNamespace(prompt_token_count=5, candidates_token_count=7))
    configs = []
    def call(**kwargs):
        configs.append(kwargs['config'])
        return response
    monkeypatch.setattr(gemini, 'client', lambda: SimpleNamespace(models=SimpleNamespace(generate_content=call)))
    result = gemini.transcribe_window([], {}, 0, 5, youtube_id='example', capture_dir=tmp_path)
    assert result == {'turns': [], 'events': [], 'future': None, 'usage': {'in': 5, 'out': 7}}
    assert configs[0].should_return_http_response is True
    capture = GeminiResponseCapture.model_validate_json(next(tmp_path.glob('*.json')).read_text())
    assert capture.response.body_bytes() == raw.encode()
    assert capture.generated.body_bytes() == generated.encode()
    assert capture.observed_at and capture.start == 0 and capture.end == 5


def test_invalid_model_response_is_retained_then_raises(tmp_path, monkeypatch):
    response = SimpleNamespace(text='{bad JSON', sdk_http_response=None, candidates=[])
    monkeypatch.setattr(gemini, 'client', lambda: SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k: response)))
    monkeypatch.setattr(gemini.time, 'sleep', lambda n: None)
    with pytest.raises(gemini.TranscriptionWindowError, match='failed after retries'):
        gemini.transcribe_window([], {}, 0, 5, youtube_id='example', capture_dir=tmp_path)
    captures = [GeminiResponseCapture.model_validate_json(p.read_text()) for p in tmp_path.glob('*.json')]
    assert len(captures) == 2
    assert all(c.response is None and c.generated.body_bytes() == b'{bad JSON' for c in captures)


def test_youtube_complete_requested_part_roundtrips_and_native_aliases_stay_distinct():
    payload = {'kind': 'youtube#videoListResponse', 'etag': 'exact',
        'pageInfo': {'totalResults': 1, 'resultsPerPage': 5}, 'items': [{
        'id': 'id', 'kind': 'youtube#video', 'etag': 'item', 'contentDetails': {
            'duration': 'PT1H2M3S', 'dimension': '2d', 'definition': 'hd', 'caption': 'false',
            'licensedContent': True, 'regionRestriction': {'allowed': ['US']},
            'contentRating': {'ytRating': 'ytAgeRestricted', 'futureReasons': ['A']},
            'projection': 'rectangular', 'hasCustomThumbnail': False,
            'licensed_content': 'unrelated publisher key', 'future': [1, None]}}]}
    source = YoutubeVideoResponse.model_validate(payload)
    assert source.items[0].content_details.licensed_content is True
    assert source.source_dict() == payload
    with pytest.raises(ValidationError):
        YoutubeVideoResponse.model_validate({'items': [{'contentDetails': {'duration': 10}}]})


def test_ytdlp_result_keeps_extractor_specific_data():
    payload = {'id': 'v', 'duration': 0, 'formats': [{'height': None, 'url': 'exact'}],
        'automatic_captions': {'en': [{'ext': 'vtt', 'url': 'https://example.org/captions'}]}}
    assert YtdlpVideoInfo.model_validate(payload).source_dict() == payload


def test_transcript_schema_is_generated_from_the_actual_typed_reader():
    assert TRANSCRIPT_JSON_SCHEMA['properties'] == Transcript.model_json_schema()['properties']
    assert TRANSCRIPT_JSON_SCHEMA['$defs']['Turn']['properties']['text']['type'] == 'string'
