"""Local paths for one release's named assets, independent of storage layout.

Native exports stay at their retained paths. Downloaded releases use their public
layout. These helpers resolve membership only; the native owner, download and
publication boundaries verify the corresponding bytes.
"""
import json
from pathlib import Path

from viewer_publication.archive_format import archive_asset_name


def directory_files(directory):
    """Name the assets in a downloaded or fixture release without opening data."""
    directory = Path(directory).absolute()
    manifest = json.loads((directory / 'manifest.json').read_text())
    names = [item['name'] for item in manifest['files']]
    if len(names) != len(set(names)) or any(not archive_asset_name(name) for name in names):
        raise ValueError('Invalid or duplicate release asset path')
    return {'manifest.json': directory / 'manifest.json',
            **{name: directory / name for name in names}}
