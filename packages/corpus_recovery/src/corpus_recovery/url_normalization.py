"""Registry-driven URL identity and narrow fetch-address repair helpers.

Single-source parity with ``model/sql/url-normalized.sql`` + ``model/sql/url-keys.sql``
and ``model/registries/url-rules.json``, plus narrow candidate-address repairs from
``docs/plans/url-normalization.md`` Work Item 5.
"""
import functools
import json
from pathlib import Path
import re
from urllib.parse import unquote_to_bytes


_URL_RULES_PATH = Path(__file__).resolve().parents[4] / 'model/registries/url-rules.json'


def _rust_regex(pattern):
    """Translate the registry's Rust-regex subset to Python ``re``.

    The registry uses inline flags, character classes, groups and anchors. Rust's
    ``$`` (without multiline) matches only at the end of the text, so a final
    unescaped ``$`` becomes ``\\Z`` to keep Python from accepting a trailing newline.
    """
    if pattern.endswith('$') and not pattern.endswith('\\$'):
        pattern = pattern[:-1] + r'\Z'
    return re.compile(pattern)


_RUST_GROUP_REF = re.compile(r'\$(?:\$|\{([A-Za-z0-9_]+)\}|([A-Za-z0-9_]+))')


def _rust_replace(compiled, replacement, value):
    """Emulate DataFusion ``regexp_replace(value, pattern, replacement)`` (first match)."""
    def expand(match):
        def ref(token):
            name = token.group(1) or token.group(2)
            if name is None:
                return '$'
            try:
                group = match.group(int(name) if name.isdigit() else name)
            except IndexError:  # Rust expands an unknown group to the empty string.
                return ''
            return group or ''
        return _RUST_GROUP_REF.sub(ref, replacement)
    return compiled.sub(expand, value, count=1)


@functools.lru_cache(maxsize=1)
def _load_url_rules():
    """Load wrapper and strip rules from ``model/registries/url-rules.json``.

    The registry is the single owner of URL identity rules; computing keys without
    it would silently diverge from ``model/sql/url-normalized.sql``.
    """
    candidates = [_URL_RULES_PATH, Path.cwd() / 'model/registries/url-rules.json']
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise FileNotFoundError('model/registries/url-rules.json is required for URL identity')
    data = json.loads(path.read_text(encoding='utf-8'))
    entries = data if isinstance(data, list) else data.get('entries', ())
    wrappers, strips = [], []
    for entry in entries:
        item = dict(entry, _re=_rust_regex(entry['pattern']),
                    _host_re=_rust_regex(entry['host_pattern']) if entry.get('host_pattern') else None)
        if entry.get('kind') == 'wrapper':
            wrappers.append(item)
        elif entry.get('kind') == 'strip':
            strips.append(item)
    return tuple(wrappers), tuple(strips)


def _percent_decode_utf8(value):
    """Mirror the native ``percent_decode_utf8``: invalid UTF-8 keeps the input."""
    try:
        return unquote_to_bytes(value).decode('utf-8')
    except UnicodeDecodeError:
        return value


def _wrapper_pass(value, wrappers):
    """One ``url-normalized.sql`` wrapper pass: ``(value, matches)``."""
    if value is None:
        return None, 0
    matched = [r for r in wrappers if r['_re'].search(value)]
    if not matched:
        return value, 0
    inner = []
    for rule in matched:
        text = _rust_replace(rule['_re'], rule.get('replacement') or '', value)
        if rule.get('decoder') == 'proofpoint':
            text = re.sub(r'-([0-9A-Fa-f]{2})', r'%\1', text).replace('_', '/')
            text = _percent_decode_utf8(text)
        elif rule.get('decoder') == 'percent':
            text = _percent_decode_utf8(text)
        inner.append(text)
    # SQL max(); only meaningful for one match, more matches are a conflict.
    return max(inner), len(matched)


# WHATWG percent-encode sets for special (http/https) URLs.
_C0_SET = frozenset(range(0x00, 0x20)) | frozenset(range(0x7F, 0x100))
_FRAGMENT_SET = _C0_SET | frozenset(b' "<>`')
_QUERY_SET = _C0_SET | frozenset(b' "#<>\'')
_PATH_SET = _C0_SET | frozenset(b' "#<>?`{}')
_USERINFO_SET = _PATH_SET | frozenset(b'/:;=@[\\]^|')
_FORBIDDEN_HOST = frozenset('\x00\t\n\r #/:<>?@[\\]^|%\x7f') | frozenset(chr(c) for c in range(0x20))
_DEFAULT_PORTS = {'http': 80, 'https': 443}
_UNRESERVED = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~')
_RESERVED = frozenset(b":/?#[]@!$&'()*+,;=")
_HEX = '0123456789ABCDEF'


