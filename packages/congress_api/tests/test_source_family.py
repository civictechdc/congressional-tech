"""Source and layout evidence takes precedence over hearing-title words."""
import pytest

from congress_api.parsers.source_family import family


SENATE_YOUTUBE_HEARING = (
    "https_www_commerce_senate_gov_meetings_subcommittee_"
    "protecting_kids_online_snapchat_tiktok_and_youtube_.html"
)


def test_senate_html_path_wins_over_youtube_in_hearing_title():
    assert family(source=SENATE_YOUTUBE_HEARING) == "senate/pages"


@pytest.mark.parametrize(("source", "url", "expected"), [
    ("youtube/api/videos.json", "", "youtube/api"),
    ("youtube/watch-pages/watch.html", "", "youtube/watch-pages"),
    ("youtube/captions/timedtext.vtt", "", "youtube/captions"),
    ("", "https://www.googleapis.com/youtube/v3/videos?id=abc123", "youtube/api"),
    ("", "https://www.youtube.com/watch?v=abc123", "youtube/watch-pages"),
    ("", "https://www.youtube.com/api/timedtext?v=abc123&lang=en", "youtube/captions"),
])
def test_genuine_youtube_routing_is_preserved(source, url, expected):
    assert family(source=source, url=url) == expected


@pytest.mark.parametrize(("url", "expected"), [
    ("https://docs.house.gov/meetings/IF/IF00/20261010/118001/HMTG-119-IF00-20261010.xml", "house/meeting-xml"),
    ("https://docs.house.gov/meetings/IF/IF00/20261010/118001/HHRG-119-IF00-20261010.xml", "house/meeting-xml"),
    ("https://docs.house.gov/meetings/IF/IF00/20261010/118001/HMKP-119-IF00-20261010.xml", "house/meeting-xml"),
    ("https://docs.house.gov/meetings/IF/IF00/20261010/118001/HHRG-119-IF00-WList-20261010.xml", "house/witness-xml"),
    ("https://docs.house.gov/meetings/IF/IF00/20261010/118001/HMKP-119-IF00-WList-20261010.xml", "house/witness-xml"),
    ("https://docs.house.gov/meetings/IF/IF00/20261010/118001/HMTG-119-IF00-WList-20261010.xml", "house/witness-xml"),
    ("https://docs.house.gov/meetings/IF/IF00/20261010/118001/OTHER-119-IF00-20261010.xml", "documents"),
])
def test_house_meeting_and_witness_xml_routing(url, expected):
    assert family(url=url) == expected
