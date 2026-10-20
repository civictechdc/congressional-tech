"""Recorded source resolutions, including conflicting and invalid evidence."""
import re

from congress_api.parsers.archive_links import allowed_url, capture_links


def wrapped_target(value):
    """Recognize explicit URL wrappers; never infer a base or document version."""
    if not isinstance(value, str):
        return None
    candidate = None
    if value.startswith('ttps://'):
        candidate = 'h' + value
    elif value.startswith('mailto:https://') or value.startswith('mailto:http://'):
        candidate = value[len('mailto:'):]
    elif match := re.fullmatch(r'chrome-extension://[a-p]{32}/(https?://.+)', value):
        candidate = match[1]
    elif re.match(r'https?://(?:www\.)?lis\.gov/cgi-lis/t2GPO/', value):
        links = capture_links({'url': value})
        if len(links) == 1 and links[0].get('url_repair') == 'lis_gpo_wrapper':
            candidate = links[0]['url']
    return candidate if candidate and allowed_url(candidate) == candidate else None


def resolution_candidates(row):
    """Keep all recorded candidates; decide ambiguity after combining owners."""
    resolved = row.get('source_resolved_url') or []
    if resolved:
        return resolved
    target = wrapped_target(row.get('source_url'))
    return [target] if target else []