def _encode(text, encode_set):
    return ''.join(
        ''.join(f'%{b:02X}' for b in ch.encode('utf-8'))
        if (ord(ch) > 0x7E or ord(ch) in encode_set) else ch
        for ch in text
    )


def _ipv4_number(part):
    if part[:2].lower() == '0x':
        digits, base = part[2:], 16
        if not digits:
            return 0
    elif len(part) > 1 and part[0] == '0':
        digits, base = part[1:], 8
    else:
        digits, base = part, 10
    allowed = {16: '0123456789abcdefABCDEF', 8: '01234567', 10: '0123456789'}[base]
    if not digits or any(c not in allowed for c in digits):
        return None
    return int(digits, base)


def _whatwg_host(text):
    """WHATWG host parser for special schemes; ``None`` means failure."""
    if text.startswith('['):
        if not text.endswith(']'):
            return None
        import ipaddress
        try:
            return f'[{ipaddress.IPv6Address(text[1:-1]).compressed}]'
        except ValueError:
            return None
    host = unquote_to_bytes(text).decode('utf-8', errors='replace')
    if not host:
        return None
    if host.isascii():
        host = host.lower()
    else:
        try:
            import idna
            host = '.'.join(
                idna.encode(label, uts46=True, transitional=False).decode('ascii') if label else ''
                for label in host.split('.')
            )
        except Exception:  # noqa: BLE001 - any IDNA failure is a WHATWG host failure
            return None
    if not host or any(c in _FORBIDDEN_HOST for c in host):
        return None
    labels = host.split('.')
    if labels[-1] == '' and len(labels) > 1:
        labels = labels[:-1]
    last = labels[-1]
    if last and (last.isdigit() or (last[:2].lower() == '0x' and all(
            c in '0123456789abcdefABCDEF' for c in last[2:]))):
        if len(labels) > 4:
            return None
        numbers = [_ipv4_number(p) if p else None for p in labels]
        if any(n is None for n in numbers) or any(n > 255 for n in numbers[:-1]):
            return None
        if numbers[-1] >= 256 ** (5 - len(numbers)):
            return None
        address = numbers[-1]
        for index, n in enumerate(numbers[:-1]):
            address += n * 256 ** (3 - index)
        return '.'.join(str((address >> shift) & 255) for shift in (24, 16, 8, 0))
    return host


def _whatwg_special_url(value):
    """Serialize an absolute http(s) URL like Rust ``url::Url::parse`` (WHATWG).

    Equivalent to the native ``url_resolve(value, NULL)`` for http(s) inputs; other
    schemes and relative references return ``None`` because they cannot produce an
    ``https?://`` authority in ``url-normalized.sql``.
    """
    text = value.strip(''.join(chr(c) for c in range(0x21)))
    text = re.sub('[\t\n\r]', '', text)
    scheme_match = re.match(r'(?i)(https?):', text)
    if scheme_match is None:
        return None
    scheme = scheme_match.group(1).lower()
    rest = text[scheme_match.end():].lstrip('/\\')
    end = len(rest)
    for stop in '/\\?#':
        found = rest.find(stop)
        if found != -1:
            end = min(end, found)
    authority, rest = rest[:end], rest[end:]
    userinfo = ''
    if '@' in authority:
        credentials, _, authority = authority.rpartition('@')
        user, _, password = credentials.partition(':')
        user, password = _encode(user, _USERINFO_SET), _encode(password, _USERINFO_SET)
        if user or password:
            userinfo = user + (f':{password}' if password else '') + '@'
    port_match = re.fullmatch(r'(.*?)(?::([0-9]*))?', authority, re.S)
    host_text, port_text = port_match.group(1), port_match.group(2)
    if ':' in host_text and not host_text.startswith('['):
        return None
    if host_text.startswith('[') and ']' in host_text and not host_text.endswith(']'):
        return None
    host = _whatwg_host(host_text)
    if host is None:
        return None
    port = ''
    if port_text:
        number = int(port_text)
        if number > 65535:
            return None
        if number != _DEFAULT_PORTS[scheme]:
            port = f':{number}'
    fragment = None
    if '#' in rest:
        rest, fragment = rest.split('#', 1)
    query = None
    if '?' in rest:
        rest, query = rest.split('?', 1)
    segments = []
    raw_segments = rest.replace('\\', '/').split('/')[1:] if rest else []
    for index, segment in enumerate(raw_segments):
        last = index == len(raw_segments) - 1
        lowered = segment.lower()
        if lowered in ('..', '.%2e', '%2e.', '%2e%2e'):
            if segments:
                segments.pop()
            if last:
                segments.append('')
        elif lowered in ('.', '%2e'):
            if last:
                segments.append('')
        else:
            segments.append(_encode(segment, _PATH_SET))
    serialized = f'{scheme}://{userinfo}{host}{port}/' + '/'.join(segments)
    if query is not None:
        serialized += '?' + _encode(query, _QUERY_SET)
    if fragment is not None:
        serialized += '#' + _encode(fragment, _FRAGMENT_SET)
    return serialized


