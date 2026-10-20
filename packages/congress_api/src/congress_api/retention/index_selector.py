"""Narrow object-key policy for application snapshot selectors."""


def require_selector_key(key):
    if (not isinstance(key, str) or not key.startswith('indexes/') or not key.endswith('.json')
            or key.count('/') != 1 or len(key) <= len('indexes/.json')
            or any(char not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for char in key[8:-5])):
        raise ValueError('Invalid application selector key')
