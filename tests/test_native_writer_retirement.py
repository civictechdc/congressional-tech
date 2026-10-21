"""Retirement removes alternate writers, while native and historical reads remain."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

from congress_api.retention import raw_archive, raw_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_raw_catalog_exposes_only_native_update_dispatch():
    for name in ('rebuild_catalog', 'rebuild_catalog_in_directory', '_rebuild_catalog',
                 '_rebuild_catalog_owned', '_publish_result'):
        assert not hasattr(raw_catalog, name)
    for name in ('update_from_raw', 'qualify_source_contributions', 'upgrade_source_rules'):
        assert callable(getattr(raw_catalog, name))
    assert importlib.util.find_spec('congress_api.retention.catalog_lineage') is None


def test_raw_archive_has_no_checkpoint_writer_or_reconstruction_adopter():
    assert not hasattr(raw_archive, 'LegacyArchiveSeed')
    assert not hasattr(raw_archive, 'adopt_legacy_archive')
    assert callable(raw_archive.Archive.save)


def test_viewer_builder_exposes_native_preparation_without_v5_writer():
    spec = importlib.util.spec_from_file_location('retired_writer_check', ROOT / 'scripts/publication/publish-filename-viewer.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.publish_selected)
    assert not hasattr(module, 'publish') and not hasattr(module, '_publish')


def test_old_direct_viewer_cli_refuses_before_output(tmp_path):
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(str(p) for p in sorted((ROOT / 'packages').glob('*/src'))))
    target = tmp_path / 'output'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/publication/publish-filename-viewer.py'),
        '--source', str(tmp_path), '--output', str(target)], env=env,
        capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'publish-viewer-r2.py prepare' in result.stderr
    assert not target.exists()