def _uri_normalize_encoding(value):
    """Mirror native ``uri_normalize_encoding``: RFC 3986 escapes, unreserved decoded."""
    data = value.encode('utf-8')
    out = []
    index = 0
    while index < len(data):
        byte = data[index]
        if byte == 0x25 and index + 2 < len(data):
            pair = data[index + 1:index + 3]
            decoded = int(pair, 16) if re.fullmatch(rb'[0-9A-Fa-f]{2}', pair) else None
            if decoded is not None:
                out.append(chr(decoded) if decoded in _UNRESERVED else f'%{_HEX[decoded >> 4]}{_HEX[decoded & 15]}')
                index += 3
                continue
        out.append(chr(byte) if byte in _UNRESERVED or byte in _RESERVED else f'%{_HEX[byte >> 4]}{_HEX[byte & 15]}')
        index += 1
    return ''.join(out)


def url_identity(raw_url):
    """Python twin of ``model/sql/url-normalized.sql`` + ``url-keys.sql`` (no variants).

    Returns ``dict(normalized_url, url_key, error, still_wrapped)``. ``normalized_url``
    is the SQL's ``parsed`` value, ``uri_normalize_encoding(url_resolve(unwrapped))``:
    the unwrapped absolute URL with scheme, ``www.``, trailing slash, original query
    order and fragment intact. ``url_key`` is the SQL ``base_key``. Both are ``None``
    when the SQL reports ``wrapper_conflict`` or ``invalid_url``.
    """
    wrappers, strips = _load_url_rules()
    value = raw_url if isinstance(raw_url, str) else None
    value, first = _wrapper_pass(value, wrappers)
    value, second = _wrapper_pass(value, wrappers)
    still_wrapped = value is not None and any(r['_re'].search(value) for r in wrappers)
    if first > 1 or second > 1:
        return dict(normalized_url=None, url_key=None, error='wrapper_conflict', still_wrapped=still_wrapped)
    resolved = _whatwg_special_url(value) if value is not None else None
    parsed = _uri_normalize_encoding(resolved) if resolved is not None else None
    match = re.match(r'https?://([^/?#]+)([^?#]*)', parsed) if parsed is not None else None
    if match is None:
        return dict(normalized_url=None, url_key=None, error='invalid_url', still_wrapped=still_wrapped)
    authority = re.sub(r'^www\.', '', match.group(1))
    path = match.group(2)
    query_match = re.search(r'\?(.*)\Z', parsed.split('#', 1)[0], re.S)
    query = query_match.group(1) if query_match else None
    kept = []
    if query:
        host = re.sub(r':[0-9]+\Z', '', authority)
        for pair in query.split('&'):
            name = pair.split('=', 1)[0]
            if not any((r['_host_re'] is None or r['_host_re'].search(host)) and r['_re'].search(name)
                       for r in strips):
                kept.append(pair)
    key = authority + re.sub(r'/\Z', '', path) + ('?' + '&'.join(sorted(kept)) if kept else '')
    return dict(normalized_url=parsed, url_key=key, error=None, still_wrapped=still_wrapped)


def _normalize_and_key_url(raw_url):
    """Return ``(normalized_url, url_key)``; see :func:`url_identity`."""
    identity = url_identity(raw_url)
    return identity['normalized_url'], identity['url_key']


# Narrow, evidence-backed address repairs for observed malformed URL families
# (docs/plans/url-normalization.md Work Item 5). Wrapper rules come from
# ``model/registries/url-rules.json`` so repair patterns cannot drift from SQL.
_MAILTO_HTTP_RE = re.compile(r'(?i)^mailto:\s*(https?://.+)$')
_FILE_URL_PATH_RE = re.compile(r'(?i)^https?://file(?:%20|\s)+url(?:%20|\s)+path:(?:%20|\s)*(/.*)$')
_FILE_URL_EMBEDDED_HOST_RE = re.compile(r'(?i)^/+([a-z0-9.-]+\.(?:house|senate|congress)\.gov/.+)$')
_TRAILING_SPACE_PATH_RE = re.compile(r'^(https?://[^/?#]+/[^?#]*?)(?:%20|\s)+((?:\?[^#]*)?(?:#.*)?)$')


