"""Resolve one download using saved responses or bounded injected GETs."""
from congress_api.parsers.document_links import document_links, http_url, response_kind
from congress_api.transport.document_probe import DEFAULT_LIMIT, get_prefix


def resolve_document(url, *, saved=None, get=get_prefix, max_bytes=DEFAULT_LIMIT, max_steps=5):
    """Identify a document prefix, or report candidates/why resolution stopped.

    `saved` maps exact URLs to DocumentProbeResponse records. No file reads or
    downloads happen here except through `get`. A prefix never counts as an
    archived document. Multiple explicit links are returned for selection.
    """
    if max_steps < 1 or max_bytes < 1024:
        raise ValueError('Use at least one step and a 1024-byte response limit.')
    target = http_url(url)
    responses, links, visited = [], [], set()
    result = {'url': url, 'outcome': 'step_limit', 'resolved_url': None,
              'responses': responses, 'links': links}
    for _ in range(max_steps):
        if not target:
            result['outcome'] = 'invalid_url'
            break
        if target in visited:
            result['outcome'] = 'loop'
            break
        visited.add(target)
        response = (saved or {}).get(target)
        if response is None:
            try:
                response = get(target, max_bytes=max_bytes)
            except (RuntimeError, OSError) as error:
                result.update(outcome='request_failed', error=str(error))
                break
        responses.append(response)
        headers = {k.lower(): v for k, v in response.headers.items()}
        if response.status_code in (301, 302, 303, 307, 308):
            target = http_url(headers.get('location', ''), response.url) if headers.get('location') else None
            continue
        if not 200 <= response.status_code < 300:
            result['outcome'] = 'http_error'
            break
        body = response.content.body_bytes()[:max_bytes]
        kind = response_kind(body, response.content.media_type)
        if kind in ('pdf', 'zip', 'legacy_office', 'rtf', 'xml'):
            result.update(outcome='document_identified', format=kind, resolved_url=response.url)
            break
        if kind != 'html':
            result['outcome'] = 'unverified_content'
            break
        found = document_links(body, response.url)
        links.extend(found)
        if len(found) != 1:
            result['outcome'] = ('multiple_downloads' if found else
                'no_download_link' if response.complete and len(response.content.body_bytes()) <= max_bytes
                else 'html_limit')
            break
        target = found[0].url
    return result
