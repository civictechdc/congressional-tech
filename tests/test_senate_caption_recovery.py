import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from congress_api.models.media import WebVTTCue
from congress_api.parsers.captions import IncompleteCaptionsError as captions_IncompleteCaptionsError
from congress_api.parsers.captions import cues as captions_cues
from congress_api.parsers.captions import parsed_cues as captions_parsed_cues
from congress_api.retention.captions import receipt_path as captions_receipt_path
from congress_api.transcripts import senate as captions
from congress_api.transport.senate import sess as captions_sess


def test_real_zero_duration_updates_survive_unchanged():
    raw = (Path(__file__).parent / 'fixtures/captions/senate-armedA040924-segment818.vtt').read_bytes()
    cues = captions_parsed_cues(raw.decode())
    zero = [cue for cue in cues if cue.start == cue.end]
    assert len(zero) == 51
    assert zero[0].start == '02:43:31.898'
    for cue in zero:
        assert WebVTTCue.model_validate(cue.source_dict()).source_dict() == cue.source_dict()
    assert captions_cues(raw.decode())


def test_backwards_timing_still_fails():
    with pytest.raises(captions_IncompleteCaptionsError, match='ends before'):
        captions_parsed_cues('WEBVTT\n\n00:00:02.000 --> 00:00:01.000\nbackwards\n')


def test_archive_only_committee_and_zero_duration_receipt(tmp_path, monkeypatch):
    master = 'https://www-senate-gov-msl3archive.akamaized.net/internationalnarcoticscaucus/intlnarc040924_1/master.m3u8'
    bodies = {master: '#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,URI="sub.m3u8"\n',
              master.replace('master.m3u8', 'sub.m3u8'): '#EXTM3U\n#EXTINF:1,\ncue.vtt\n#EXT-X-ENDLIST\n',
              master.replace('master.m3u8', 'cue.vtt'): 'WEBVTT\n\n00:00:01.000 --> 00:00:01.000\noriginal words\n'}
    def get(url, **kwargs):
        assert url in bodies
        return SimpleNamespace(status_code=200, text=bodies[url], content=bodies[url].encode(), headers={})
    monkeypatch.setattr(captions_sess, 'get', get)
    url = 'https://www.senate.gov/isvp/?comm=intlnarc&filename=intlnarc040924'
    result = captions.fetch_one(url, tmp_path, nthreads=1)
    assert result[2] == 'webvtt'
    receipt = json.loads(captions_receipt_path(tmp_path, url).read_text())
    assert receipt['zero_duration_cues'] == 1
    assert receipt['outcome'] == 'available'
    assert (tmp_path / 'intlnarc040924.txt').read_text() == 'original words\n'


def test_archive_only_negative_check_retains_checked_location(tmp_path, monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=404, text='missing', content=b'missing', headers={})

    monkeypatch.setattr(captions_sess, 'get', get)
    url = 'https://www.senate.gov/isvp/?comm=intlnarc&filename=intlnarc040924'
    captions.fetch_one(url, tmp_path, nthreads=1)
    receipt = json.loads(captions_receipt_path(tmp_path, url).read_text())
    assert len(calls) == 1
    assert '/internationalnarcoticscaucus/' in calls[0]
    assert receipt['scope']['master_url'] == calls[0]
    assert receipt['scope']['includes_embedded_archive_captions'] is False
    assert receipt['outcome'] == 'not_found'
    assert 'No checked master' in receipt['reason']


def test_failure_after_staged_gzip_keeps_previous_capture_bytes(tmp_path, monkeypatch):
    """Re-fetch must not replace .captions.json.gz until txt succeeds."""
    from congress_api.retention import captions as caption_store
    from test_senate_caption_checks import PLAYER, responses

    monkeypatch.setattr(captions_sess, 'get', responses())
    captions.fetch_one(PLAYER, tmp_path, nthreads=1)
    gzip_path = tmp_path / 'epw120623.captions.json.gz'
    previous = gzip_path.read_bytes()
    original_receipt = json.loads(captions_receipt_path(tmp_path, PLAYER).read_text())
    assert original_receipt['outcome'] == 'available'
    assert previous

    real_write = caption_store._write_text

    def fail_plain_text(path, text):
        if path.name.endswith('.txt') and not path.name.endswith('.cues.txt'):
            raise OSError('txt write failed after gzip staged')
        return real_write(path, text)

    monkeypatch.setattr(captions, '_write_text', fail_plain_text)
    with pytest.raises(OSError, match='txt write failed'):
        captions.fetch_one(PLAYER, tmp_path, nthreads=1)

    assert gzip_path.read_bytes() == previous
    assert not gzip_path.with_suffix(gzip_path.suffix + '.tmp').exists()
    error_receipt = json.loads(captions_receipt_path(tmp_path, PLAYER).read_text())
    assert error_receipt['outcome'] == 'error'
    assert error_receipt['last_successful']['source_file'] == 'epw120623.captions.json.gz'
    assert (tmp_path / error_receipt['last_successful']['source_file']).read_bytes() == previous


def test_main_passes_nthreads_into_segment_pool(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from test_senate_caption_checks import PLAYER, responses

    seen = []
    real = ThreadPoolExecutor

    class TrackingPool(real):
        def __init__(self, max_workers=None, *args, **kwargs):
            seen.append(max_workers)
            super().__init__(max_workers=max_workers, *args, **kwargs)

    monkeypatch.setattr(captions, 'ThreadPoolExecutor', TrackingPool)
    monkeypatch.setattr(captions_sess, 'get', responses())
    captions.main(tmp_path, [PLAYER], nthreads=3)
    # Recording pool and per-recording segment pool both receive CLI nthreads.
    assert seen == [3, 3]
