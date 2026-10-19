"""URL keys and CDX rows shared by the Web Harvest index scripts."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from surt import surt

FIELDS = ['urlkey', 'timestamp', 'url', 'mime', 'status', 'digest', 'unused', 'flags', 'length', 'offset', 'filename']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def load(path):
    return json.loads(path.read_text())


def key(url):
    try:
        p = urlsplit(url)
        if p.scheme not in {'http', 'https'} or not p.hostname or '.' not in p.hostname or p.username or p.password:
            return None
        if any(c.isspace() for c in p.netloc):
            return None
        return surt(url)
    except ValueError:
        return None


def parse_cdx(raw):
    rows, resume = [], None
    for line in raw.decode('utf-8').splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) == 11 and re.fullmatch(r'\d{14}', parts[1]):
            rows.append(dict(zip(FIELDS, parts)))
        elif len(parts) == 1 and re.fullmatch(r'[A-Za-z0-9_=-]+', parts[0]) and resume is None:
            resume = parts[0]
        else:
            raise ValueError('not_cdx_text')
    return rows, resume
