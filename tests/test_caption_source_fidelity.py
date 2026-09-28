"""Timed upstream caption text survives capture and numeric speech survives normalization."""
from pathlib import Path
import gzip
import json
import pytest
import yt_dlp

from congress_api.senate import captions as senate
from congress_shared.webvtt import cue_lines
from youtube_api.captions import main as youtube
from test_senate_caption_checks import PLAYER, MASTER_BODY, PLAYLIST_BODY, VTT1, VTT2, responses

VIDEO = 'abcdefghijk'
VTT = 'WEBVTT\nLanguage: en\n\ncue-1\n00:00:01.000 --> 00:00:02.000\n2025\nA &amp; B\n\nNOTE omitted metadata\nnot speech\n\n2\n00:00:02.000 --> 00:00:03.000\n<v Speaker>Thank you.</v>\n'


def test_text_parsers_keep_numeric_speech_and_decode_entities_without_cue_ids():
    assert cue_lines(VTT) == [['2025', 'A & B'], ['Thank you.']]
    assert senate.cues(VTT) == [['2025', 'A & B'], ['Thank you.']]
    assert youtube.vtt_to_text(VTT) == '2025\nA & B\nThank you.\n'
    with pytest.raises(ValueError):
        cue_lines('WEBVTT\n00:00:00.000 --> 00:00:01.000\ninvalid header')


def fake_ydl(monkeypatch, *, info=None, tracks=None, error=None):
    class Downloader:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download):
            if error:
                raise yt_dlp.utils.DownloadError(error)
            folder = Path(self.opts['outtmpl']).parent
            for language, body in (tracks or {}).items():
                (folder / f'{VIDEO}.{language}.vtt').write_text(body)
            return info or {}
    monkeypatch.setattr(youtube.yt_dlp, 'YoutubeDL', Downloader)


@pytest.mark.parametrize('message', ['HTTP Error 403: Forbidden', 'This video is private', 'Video unavailable', 'HTTP Error 429', 'Connection reset'])
def test_failed_youtube_acquisition_never_becomes_permanent_none(tmp_path, monkeypatch, message):
    fake_ydl(monkeypatch, error=message)
    assert youtube.fetch_one(VIDEO, tmp_path) == (VIDEO, 'error', 0)
    youtube.main(tmp_path, [VIDEO], nthreads=1)
    assert (tmp_path / youtube.INDEX).read_text().strip() == 'video_id,kind,characters'


def test_youtube_manual_track_is_selected_and_all_downloaded_timing_is_retained(tmp_path, monkeypatch):
    automatic = VTT.replace('Thank you.', 'Automatic track.')
    fake_ydl(monkeypatch, info={'subtitles': {'en-US': [{}]}, 'automatic_captions': {'en-orig': [{}]}},
             tracks={'en-US': VTT, 'en-orig': automatic})
    video, kind, characters = youtube.fetch_one(VIDEO, tmp_path)
    assert kind == 'manual'
    assert (tmp_path / f'{VIDEO}.txt').read_text() == youtube.vtt_to_text(VTT)
    assert characters == len(youtube.vtt_to_text(VTT))
    assert (tmp_path / 'tracks' / f'{VIDEO}.en-US.vtt').read_text() == VTT
    assert (tmp_path / 'tracks' / f'{VIDEO}.en-orig.vtt').read_text() == automatic


def test_declared_track_without_download_is_error_not_none(tmp_path, monkeypatch):
    fake_ydl(monkeypatch, info={'subtitles': {'en': [{}]}})
    assert youtube.fetch_one(VIDEO, tmp_path) == (VIDEO, 'error', 0)
    fake_ydl(monkeypatch, info={})
    assert youtube.fetch_one(VIDEO, tmp_path) == (VIDEO, 'none', 0)


def test_senate_capture_retains_playlists_segments_and_timestamps(tmp_path, monkeypatch):
    monkeypatch.setattr(senate.sess, 'get', responses())
    senate.fetch_one(PLAYER, tmp_path)
    retained = json.loads(gzip.decompress((tmp_path / 'epw120623.captions.json.gz').read_bytes()))
    assert retained['master']['text'] == MASTER_BODY
    assert retained['playlist']['text'] == PLAYLIST_BODY
    assert [x['text'] for x in retained['segments']] == [VTT1, VTT2]
    assert 'X-TIMESTAMP-MAP' in retained['segments'][0]['text']


def test_legacy_youtube_none_and_positive_without_vtt_recheck_without_duplicates(tmp_path, monkeypatch):
    for legacy_kind in ('none', 'auto'):
        (tmp_path / youtube.INDEX).write_text(f'video_id,kind,characters\n{VIDEO},{legacy_kind},0\n')
        (tmp_path / f'{VIDEO}.txt').write_text('Older retained text')
        receipt = tmp_path / youtube.RECEIPTS / f'{VIDEO}.json'
        receipt.unlink(missing_ok=True)
        fake_ydl(monkeypatch, info={'subtitles': {'en': [{}]}}, tracks={'en': VTT})
        assert youtube.main(tmp_path, [VIDEO], nthreads=1)['manual'] == 1
        assert len((tmp_path / youtube.INDEX).read_text().splitlines()) == 2
        capture = json.loads(receipt.read_text())
        assert capture['observed_at'] and capture['capture_version'] == youtube.CAPTURE_VERSION
        fake_ydl(monkeypatch, error='must not reacquire current complete capture')
        assert youtube.main(tmp_path, [VIDEO], nthreads=1)['error'] == 0
        (tmp_path / 'tracks' / capture['selected_track']).unlink()
        assert youtube.main(tmp_path, [VIDEO], nthreads=1)['error'] == 1
        assert (tmp_path / f'{VIDEO}.txt').read_text() == youtube.vtt_to_text(VTT)


def test_legacy_senate_positive_without_timed_source_is_rechecked(tmp_path, monkeypatch):
    (tmp_path / senate.INDEX).write_text('filename,comm,kind,characters\nepw120623,epw,webvtt,3\n')
    (tmp_path / 'epw120623.txt').write_text('old')
    monkeypatch.setattr(senate.sess, 'get', responses())
    assert senate.main(tmp_path, [PLAYER], nthreads=1)['webvtt'] == 1
    assert len((tmp_path / senate.INDEX).read_text().splitlines()) == 2
    assert (tmp_path / 'epw120623.captions.json.gz').exists()


def test_real_senate_vtt_preserves_25_timed_cues_and_rollup_text():
    raw = (Path(__file__).parent / 'fixtures/captions/senate-jec011724-segment101.vtt').read_text()
    lines = senate.cues(raw)
    assert len(lines) == 25
    assert senate.merge_rollup(lines) == (
        'HOUSING AS NEIGHBORS, TO EVEN\nRIGHT HERE DOWN THE STREET HERE\nIN VIRGINIA, WHERE THE\n'
        'NEIGHBORHOOD, VERY PROGRESSIVE\nIN VOTING ONE, BASICALLY OPPOSED\n.\nFOR THOSE OF US IN THE\n')
