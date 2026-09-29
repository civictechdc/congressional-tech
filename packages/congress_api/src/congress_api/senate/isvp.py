"""
The Senate Recording Studio's video player (senate.gov/isvp), which hosts Senate committee
hearing video and the video of joint bodies the Senate records.

A recording is named <comm><MMDDYY> (a second hearing that day is <comm>A<MMDDYY>, then B).
The player at https://www.senate.gov/isvp/?comm=<comm>&filename=<name> loads one of:
- the archive, https://www-senate-gov-msl3archive.akamaized.net/<stream>/<name>_1/master.m3u8,
  where older recordings may embed captions in video and some recordings declare
  separate WebVTT tracks, including recordings moved from the live path;
- the live path, https://www-senate-gov-media-srs.akamaized.net/hls/live/<id>/<comm>/<name>/master.m3u8,
  commonly used since mid-2023, which can carry an English WebVTT subtitle track.
The tables below come from the player page's own stream table (September 2026).
"""
import re
import urllib.parse
from congress_api.models.media import SenatePlayerQuery

## GPO committee code -> the player's `comm` value (from Congress.gov's senate.gov links)
COMM = {"ssaf00": "ag", "ssap00": "approps", "ssas00": "armed", "ssbk00": "banking", "ssbu00": "budget", "sscm00": "commerce",
        "sseg00": "energy", "ssev00": "epw", "ssfi00": "finance", "ssfr00": "foreign", "ssga00": "govtaff", "sshr00": "help",
        "ssju00": "judiciary", "ssra00": "rules", "sssb00": "smbiz", "ssva00": "vetaff", "slia00": "indian", "slin00": "intel",
        "spag00": "aging", "slet00": "ethics",
        ## joint bodies the Senate studio records: Helsinki Commission, Joint Economic Committee, China commissions
        "jcse00": "csce", "jsec00": "jec", "jjec00": "jec", "jcpk00": "cecc", "jcuc00": "uscc"}
STREAM = {"ag": "agriculture", "aging": "aging", "approps": "appropriations", "armed": "armedservices", "banking": "banking", "budget": "budget", "cecc": "srs_cecc", "commerce": "commerce", "csce": "srs_srs", "energy": "energy", "epw": "environment", "ethics": "ethics", "finance": "finance_finance", "foreign": "foreignrelations", "govtaff": "hsgac", "help": "help", "indian": "indianaffairs", "intel": "intelligence", "intlnarc": "internationalnarcoticscaucus", "jec": "jointeconomic", "judiciary": "judiciary", "rules": "rules", "smbiz": "smallbusiness", "uscc": "srs_uscc", "vetaff": "veteransaffairs"}
LIVE_ID = {"ag": "2036803", "aging": "2036801", "approps": "2036802", "armed": "2036800", "banking": "2036799", "budget": "2036798", "cecc": "2036782", "commerce": "2036779", "csce": "2036777", "energy": "2036797", "epw": "2036783", "ethics": "2036796", "finance": "2036795", "foreign": "2036794", "govtaff": "2036792", "help": "2036793", "indian": "2036791", "intel": "2036790", "jec": "2036789", "judiciary": "2036788", "rules": "2036787", "smbiz": "2036786", "uscc": "2036781", "vetaff": "2036785"}
PLAYER = "https://www.senate.gov/isvp/?comm={comm}&filename={fn}"
ARCHIVE = "https://www-senate-gov-msl3archive.akamaized.net/{stream}/{fn}_1/master.m3u8"
LIVE = "https://www-senate-gov-media-srs.akamaized.net/hls/live/{sid}/{comm}/{fn}/master.m3u8"


def parse_player_query(url: str) -> SenatePlayerQuery:
    """Preserve the publisher's query values, including explicit empty strings."""
    return SenatePlayerQuery.model_validate(dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query, keep_blank_values=True)))


def parse_player_url(url: str) -> tuple[str, str] | None:
    """(comm, filename) from a player URL, or None."""
    q = parse_player_query(url)
    return (q.comm, q.filename) if q.comm and q.filename else None


def player_url(comm: str, fn: str) -> str:
    return PLAYER.format(comm=comm, fn=fn)


def archive_url(comm: str, fn: str) -> str:
    return ARCHIVE.format(stream=STREAM[comm], fn=fn)


def live_url(comm: str, fn: str) -> str:
    return LIVE.format(sid=LIVE_ID[comm], comm=comm, fn=fn)
