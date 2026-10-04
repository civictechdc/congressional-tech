"""Interpret the bounded scope of a retained Senate archive/live HEAD probe."""
from dataclasses import dataclass
from datetime import date

from congress_api.parsers.media import recording_reference
from congress_api.parsers.senate_player import STREAM, LIVE_ID, archive_url, live_url


@dataclass(frozen=True)
class ProbeObservation:
    observed_day: date | None
    valid_urls: bool
    positive_players: tuple[tuple[str, str], ...]
    tested_players: tuple[tuple[str, str], ...]


def probe_observation(native_key, observation, now):
    """Keep found players; infer absence only in a complete live probe's scope.

    Imported research-cache dates are file times, not source observation times.
    The collector tests four committee/day names at archive and live endpoints.
    """
    checked = None
    if observation.get('source') == 'HEAD':
        try:
            parsed = date.fromisoformat(observation['checked'])
            if parsed <= now.date():
                checked = parsed
        except (KeyError, TypeError, ValueError):
            pass
    raw_urls = observation.get('urls')
    players = []
    valid_urls = isinstance(raw_urls, list)
    for url in raw_urls if isinstance(raw_urls, list) else []:
        player = recording_reference(url)
        if player and player.provider == 'senate':
            players.append((player.identifier, url))
        else:
            valid_urls = False
    tested = []
    if observation.get('source') == 'HEAD' and valid_urls:
        try:
            comm, day = native_key.split('|', 1)
            held = date.fromisoformat(day)
        except (ValueError, TypeError):
            comm = ''
        if comm in STREAM and comm in LIVE_ID:
            for filename in (f'{comm}{held:%m%d%y}', f'{comm}A{held:%m%d%y}', f'{comm}B{held:%m%d%y}', f'{comm}{held:%m%d%y}p'):
                tested.append((filename, f'HEAD {archive_url(comm, filename)} and {live_url(comm, filename)}'))
    return ProbeObservation(checked, valid_urls, tuple(players), tuple(tested))
