"""Retirement removes alternate writers, while native and historical reads remain."""
import importlib.util

from congress_api.retention import raw_archive, raw_catalog

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