def _wrapper_rule_by_id(rule_id):
    wrappers, _ = _load_url_rules()
    return next(r for r in wrappers if r['id'] == rule_id)


def narrow_address_repairs(raw_target, context_url=None):
    """Return ``[(repaired_url, basis), ...]`` for known malformed URL families.

    ``context_url`` is the page that carried the link; it is required only to
    resolve the relative ``http://File URL path: /...`` literal.
    """
    from congress_api.parsers.document_links import download_query_fallback, http_url

    repairs = []
    text = raw_target.strip() if isinstance(raw_target, str) else ''
    if not text:
        return repairs

    m = _MAILTO_HTTP_RE.match(text)
    if m:
        cleaned = http_url(m.group(1))
        if cleaned:
            repairs.append((cleaned, 'mailto_prefix_repair'))
            text = cleaned

    m = _FILE_URL_PATH_RE.match(text)
    if m:
        embedded = _FILE_URL_EMBEDDED_HOST_RE.match(m.group(1))
        if embedded:
            cleaned = http_url('https://' + embedded.group(1))
        elif isinstance(context_url, str) and http_url(context_url):
            cleaned = http_url('/' + m.group(1).lstrip('/'), base=context_url)
        else:
            cleaned = None
        if cleaned:
            repairs.append((cleaned, 'file_url_path_prefix_repair'))
            text = cleaned

    t2gpo_rule = _wrapper_rule_by_id('lis-gpo')
    if t2gpo_rule['_re'].search(text):
        cleaned = http_url(_rust_replace(t2gpo_rule['_re'], t2gpo_rule['replacement'], text))
        if cleaned:
            repairs.append((cleaned, 'congress_t2gpo_wrapper_repair'))
            text = cleaned

    senate_rule = _wrapper_rule_by_id('senate-notfound')
    m = senate_rule['_re'].search(text)
    if m:
        decoded_tail = _percent_decode_utf8(m.group(2))
        if decoded_tail.lower().startswith(('http://', 'https://')):
            raw_repaired = decoded_tail
        else:
            raw_repaired = _percent_decode_utf8(
                _rust_replace(senate_rule['_re'], senate_rule['replacement'], text)
            )
        resolved = _whatwg_special_url(raw_repaired.replace(' ', '%20'))
        repaired = (
            _uri_normalize_encoding(resolved)
            if resolved is not None
            else (http_url(raw_repaired) or raw_repaired.replace(' ', '%20'))
        )
        if repaired and repaired != raw_target:
            repairs.append((repaired, 'senate_notfound_wrapper_repair'))
            text = repaired

    fallback_link = download_query_fallback(text, 404)
    if fallback_link is not None and fallback_link.url != raw_target:
        repairs.append((fallback_link.url, fallback_link.basis))
        text = fallback_link.url
    else:
        amp_rule = _wrapper_rule_by_id('download-ampersand-query')
        if amp_rule['_re'].search(text):
            repaired = _rust_replace(amp_rule['_re'], amp_rule['replacement'], text)
            if repaired != raw_target:
                repairs.append((repaired, 'publisher_download_query_fallback'))
                text = repaired

    m = _TRAILING_SPACE_PATH_RE.match(text)
    if m:
        trimmed = f'{m.group(1)}{m.group(2)}'
        cleaned_trim = http_url(trimmed) or trimmed.split('#', 1)[0]
        if cleaned_trim and cleaned_trim != raw_target:
            repairs.append((cleaned_trim, 'trailing_space_trim_repair'))

    return repairs


def scope_probe_urls(target_url, context_url=None):
    """Spellings whose capture scope decides whether ``target_url`` is acquirable.

    The literal, its narrow repairs, and each of those without a fragment and with
    ``https`` (both preserve the scheme-agnostic, fragment-free ``url_key``).
    """
    probes = []
    for url in [target_url, *(u for u, _ in narrow_address_repairs(target_url, context_url))]:
        bare = url.split('#', 1)[0]
        for probe in (url, bare, re.sub(r'(?i)^http://', 'https://', bare)):
            if probe not in probes:
                probes.append(probe)
    return probes
