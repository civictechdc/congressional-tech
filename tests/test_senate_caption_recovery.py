from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from congress_api.senate import captions
from congress_api.models.media import WebVTTCue


def test_real_zero_duration_updates_survive_unchanged():
    raw = (Path(__file__).parent / 'fixtures/captions/senate-armedA040924-segment818.vtt').read_bytes()
    cues = captions.parsed_cues(raw.decode())
    zero = [cue for cue in cues if cue.start == cue.end]
    assert len(zero) == 51
    assert zero[0].start == '02:43:31.898'
    for cue in zero:
        assert WebVTTCue.model_validate(cue.source_dict()).source_dict() == cue.source_dict()
    assert captions.cues(raw.decode())


def test_backwards_timing_still_fails():
    with pytest.raises(captions.IncompleteCaptionsError, match='ends before'):
        captions.parsed_cues('WEBVTT\n\n00:00:02.000 --> 00:00:01.000\nbackwards\n')


def test_archive_only_committee_and_zero_duration_receipt(tmp_path, monkeypatch):
    master = 'https://www-senate-gov-msl3archive.akamaized.net/internationalnarcoticscaucus/intlnarc040924_1/master.m3u8'
    bodies = {master: '#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,URI="sub.m3u8"\n',
              master.replace('master.m3u8', 'sub.m3u8'): '#EXTM3U\n#EXTINF:1,\ncue.vtt\n#EXT-X-ENDLIST\n',
              master.replace('master.m3u8', 'cue.vtt'): 'WEBVTT\n\n00:00:01.000 --> 00:00:01.000\noriginal words\n'}
    def get(url, **kwargs):
        assert url in bodies
        return SimpleNamespace(status_code=200, text=bodies[url], content=bodies[url].encode(), headers={})
    monkeypatch.setattr(captions.sess, 'get', get)
    url = 'https://www.senate.gov/isvp/?comm=intlnarc&filename=intlnarc040924'
    result = captions.fetch_one(url, tmp_path, nthreads=1)
    assert result[2] == 'webvtt'
    receipt = json.loads(captions.receipt_path(tmp_path, url).read_text())
    assert receipt['zero_duration_cues'] == 1
    assert receipt['outcome'] == 'available'
    assert (tmp_path / 'intlnarc040924.txt').read_text() == 'original words\n'


def test_archive_only_negative_check_retains_checked_location(tmp_path, monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=404, text='missing', content=b'missing', headers={})

    monkeypatch.setattr(captions.sess, 'get', get)
    url = 'https://www.senate.gov/isvp/?comm=intlnarc&filename=intlnarc040924'
    captions.fetch_one(url, tmp_path, nthreads=1)
    receipt = json.loads(captions.receipt_path(tmp_path, url).read_text())
    assert len(calls) == 1
    assert '/internationalnarcoticscaucus/' in calls[0]
    assert receipt['scope']['master_url'] == calls[0]
    assert receipt['scope']['includes_embedded_archive_captions'] is False
    assert receipt['outcome'] == 'not_found'
    assert 'No checked master' in receipt['reason']
