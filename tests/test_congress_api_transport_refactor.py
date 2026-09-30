"""Transport failures and optional model accounting remain distinct from empty output."""
from types import SimpleNamespace

import pytest

from congress_api.transport import audio, gemini


def test_failed_audio_probe_does_not_become_empty_transcription(tmp_path, monkeypatch):
    monkeypatch.setattr(audio.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=1, stdout='', stderr='invalid media'))
    with pytest.raises(RuntimeError, match='ffprobe failed: invalid media'):
        audio.chunks(tmp_path / 'broken.mp3')


@pytest.mark.parametrize('minutes', [0, -1, float('inf'), float('nan')])
def test_invalid_chunk_step_fails_before_probe(tmp_path, monkeypatch, minutes):
    monkeypatch.setattr(audio, 'duration', lambda _: pytest.fail('must reject before probing'))
    with pytest.raises(ValueError, match='minutes'):
        audio.chunks(tmp_path / 'audio.mp3', minutes=minutes)


@pytest.mark.parametrize('overlap', [-1, float('inf'), float('nan')])
def test_invalid_chunk_overlap_fails_before_probe(tmp_path, monkeypatch, overlap):
    monkeypatch.setattr(audio, 'duration', lambda _: pytest.fail('must reject before probing'))
    with pytest.raises(ValueError, match='overlap'):
        audio.chunks(tmp_path / 'audio.mp3', overlap=overlap)


@pytest.mark.parametrize('usage', [None, SimpleNamespace(prompt_token_count=None, candidates_token_count=7)])
def test_missing_usage_does_not_retry_or_discard_valid_turns(monkeypatch, usage):
    calls = []
    response = SimpleNamespace(text='{"turns":[{"speaker":"Chair","role":"chair",'
        '"confidence":1,"start":0,"text":"Call to order"}],"events":[]}',
        candidates=[], usage_metadata=usage)
    def generate(**kwargs):
        calls.append(kwargs)
        return response
    monkeypatch.setattr(gemini, 'client', lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr(gemini.time, 'sleep', lambda _: pytest.fail('valid output must not retry'))
    result = gemini.transcribe_window([], {}, 0, 5, youtube_id='example')
    assert result['turns'][0]['text'] == 'Call to order'
    assert result['usage'] == {'in': 0, 'out': 0 if usage is None else 7}
    assert len(calls) == 1
