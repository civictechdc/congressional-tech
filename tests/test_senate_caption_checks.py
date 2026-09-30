from congress_api.retention import captions as caption_store

"""Caption acquisition failures must never become permanent negative index rows."""
import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
from congress_api.parsers.captions import IncompleteCaptionsError as captions_IncompleteCaptionsError
from congress_api.parsers.senate_player import archive_url, live_url
from congress_api.retention.captions import receipt_path as captions_receipt_path
from congress_api.transcripts import senate as captions
from congress_api.transport.senate import get as captions_get
from congress_api.transport.senate import sess as captions_sess

PLAYER = "https://www.senate.gov/isvp/?comm=epw&filename=epw120623"
MASTER = live_url("epw", "epw120623")
PLAYLIST = MASTER.rsplit("/", 1)[0] + "/subtitles/eng.m3u8"
SEGMENT1 = PLAYLIST.rsplit("/", 1)[0] + "/one.vtt"
SEGMENT2 = PLAYLIST.rsplit("/", 1)[0] + "/two.vtt"
MASTER_BODY = '#EXTM3U\n#EXT-X-MEDIA:URI="subtitles/eng.m3u8",TYPE=SUBTITLES,LANGUAGE="en"\n'
PLAYLIST_BODY = "#EXTM3U\n#EXTINF:6,\none.vtt\n#EXTINF:6,\ntwo.vtt\n#EXT-X-ENDLIST\n"
VTT1 = "WEBVTT\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:0\n\n00:00:00.000 --> 00:00:03.000\nThe hearing\n\n"
VTT2 = "WEBVTT\n\n00:00:03.000 --> 00:00:06.000\nThe hearing begins.\n\n"


def response(status, body=""):
    return SimpleNamespace(status_code=status, text=body)


def responses(changes=None):
    values = {
        MASTER: response(200, MASTER_BODY), archive_url("epw", "epw120623"): response(404), PLAYLIST: response(200, PLAYLIST_BODY),
        SEGMENT1: response(200, VTT1), SEGMENT2: response(200, VTT2),
    }
    values.update(changes or {})

    def fetch(url, **kwargs):
        value = values[url]
        if isinstance(value, Exception):
            raise value
        return value
    return fetch


