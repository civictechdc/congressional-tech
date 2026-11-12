"""Narrow URL serialization aliases; document and capture identity stay unchanged."""
import hashlib
import re

ALIAS_PREFIX = 'lookup-alias:serialization-v1:'
ALIAS_PATTERN = '[ ]|%[0-9A-Fa-f]{2}'


def serialization_alias_sql(value):
    """Serialize U+0020 and uppercase valid percent triplets, without decoding."""
    value = f"replace({value},' ','%20')"
    for digit in 'abcdef':
        value = f"regexp_replace({value},'%{digit}([0-9A-Fa-f])','%{digit.upper()}\\1','g')"
        value = f"regexp_replace({value},'(%[0-9A-Fa-f]){digit}','\\1{digit.upper()}','g')"
    return value


def serialization_alias(value: str) -> str:
    """Python counterpart of `serialization_alias_sql` for offline gate proof (ct-faan)."""
    value = value.replace(' ', '%20')
    return re.sub(r'%([0-9A-Fa-f])([0-9A-Fa-f])', lambda m: '%' + m.group(1).upper() + m.group(2).upper(), value)


def lookup_form(url: str) -> str | None:
    """Python counterpart of `archive_format._lookup_steps` (DM §8.2) for offline gate proof."""
    m = re.match(r'^([a-zA-Z][a-zA-Z0-9+.-]*)://', url)
    if not m:
        return None
    scheme = m.group(1).lower()
    tail = url[m.end():]
    authority = re.match(r'^([^/?#]*)', tail).group(1)
    remainder = re.sub(r'#.*$', '', tail[len(authority):], flags=re.S)
    host = re.sub(r'^www[.]', '', authority.lower())
    if scheme == 'http':
        host = re.sub(r':80$', '', host)
    elif scheme == 'https':
        host = re.sub(r':443$', '', host)
    path = re.sub(r'/$', '', re.match(r'^([^?]*)', remainder).group(1))
    query = (re.search(r'([?].*)$', remainder, flags=re.S) or [None, ''])[1] if '?' in remainder else ''
    return host + path + query


def _h16(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def address_keys(url: str) -> dict[str, set[str]]:
    """Keys derived from an address by Kind: link_key, lookup_key (including serialization alias), and address."""
    lookups: set[str] = set()
    form = lookup_form(url)
    if form is not None:
        lookups.add(_h16('lookup:' + form))
        if re.search(ALIAS_PATTERN, form):
            lookups.add(_h16(ALIAS_PREFIX + serialization_alias(form)))
    return {
        'link_key': {_h16('url:' + url)},
        'lookup_key': lookups,
        'address': {url},
    }
