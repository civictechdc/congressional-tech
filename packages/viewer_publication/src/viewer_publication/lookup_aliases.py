"""Narrow URL serialization aliases; document and capture identity stay unchanged."""

ALIAS_PREFIX = 'lookup-alias:serialization-v1:'
ALIAS_PATTERN = '[ ]|%[0-9A-Fa-f]{2}'


def serialization_alias_sql(value):
    """Serialize U+0020 and uppercase valid percent triplets, without decoding."""
    value = f"replace({value},' ','%20')"
    for digit in 'abcdef':
        value = f"regexp_replace({value},'%{digit}([0-9A-Fa-f])','%{digit.upper()}\\1','g')"
        value = f"regexp_replace({value},'(%[0-9A-Fa-f]){digit}','\\1{digit.upper()}','g')"
    return value
