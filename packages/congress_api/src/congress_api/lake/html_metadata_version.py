"""Content version of the HTML metadata reader.

extruct and the packages it brings are not hashed: by owner decision their versions do
not force re-reads. Each reading records ``extruct_version`` as provenance instead.
"""
from importlib import metadata
from pathlib import Path

from congress_api.lake.versions import version_digest
from congress_api.parsers.html_metadata import FORMAT_TIMEOUT_SECONDS, FORMATS

ROOT = Path(__file__).resolve().parents[5]
SOURCE = Path('packages/congress_api/src/congress_api')


def current_version(root=ROOT):
    root = Path(root)
    return version_digest(packages={}, files={
        name: root / SOURCE / name for name in ('models/html_metadata.py', 'parsers/html_metadata.py', 'parsers/main_content.py')
    }, values=dict(parser='html_metadata', lxml=metadata.version('lxml'),
                   options=dict(formats=list(FORMATS), format_timeout_seconds=FORMAT_TIMEOUT_SECONDS, base_url=None)))