class GetTests(unittest.TestCase):
    def test_only_confirmed_404_returns_empty(self):
        with patch.object(captions_sess, "get", return_value=response(404)) as request:
            self.assertEqual(captions_get("https://example.gov/missing"), "")
        self.assertEqual(request.call_count, 1)

    def test_exhausted_http_and_request_errors_raise(self):
        for value in (response(503, "unavailable"), requests.Timeout("timeout"), response(200, "")):
            with self.subTest(value=value):
                kwargs = {"side_effect": value} if isinstance(value, Exception) else {"return_value": value}
                with patch.object(captions_sess, "get", **kwargs) as request:
                    with self.assertRaises(requests.RequestException):
                        captions_get("https://example.gov/failure")
                self.assertEqual(request.call_count, 3)

    def test_transient_error_can_recover_within_existing_retry_budget(self):
        with patch.object(captions_sess, "get", side_effect=[requests.Timeout(), response(200, MASTER_BODY)]) as request:
            self.assertEqual(captions_get(MASTER), MASTER_BODY)
        self.assertEqual(request.call_count, 2)


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)

    def receipt(self, url=PLAYER):
        return json.loads(captions_receipt_path(self.out, url).read_text())

    def test_complete_acquisition_has_precise_scoped_receipt(self):
        instant = datetime(2026, 9, 27, 18, 23, 19, 123456, tzinfo=timezone.utc)
        with patch.object(captions_sess, "get", side_effect=responses()), patch.object(caption_store, "datetime") as clock:
            clock.now.return_value = instant
            result = captions.fetch_one(PLAYER, self.out)
        self.assertEqual(result, ("epw120623", "epw", "webvtt", len("The hearing begins.\n")))
        self.assertEqual((self.out / "epw120623.txt").read_text(), "The hearing begins.\n")
        receipt = self.receipt()
        self.assertEqual(receipt["observed_at"], "2026-09-27T18:23:19.123456Z")
        self.assertEqual(receipt["outcome"], "available")
        self.assertEqual(receipt["player_url"], PLAYER)
        self.assertEqual(receipt["scope"]["segment_urls"], [SEGMENT1, SEGMENT2])
        self.assertFalse(receipt["scope"]["includes_embedded_archive_captions"])
        self.assertEqual(receipt["scope"]["playlist_url"], PLAYLIST)

    def test_master_404_and_confirmed_no_track_are_bounded_negatives(self):
        for master in (response(404), response(200, "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nvideo.m3u8\n")):
            with self.subTest(master=master):
                with patch.object(captions_sess, "get", return_value=master) as request:
                    result = captions.fetch_one(PLAYER, self.out)
                self.assertEqual(result, ("epw120623", "epw", "none", 0))
                self.assertEqual(request.call_count, 2)
                self.assertEqual(self.receipt()["outcome"], "not_found")
                self.assertFalse((self.out / "epw120623.txt").exists())

    def test_archive_subtitles_are_captured_when_live_master_is_missing(self):
        archive = archive_url("epw", "epw120623")
        body = f'#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,URI="{PLAYLIST}"\n'
        with patch.object(captions_sess, 'get', side_effect=responses({
            MASTER: response(404), archive: response(200, body),
        })):
            self.assertEqual(captions.fetch_one(PLAYER, self.out)[2], 'webvtt')
        raw = json.loads(gzip.decompress((self.out / 'epw120623.captions.json.gz').read_bytes()))
        self.assertEqual([source['status_code'] for source in raw['master_checks']], [404, 200])
        self.assertEqual(raw['master']['url'], archive)
        self.assertEqual(self.receipt()['scope']['master_url'], archive)
        self.assertEqual(len(raw['segments']), 2)

    def test_archive_error_does_not_convert_live_absence_to_negative(self):
        with patch.object(captions_sess, 'get', side_effect=responses({
            MASTER: response(404), archive_url('epw', 'epw120623'): response(503),
        })):
            with self.assertRaises(requests.RequestException):
                captions.fetch_one(PLAYER, self.out)
        self.assertEqual(self.receipt()['outcome'], 'error')

    def test_broken_live_playlist_falls_back_to_archive_and_retains_failed_response(self):
        archive = archive_url('epw', 'epw120623')
        archive_playlist = archive.rsplit('/', 1)[0] + '/text/main.m3u8'
        master = f'#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,URI="{archive_playlist}"\n'
        playlist = f'#EXTM3U\n{SEGMENT1}\n{SEGMENT2}\n#EXT-X-ENDLIST\n'
        with patch.object(captions_sess, 'get', side_effect=responses({
            PLAYLIST: response(404), archive: response(200, master),
            archive_playlist: response(200, playlist),
        })):
            self.assertEqual(captions.fetch_one(PLAYER, self.out)[2], 'webvtt')
        raw = json.loads(gzip.decompress((self.out / 'epw120623.captions.json.gz').read_bytes()))
        self.assertEqual(raw['master']['url'], archive)
        self.assertEqual([(s['url'], s['status_code']) for s in raw['prior_responses']], [(PLAYLIST, 404)])

    def test_missing_or_invalid_segment_never_writes_partial_text(self):
        for failed in (response(404), response(200, "<html>error</html>"), response(503),
                       response(200, "WEBVTT\n\nThis is not a timed cue.\n"),
                       response(200, "WEBVTT\n00:00:00.000 --> 00:00:01.000\nIncomplete header\n"),
                       response(200, "WEBVTT\n\n00:00:03.000 --> 00:00:01.000\nReversed cue\n")):
            with self.subTest(failed=failed):
                with patch.object(captions_sess, "get", side_effect=responses({SEGMENT2: failed})):
                    with self.assertRaises((captions_IncompleteCaptionsError, requests.RequestException)):
                        captions.fetch_one(PLAYER, self.out)
                self.assertFalse((self.out / "epw120623.txt").exists())
                self.assertFalse((self.out / "epw120623.cues.txt").exists())
                self.assertEqual(self.receipt()["outcome"], "error")
                self.assertNotIn("kind", self.receipt())

    def test_listed_missing_playlist_and_malformed_master_are_errors(self):
        for changed in ({PLAYLIST: response(404)}, {PLAYLIST: response(200, "#EXTM3U\n")},
                        {MASTER: response(200, "<html>temporary outage</html>")}):
            with self.subTest(changed=changed):
                with patch.object(captions_sess, "get", side_effect=responses(changed)):
                    with self.assertRaises(captions_IncompleteCaptionsError):
                        captions.fetch_one(PLAYER, self.out)
                self.assertEqual(self.receipt()["outcome"], "error")

    def test_relative_and_absolute_segment_urls_are_resolved(self):
        absolute = "https://captions.example.gov/file.vtt?part=2"
        playlist = "#EXTM3U\n../one.vtt\n" + absolute + "\n"
        relative = MASTER.rsplit("/", 1)[0] + "/one.vtt"
        overrides = {PLAYLIST: response(200, playlist), relative: response(200, VTT1), absolute: response(200, VTT2)}
        with patch.object(captions_sess, "get", side_effect=responses(overrides)):
            captions.fetch_one(PLAYER, self.out)
        self.assertEqual(self.receipt()["scope"]["segment_urls"], [relative, absolute])

    def test_failure_preserves_previously_retained_output(self):
        output = self.out / "epw120623.txt"
        output.write_text("Previously complete text.\n")
        with patch.object(captions_sess, "get", side_effect=responses({SEGMENT2: response(404)})):
            with self.assertRaises(captions_IncompleteCaptionsError):
                captions.fetch_one(PLAYER, self.out)
        self.assertEqual(output.read_text(), "Previously complete text.\n")

    def test_failed_record_not_indexed_while_independent_success_is_saved(self):
        second = "https://www.senate.gov/isvp/?comm=epw&filename=epw120723"
        second_master = live_url("epw", "epw120723")
        with patch.object(captions_sess, "get", side_effect=responses({MASTER: response(503), second_master: response(404), archive_url("epw", "epw120723"): response(404)})):
            with self.assertRaisesRegex(RuntimeError, "1 Senate caption acquisition"):
                captions.main(self.out, [PLAYER, second], nthreads=2)
        with (self.out / captions.INDEX).open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows, [{"filename": "epw120723", "comm": "epw", "kind": "none", "characters": "0"}])
        self.assertEqual(self.receipt()["outcome"], "error")
        self.assertEqual(self.receipt(second)["outcome"], "not_found")

    def test_legacy_index_is_rechecked_before_assigning_a_current_receipt(self):
        index = self.out / captions.INDEX
        original = "filename,comm,kind,characters\nepw120623,epw,none,0\n"
        index.write_text(original)
        with patch.object(captions_sess, "get", return_value=response(404)) as request:
            self.assertEqual(captions.main(self.out, [PLAYER]), {"webvtt": 0, "none": 1})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(index.read_text(), original)
        self.assertEqual(self.receipt()['capture_version'], captions.CAPTURE_VERSION)
        with patch.object(captions_sess, 'get', side_effect=AssertionError('confirmed capture is current')):
            self.assertEqual(captions.main(self.out, [PLAYER]), {'webvtt': 0, 'none': 0})

    def test_equivalent_player_urls_are_checked_once(self):
        alternative = "https://www.senate.gov/isvp/?filename=epw120623&comm=epw&autoplay=false"
        with patch.object(captions_sess, "get", return_value=response(404)) as request:
            captions.main(self.out, [PLAYER, alternative])
        self.assertEqual(request.call_count, 2)
        self.assertEqual(captions_receipt_path(self.out, PLAYER), captions_receipt_path(self.out, alternative))


if __name__ == "__main__":
    unittest.main()
