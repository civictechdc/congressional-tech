"""Preserve published IDs when a native player gains a recognized provider."""
from collections import defaultdict
import re
from urllib.parse import parse_qsl, urlparse

from congress_api.adapters.common import web_url
from congress_api.adapters.meetings import event_page, meeting_key
from congress_api.parsers.media import recording_reference

# Frozen pre-migration recognition, used only to locate previously allocated
# keys. These permissive rules must never establish current provider facts.
_LEGACY_YOUTUBE = re.compile(r'(?:youtube\.com/(?:watch\?(?:.*&)?v=|live/|embed/|shorts/|v/)|youtu\.be/)([\w-]{11})')


def _legacy_provider_key(url):
    if match := _LEGACY_YOUTUBE.search(url):
        return 'youtube|' + match.group(1)
    query = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
    if query.get('comm') and query.get('filename'):
        return 'senate|' + query['comm'] + '|' + query['filename']
    return None


def _record_keys(key, url, meeting):
    keys = {'material': key, 'material_version': key + '|reported-edition',
            'representation': key + '|' + url}
    if meeting:
        keys['material_link'] = key + '|meeting|' + meeting + '|recording'
    return keys


def retain_recording_ids(rows, ids):
    """Alias unambiguous keys; retain source keys when public IDs conflict.

    Return native-key overrides for the adapter and a versioned publication
    receipt. Existing registry entries never move, including versions, exact
    player representations and meeting links. Corrected mistaken provider
    associations use separate graph keys, with explicit old/new ID receipts,
    so historical issue subjects and genuine provider records remain intact.
    """
    groups = defaultdict(list)
    corrections = []
    for row in rows:
        native = meeting_key(row)
        for video in row.get('videos') or []:
            url = web_url(video.get('url'))
            if not url or event_page(url):
                continue
            parsed = recording_reference(url)
            legacy = native + '|videos|' + url
            current = parsed.key if parsed and parsed.provider else legacy
            meeting = ids.existing('meeting', native)
            prior = _legacy_provider_key(url)
            if (prior and prior != current and ids.existing('material', prior) is not None
                    and ids.existing('representation', prior + '|' + url) is not None):
                corrections.append((legacy, prior, current, url, meeting))
            elif parsed and parsed.provider and ids.existing('material', legacy) is not None:
                groups[parsed.key].append((legacy, url, meeting))
    overrides = {}
    aliases = conflicts = 0
    for canonical, sources in sorted(groups.items()):
        pairs = set()
        for legacy, url, meeting in sources:
            old_keys = _record_keys(legacy, url, meeting)
            for kind, new in _record_keys(canonical, url, meeting).items():
                pairs.add((kind, new, old_keys[kind]))
        targets = defaultdict(set)
        for kind, new, old in pairs:
            targets[kind, new].update(value for value in (ids.existing(kind, new), ids.existing(kind, old)) if value is not None)
        if any(len(values) > 1 for values in targets.values()):
            conflicts += 1
            overrides.update((legacy, legacy) for legacy, _, _ in sources)
            continue
        for kind, new, old in sorted(pairs):
            if ids.existing(kind, new) is None:
                aliases += ids.alias(kind, new, old)
    corrected = []
    for source, prior, current, url, meeting in sorted(set(corrections)):
        # Do not reparent an existing representation/link: previous issues may
        # still reference that exact historical graph, or a genuine recording
        # may share the mistaken canonical key. Keep all old bindings intact.
        old_ids = {kind: ids.existing(kind, key) for kind, key in _record_keys(prior, url, meeting).items()}
        new_ids = {kind: ids(kind, key) for kind, key in _record_keys(current, url, meeting).items()}
        corrected.append({'source_key': source, 'url': url, 'previous_key': prior, 'current_key': current,
                          'reason': 'Prior provider recognition does not match the supplied URL.',
                          'old_ids': old_ids, 'new_ids': new_ids})
    return overrides, {'provider': 'congress.gov', 'migration': 'native-recording-provider-keys',
                       'version': 1, 'aliases_added': aliases,
                       'conflicting_provider_keys': conflicts, 'retained_source_keys': len(overrides),
                       'corrected_provider_references': corrected}
