"""Interpret recording providers without creating normalized meeting records."""
from dataclasses import dataclass
import re
from urllib.parse import parse_qs, urlsplit

from congress_api.parsers.senate_player import parse_player_url

VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')


@dataclass(frozen=True)
class RecordingReference:
    """Provider identity plus the exact supplied URL; scope identifies Senate's owner."""
    key: str
    url: str
    provider: str | None = None
    identifier: str | None = None
    scope: str | None = None


def offsite_reference(url: str) -> RecordingReference:
    """Explicit offsite findings retain their URL identity, even for known players."""
    return RecordingReference('offsite|' + url, url)


def recording_reference(token: object) -> RecordingReference | None:
    """Recognize bare YouTube IDs and provider URLs; retain other HTTP(S) URLs."""
    if not isinstance(token, str):
        return None
    if VIDEO_ID.fullmatch(token):
        return RecordingReference('youtube|' + token, 'https://www.youtube.com/watch?v=' + token, 'youtube', token)
    # Validate without normalizing fragments, escaping, paths or HTTP spelling.
    try:
        parsed = urlsplit(token)
    except ValueError:
        return None
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return None
    url = token
    host = (parsed.hostname or '').removeprefix('www.')
    video = None
    if host in ('youtube.com', 'youtube-nocookie.com'):
        if parsed.path == '/watch':
            video = next(iter(parse_qs(parsed.query).get('v', [])), None)
        else:
            parts = parsed.path.strip('/').split('/')
            if len(parts) == 2 and parts[0] in ('live', 'embed', 'shorts', 'v'):
                video = parts[1]
    elif host == 'youtu.be':
        video = parsed.path.lstrip('/').split('/')[0]
    if video and VIDEO_ID.fullmatch(video):
        return RecordingReference('youtube|' + video, url, 'youtube', video)
    if host == 'senate.gov' and parsed.path.rstrip('/') == '/isvp':
        player = parse_player_url(url)
        if player:
            return RecordingReference('senate|' + '|'.join(player), url, 'senate', player[1], player[0])
    return offsite_reference(url)


def youtube_video_id(token: object) -> str | None:
    """Return the YouTube identity only when the supplied reference identifies that provider."""
    parsed = recording_reference(token)
    return parsed.identifier if parsed and parsed.provider == 'youtube' else None


def senate_player_reference(token: object) -> bool:
    """Whether the supplied reference is a usable Senate player on Senate.gov."""
    parsed = recording_reference(token)
    return bool(parsed and parsed.provider == 'senate')
