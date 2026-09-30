"""Transport failures and optional model accounting remain distinct from empty output."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from congress_api.parsers.senate_player import archive_url
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


def test_failed_local_encode_does_not_leave_cacheable_output(tmp_path, monkeypatch):
    source = tmp_path / 'hearing.mp4'
    source.write_bytes(b'fake')
    out_dir = tmp_path / 'audio'

    def fail(cmd, check=True):
        Path(cmd[-1]).write_bytes(b'partial')
        if check:
            raise RuntimeError('ffmpeg failed: encode error')
        return 1

    monkeypatch.setattr(audio, 'run', fail)
    with pytest.raises(RuntimeError, match='ffmpeg failed'):
        audio.get_audio(out_dir, local=str(source))
    assert not (out_dir / 'hearing.mp3').exists()
    assert not list(out_dir.glob('*.tmp'))


def test_failed_cut_does_not_leave_cacheable_piece(tmp_path, monkeypatch):
    path = tmp_path / 'hearing.mp3'
    path.write_bytes(b'audio')

    def fail(cmd, check=True):
        Path(cmd[-1]).write_bytes(b'partial')
        raise RuntimeError('ffmpeg failed: cut error')

    monkeypatch.setattr(audio, 'run', fail)
    with pytest.raises(RuntimeError, match='cut error'):
        audio.cut(path, 0, 10)
    assert not list(tmp_path.glob('hearing.*.mp3'))
    assert not list(tmp_path.glob('*.tmp'))


def test_senate_audio_skips_live_when_comm_lacks_live_id(tmp_path, monkeypatch):
    urls = []

    def capture(cmd, check=True):
        urls.append(cmd[cmd.index('-i') + 1])
        Path(cmd[-1]).write_bytes(b'mp3')
        return 0

    monkeypatch.setattr(audio, 'run', capture)
    path = audio.get_audio(
        tmp_path,
        senate_url='https://www.senate.gov/isvp/?comm=intlnarc&filename=intlnarc010126',
    )
    assert path.exists()
    assert urls == [archive_url('intlnarc', 'intlnarc010126')]


def test_senate_audio_rejects_unknown_committee(tmp_path):
    with pytest.raises(ValueError, match='Unsupported Senate player URL or committee'):
        audio.get_audio(tmp_path, senate_url='https://www.senate.gov/isvp/?comm=notacommittee&filename=x010126')


def test_youtube_proxy_does_not_disable_tls_verification(tmp_path, monkeypatch):
    import sys

    from congress_api.transcripts import generate as main

    seen = []
    video_id = 'abc123Video'

    class FakeYDL:
        def __init__(self, opts):
            seen.append(dict(opts))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            path = Path(seen[-1]['outtmpl'].replace('%(id)s', video_id).replace('%(ext)s', 'webm'))
            path.write_bytes(b'source')

        def extract_info(self, url, download=True):
            return {'id': video_id, 'duration': 90}

    monkeypatch.setitem(sys.modules, 'yt_dlp', SimpleNamespace(YoutubeDL=FakeYDL))
    monkeypatch.setattr(audio, 'run', lambda cmd, check=True: Path(cmd[-1]).write_bytes(b'mp3') or 0)
    monkeypatch.delenv('YOUTUBE_API_KEY', raising=False)

    out = audio.get_audio(tmp_path, video_id=video_id, proxy='socks5://127.0.0.1:1080')
    assert out.exists()
    assert main.video_duration(video_id, proxy='socks5://127.0.0.1:1080') == 90
    assert len(seen) == 2
    for opts in seen:
        assert opts['proxy'] == 'socks5://127.0.0.1:1080'
        assert 'nocheckcertificate' not in opts


def test_missing_gemini_api_key_raises_runtime_error(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr(gemini, '_client', None)
    with pytest.raises(RuntimeError, match='GEMINI_API_KEY is not set'):
        gemini.client()
