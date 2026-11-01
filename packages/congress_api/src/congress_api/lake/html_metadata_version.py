"""Content version of the HTML metadata reader and its installed dependency closure.

It hashes (name, version) pairs, not the sidecar's bytes, so moving extruct from
the sidecar to uv.lock at the next pin move leaves this version unchanged. A wheel
rebuilt under one version is excluded by the sidecar's --require-hashes install.
"""
from importlib import metadata
from pathlib import Path
import re

from congress_api.lake.versions import version_digest
from congress_api.parsers.html_metadata import FORMAT_TIMEOUT_SECONDS, FORMATS

ROOT = Path(__file__).resolve().parents[5]
SOURCE = Path('packages/congress_api/src/congress_api')
SIDECAR = Path('packages/congress_api/html-metadata.lock.txt')
SIDECAR_CLOSURE = ('beautifulsoup4', 'extruct', 'html-text', 'html5lib', 'jstyleson', 'mf2py',
                   'pyrdfa3', 'rdflib', 'soupsieve', 'w3lib', 'webencodings')


def current_version(root=ROOT):
    root = Path(root)
    pins = dict(re.findall(r'^([a-z0-9-]+)==(\S+)', (root / SIDECAR).read_text(), re.M))
    if sorted(pins) != sorted(SIDECAR_CLOSURE):
        raise ValueError(f'{SIDECAR} does not pin the reader closure: {sorted(pins)}')
    installed = {name: metadata.version(name) for name in SIDECAR_CLOSURE}
    if wrong := sorted(name for name, version in installed.items() if version != pins[name]):
        raise ValueError(f'Installed HTML metadata packages differ from {SIDECAR}: {wrong}')
    return version_digest(packages={}, files={
        name: root / SOURCE / name for name in ('models/html_metadata.py', 'parsers/html_metadata.py', 'parsers/main_content.py')
    }, values=dict(parser='html_metadata', closure=sorted({**installed, 'lxml': metadata.version('lxml')}.items()),
                   options=dict(formats=list(FORMATS), format_timeout_seconds=FORMAT_TIMEOUT_SECONDS, base_url=None)))
