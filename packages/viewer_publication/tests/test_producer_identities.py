"""ct-an6o: producer identities hash the locked packages their parsers import, not the whole lock.

Each case runs the real version functions against a checkout whose only change is
one locked version, so a stable identity is the code's result and not a fixture's.
"""
import json
import os
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
    # A producer whose published pin is its own fingerprint (a deliberate bump since ct-an6o) needs no entry.
    assert reviewed == {fingerprints[name]: pin for name, pin in published().items() if fingerprints[name] != pin}


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


@pytest.fixture
def case_insensitive_disk(monkeypatch, tmp_path):
    """Paths under tmp_path resolve as on macOS's case-insensitive disk, on any host: file checks
    and directory listings both accept a name that differs only in case."""
    base, is_file, listdir = tmp_path.resolve(), Path.is_file, os.listdir

    def fold(path):
        path = Path(path)
        if not path.is_relative_to(base):
            return path
        found = base
        for name in path.relative_to(base).parts:
            names = listdir(found) if found.is_dir() else []
            found = found / next((n for n in names if n.casefold() == name.casefold()), name)
            if not found.exists():
                return None
        return found

    def folded_listdir(path='.'):
        if (real := fold(path)) is None:
            raise FileNotFoundError(path)
        return listdir(real)

    monkeypatch.setattr(Path, 'is_file', lambda self, *a, **k: (real := fold(self)) is not None and is_file(real))
    monkeypatch.setattr(os, 'listdir', folded_listdir)
    return base


def test_an_imported_name_is_a_submodule_only_when_a_file_has_exactly_its_name(case_insensitive_disk):
    """ct-p394: on macOS, `from house_naming import Engine` resolved to Engine.py and hashed engine.py a
    second time under a name Linux does not have, so the two hosts' reading evidence differed. The walk
    resolves a module as Python imports one, by exact name, whatever the disk accepts."""
    root = case_insensitive_disk
    (root / 'uv.lock').write_text('version = 1\n\n[[package]]\nname = "pkg"\nversion = "0.1.0"\n'
                                  'source = { editable = "pkg" }\n')
    package = root / 'pkg/src/pkg'
    (package / 'sub').mkdir(parents=True)
    (package / '__init__.py').write_text('from .engine import Engine\nfrom .sub import Sub\n')
    (package / 'engine.py').write_text('class Engine: ...\n')
    (package / 'sub/__init__.py').write_text('class Sub: ...\n')
    (root / 'reader.py').write_text('from pkg import Engine, Sub\n')
    assert (package / 'Engine.py').is_file() and (package / 'Sub/__init__.py').is_file()  # the disk folds case
    workspace, external = versions.ImportClosure(root).reachable(['reader.py'])
    assert sorted(path.relative_to(root).as_posix() for path in workspace) == [
        'pkg/src/pkg/__init__.py', 'pkg/src/pkg/engine.py', 'pkg/src/pkg/sub/__init__.py', 'reader.py']
    assert external == set()
