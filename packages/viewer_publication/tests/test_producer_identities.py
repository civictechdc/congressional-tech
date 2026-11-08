"""ct-an6o: producer identities hash the locked packages their parsers import, not the whole lock.

Each case runs the real version functions against a checkout whose only change is
one locked version, so a stable identity is the code's result and not a fixture's.
"""
import json
from pathlib import Path
import re

import pytest

from congress_api.lake import appearance_records, committee_records, filenames, meeting_records, versions

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED = json.loads((ROOT / 'model/jobs/publish-model.json').read_text())


def identities(root=ROOT):
    result = {f'appearance_records.{s}': v for s, v in appearance_records.current_versions(root=root).items()}
    result.update({f'meeting_records.{s}': v for s, v in meeting_records.current_versions(root=root).items()})
    result.update({f'committee_records.{s}': v for s, v in committee_records.current_versions(root=root).items()})
    result['filename_readings'] = filenames.current_version(root=root)
    return result


def published():
    pins = PUBLISHED['parser_versions']
    result = {f'{table}.{s}': v for table in ('appearance_records', 'meeting_records', 'committee_records')
              for s, v in pins[table].items()}
    result['filename_readings'] = PUBLISHED['catalog_version']
    return result


def bumped_checkout(tmp_path, package):
    """This checkout with one locked package's version changed and nothing else."""
    lock = (ROOT / 'uv.lock').read_text()
    pattern = re.compile(r'(\[\[package\]\]\nname = "' + re.escape(package) + r'"\nversion = ")([^"]+)(")')
    changed, count = pattern.subn(lambda m: m[1] + m[2] + '.post999' + m[3], lock)
    assert count == 1, package
    for name in ('packages', 'model'):
        (tmp_path / name).symlink_to(ROOT / name)
    (tmp_path / 'uv.lock').write_text(changed)
    return tmp_path


def test_current_identities_are_the_published_pins():
    assert identities() == published()


# aiohttp, pyasn1, urllib3, certifi and pillow were the pending security patches
# (ct-680z). pypdf feeds only readings, which carry declared versions.
@pytest.mark.parametrize('package', ['aiohttp', 'pyasn1', 'urllib3', 'certifi', 'pillow', 'pypdf', 'boto3'])
def test_an_unrelated_locked_package_leaves_every_identity(tmp_path, package):
    assert identities(bumped_checkout(tmp_path, package)) == published()


@pytest.mark.parametrize('package,moved', [
    ('lxml', {'appearance_records.congress_gov', 'appearance_records.house_xml', 'appearance_records.mods',
              'appearance_records.senate_page'}),
    ('jsonschema', {'meeting_records.congress_gov', 'meeting_records.house_xml', 'filename_readings'}),
    # A transitive dependency: house_naming.filenames imports pydantic too.
    ('pydantic-core', set(published())),
    ('pyarrow', set(published())),
])
def test_an_imported_package_moves_exactly_its_importers(tmp_path, package, moved):
    before, after = published(), identities(bumped_checkout(tmp_path, package))
    assert {name for name in before if after[name] != before[name]} == moved
    assert all(after[name] not in versions._REVIEWED_PRODUCER_VERSIONS.values() for name in moved)


def test_each_reviewed_entry_is_a_current_fingerprint_of_its_published_pin(monkeypatch):
    reviewed = dict(versions._REVIEWED_PRODUCER_VERSIONS)
    monkeypatch.setattr(versions, '_REVIEWED_PRODUCER_VERSIONS', {})
    fingerprints = identities()
    assert reviewed == {fingerprints[name]: pin for name, pin in published().items()}


@pytest.mark.parametrize('name', ['meeting_records.house_xml', 'filename_readings'])
def test_a_planted_wrong_mapping_is_refused_by_the_model_spec(monkeypatch, name):
    from viewer_publication import archive_model_job
    monkeypatch.setattr(versions, '_REVIEWED_PRODUCER_VERSIONS', {})
    fingerprint = identities()[name]
    monkeypatch.undo()
    # Point this producer's fingerprint at another producer's published ID.
    monkeypatch.setitem(versions._REVIEWED_PRODUCER_VERSIONS, fingerprint, published()['committee_records.house_xml'])
    with pytest.raises(ValueError, match='(Parser|Catalog) version'):
        archive_model_job.load_spec(ROOT / 'model/jobs/publish-model.json')


def test_an_import_without_a_locked_package_refuses(tmp_path):
    module = tmp_path / 'reader.py'
    module.write_text('import PIL\n')
    with pytest.raises(ValueError, match='Imports without a locked package: PIL'):
        versions.ImportClosure(ROOT).locked_versions([module])
