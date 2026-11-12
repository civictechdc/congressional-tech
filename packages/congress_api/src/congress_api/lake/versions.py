"""Content versions for parser packages, their inputs and the locked packages they import."""
import ast
from collections import defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import tomllib


# ct-an6o: producer identities hashed the whole uv.lock until this change, so
# every unrelated patch moved them. They now hash the locked packages their
# parsers import. At the switch (rebased onto e55e9c76), the old rule, with the
# ct-680z and body_text-lock (973298d7) reviewed entries it carried, computed
# exactly the published IDs below from the same tree, and MODS computed its
# ct-79j1/ct-rg34 full input digest; each new fingerprint maps to that ID. The
# old-rule entries are gone because no new-rule fingerprint can match them.
# Any later source, schema, parameter or imported-package change produces an
# unmapped fingerprint. Add an entry only with a reviewed equivalence decision.
# ct-zs48/ct-3aap changed MODS extraction, so appearance_records.mods publishes
# its new fingerprint and its entry was removed. ct-gfo7 round 8 added two
# MODS-only record columns to the shared appearance_records table, whose bytes
# every source hashes (3fb41ddd); congress_gov, house_xml and senate_page keep
# their published IDs under reviewed equivalence (2026-11-11, orchestrating
# session, on mods-rebase-20261110/round-8/m8-equivalence.json). ct-a73a
# (2026-11-12) unified active-unreadable filtering (reason <> 'withdrawn') in
# lake/_record_producer.py and lake/filenames/__init__.py and added supervisor
# peak-RSS sampling in retention/parser_worker.py (work-list and supervisor
# telemetry only; zero change to parsed row values or schemas), so the record
# and filename producers keep their published IDs under reviewed equivalence.
_REVIEWED_PRODUCER_VERSIONS = {
    # appearance_records.congress_gov
    "08210281b8914df0b3b0797259020ec04a7272579d3391f54b53db06b4775371":
        "6d9460f5ec203c24c508846092505a875710f565e1ff026479b542c7555e7d48",
    # appearance_records.house_xml
    "9ff81215d58b8331e75799686696eb9873000ec8f4f14b841564019951ccd5c9":
        "5078ef426e0e262ffcd972b244c3b472669583f164121cc6189ccf69e6abf3a5",
    # appearance_records.mods
    "c0fe33cb3f06af5b9eb653589925ddc80a58184b57a540ab2005713a21f0bec3":
        "704ba567914cba4466954297a5fa24ba5869b2c3c59a8258d767ffc2dd225ac4",
    # appearance_records.senate_page
    "b1240e8eb23360950a54eb0d97552fe6dd03ec3a1796df7468d0c26a09e7b509":
        "9d48c0f61a9f8ab1407c07f9c49cba7d6e9253a6369d73a8d14389d9bfee6bbb",
    # committee_records.house_xml
    "67115f315bbe0990d75629fbbc933c2899201b243e90191354d41e56c90f25f4":
        "e1c6ad0d1398f1d1985e085a0fb9b94c6c42ad38a2d9175ad3e8908eb46c531e",
    # filename_readings
    "a08c7d9bc779c33047db55c366b066039143f4a61dd9a1d4da1194cca41fecdb":
        "c65e505ef8eb085e38072297aad395ca532fdc76a348a72b86f88c7734a83b09",
    # meeting_records.congress_gov
    "ca89c3c86a7e4b9ae27d91f6964d82ae9e508b2527f95006137cd7bae062a31f":
        "325702c1794f246323ed30d7430650355121dd4891a7cea62b44a34a8ae5084d",
    # meeting_records.house_xml
    "4aab0f35642604d49dcaf17b7361598a18bbc85ad76e927b3590aa5e5d50155c":
        "24c88e855dab86f0c362387ffd4c40cf196e2a6f5c14d8aa1dba66f821ca0df5",
    # playlist_records.hls
    "415c89e149470ab532c64cdb7dc028398569e41aa04b28626ba9431c597bd14d":
        "53e6d0904cbc43c20c215505d012fdd054a5eb262d842478dfbdd6891ee4a557",
    # video_records.youtube_api
    "135af0c4bdd27729991bbf71138f145a1edbbc49eb945634cce1dd0cb1e38815":
        "8a15a14d1921489d4adb5b6f41e594c1d17b67466f716e9cb5994441a0738a4b",
    # video_records.youtube_cache
    "a57c3a1cd95e63d64a11b88c0e84ecb24ee0a247194d342a68b76eb6016266d1":
        "6efbae6d2d009baf72e0de5e60eba12307cd427f4900a2c892d36d6cc08ef3ba",
}

# Content-addressed body custody, table I/O, worker transport and this module.
# Bodies are verified by digest before parsing, so these packages cannot alter
# parsed values. Files that set refusal limits are hashed as declared inputs.
_PLUMBING = (
    'packages/congress_api/src/congress_api/retention',
    'packages/congress_api/src/congress_api/lake/tables.py',
    'packages/congress_api/src/congress_api/lake/readings.py',
    'packages/congress_api/src/congress_api/lake/compatible_versions.py',
    'packages/congress_api/src/congress_api/lake/versions.py',
    'packages/congress_shared/src/congress_shared/storage.py',
    'packages/docspec_client',
)


def version_digest(*, packages, files, values=None):
    """Hash package source/data recursively, explicit input files and vocabularies.

    Names and lengths delimit bytes, so moving a rule or changing a vocabulary
    changes the version. Runtime caches and build outputs never enter it.
    """
    digest = sha256()
    def add(name, data):
        label = name.encode('utf-8')
        digest.update(len(label).to_bytes(8, 'big')); digest.update(label)
        digest.update(len(data).to_bytes(8, 'big')); digest.update(data)
    for name, directory in sorted(packages.items()):
        directory = Path(directory)
        paths = sorted(path for path in directory.rglob('*')
                       if path.is_file() and path.suffix in {'.py', '.json', '.sql'}
                       and '__pycache__' not in path.parts)
        if not paths:
            raise ValueError('Version package has no source or data: ' + name)
        for path in paths:
            add('package/' + name + '/' + path.relative_to(directory).as_posix(), path.read_bytes())
    for name, path in sorted(files.items()):
        add('file/' + name, Path(path).read_bytes())
    add('values', json.dumps(values or {}, ensure_ascii=False, sort_keys=True,
                            separators=(',', ':'), allow_nan=False).encode('utf-8'))
    return digest.hexdigest()


def reviewed_producer_version(fingerprint):
    """Map a reviewed-equivalent producer fingerprint to its published ID, or return it unchanged."""
    return _REVIEWED_PRODUCER_VERSIONS.get(fingerprint, fingerprint)


def producer_version(*, root, module, files, packages=None, values=None):
    """A record producer's identity: its declared inputs plus the locked packages it imports.

    The import walk starts at the producer module, its declared Python files and
    package sources, and stops at plumbing. It reads no installed metadata, so
    every checkout with the same tree and lock computes the same identity.
    """
    root, packages = Path(root), packages or {}
    seeds = [Path(module), *(Path(path) for path in files.values() if Path(path).suffix == '.py'),
             *(path for directory in packages.values() for path in sorted(Path(directory).rglob('*.py'))
               if '__pycache__' not in path.parts)]
    locked = ImportClosure(root).locked_versions(seeds, stop=_PLUMBING)
    fingerprint = version_digest(packages=packages, files=files,
                                 values={**(values or {}), 'locked_imports': locked})
    return reviewed_producer_version(fingerprint)


def _normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


# Parsed imports keyed by package position and source bytes, so a repeated
# identity computation parses each unchanged file once per process.
_IMPORTS = {}


def _module_imports(data, parts, filename):
    for node in ast.walk(ast.parse(data, filename=filename)):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            module = node.module
            if node.level:
                module = '.'.join([*parts[:len(parts) - node.level + 1], *([module] if module else [])])
            if module:
                yield module
                yield from (f'{module}.{alias.name}' for alias in node.names)


class ImportClosure:
    """Follow static imports across this checkout and lock dependencies.

    This adapts the locked-package walk from 1f6effdf. Workspace resolution
    uses the checkout's source roots and never imports a module to inspect it.
    `distributions` maps import names to distribution names; without it an
    import name must be its locked distribution name.
    """

    def __init__(self, root, *, distributions=None):
        self.root = Path(root).resolve()
        self.entries = defaultdict(list)
        self.sources = []
        self.requested_extras = defaultdict(set)
        self.distributions = distributions or {}
        self._paths = {}
        self._listings = {}
        for entry in tomllib.loads((self.root / 'uv.lock').read_text())['package']:
            self.entries[_normalized(entry['name'])].append(entry)
            source = entry['source']
            location = source.get('editable', source.get('directory'))
            if location is not None:
                self.sources.append(self.root / location / 'src')
            if location is not None or 'virtual' in source:
                for edge in entry.get('dependencies', []):
                    self.requested_extras[_normalized(edge['name'])].update(edge.get('extra', []))

    def _workspace_path(self, parts):
        parts = tuple(parts)
        if parts not in self._paths:
            self._paths[parts] = next((path for source in self.sources for module in [source.joinpath(*parts)]
                                       for path in (module / '__init__.py', module.with_suffix('.py'))
                                       if self._exact_file(source, path)), None)
        return self._paths[parts]

    def _exact_file(self, source, path):
        """Whether `path` is a file whose every name below `source` is listed exactly, as Python imports it.

        A case-insensitive disk (macOS) also accepts house_naming/Engine.py for `from house_naming
        import Engine` and would hash engine.py again under a name Linux does not have (ct-p394).
        Each directory is listed once per closure."""
        directory = source
        for name in path.relative_to(source).parts:
            if directory not in self._listings:
                try:
                    self._listings[directory] = frozenset(os.listdir(directory))
                except OSError:
                    self._listings[directory] = frozenset()
            if name not in self._listings[directory]:
                return False
            directory = directory / name
        return path.is_file()

    def _imports(self, path):
        # Include imports inside functions, plus package initializers and possible
        # submodules named by "from package import name".
        parts, directory = [], path.parent
        while (directory / '__init__.py').is_file():
            parts.insert(0, directory.name)
            directory = directory.parent
        data = path.read_bytes()
        key = tuple(parts), sha256(data).digest()
        if key not in _IMPORTS:
            _IMPORTS[key] = list(_module_imports(data, parts, str(path)))
        return _IMPORTS[key]

    def reachable(self, files, *, stop=()):
        """Workspace files reached from `files` and the external top-level modules they import.

        A file under a `stop` prefix (relative to the root) is listed but not followed.
        """
        stop = {(self.root / prefix).resolve() for prefix in stop}
        seen, external = set(), set()
        pending = [self.root / file for file in files]
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            if path.suffix != '.py' or (stop and not stop.isdisjoint({resolved := path.resolve(), *resolved.parents})):
                continue
            for module in self._imports(path):
                parts = module.split('.')
                if parts[0] in sys.stdlib_module_names:
                    continue
                if self._workspace_path(parts[:1]) is None:
                    external.add(parts[0])
                    continue
                for depth in range(1, len(parts) + 1):
                    if (source := self._workspace_path(parts[:depth])) is not None and source not in seen:
                        pending.append(source)
        return seen, external

    def locked(self, modules):
        names, unresolved = set(), set()
        for module in modules:
            names_for_module = {_normalized(name) for name in self.distributions.get(module, [module])}
            names_for_module.intersection_update(self.entries)
            names.update(names_for_module)
            if not names_for_module:
                unresolved.add(module)
        seen = {}
        pending = [(name, self.requested_extras[name]) for name in names]
        while pending:
            name, extras = pending.pop()
            for i, entry in enumerate(self.entries[name]):
                key = name, i
                edges = [] if key in seen else list(entry.get('dependencies', []))
                followed = seen.setdefault(key, set())
                for extra in set(extras) - followed:
                    followed.add(extra)
                    edges.extend(entry.get('optional-dependencies', {}).get(extra, []))
                pending.extend((_normalized(edge['name']), edge.get('extra', [])) for edge in edges)
        packages = []
        for (name, i), extras in seen.items():
            entry = self.entries[name][i]
            packages.append(dict(
                name=name, version=entry['version'], source=entry['source'],
                marker=entry.get('resolution-markers', []), dependencies=entry.get('dependencies', []),
                extras={extra: entry.get('optional-dependencies', {}).get(extra, []) for extra in extras},
                sdist=entry.get('sdist'), wheels=entry.get('wheels', []),
            ))
        return dict(packages=sorted(packages, key=lambda item: json.dumps(item, sort_keys=True)),
                    unresolved=sorted(unresolved))

    def locked_versions(self, files, *, stop=()):
        """Name, version and source of each locked package `files` import, directly or through the lock.

        Refuses an import it cannot attribute to a locked package, rather than
        leaving it out of an identity.
        """
        # The seeds' own package roots are source even outside this tree's workspace.
        for path in map(Path, files):
            while (path.parent / '__init__.py').is_file():
                path = path.parent
            if path.parent not in self.sources:
                self.sources.append(path.parent)
        self._paths.clear()
        _, modules = self.reachable(files, stop=stop)
        # A workspace member absent from this tree is source, hashed through
        # declared files where it matters, never a locked release.
        locked = self.locked({module for module in modules if not all(
            {'editable', 'directory', 'virtual'} & entry['source'].keys()
            for entry in self.entries.get(_normalized(module), [{'source': {}}]))})
        if locked['unresolved']:
            raise ValueError('Imports without a locked package: ' + ', '.join(locked['unresolved']))
        return sorted((dict(name=p['name'], version=p['version'], source=p['source']) for p in locked['packages']),
                      key=lambda item: json.dumps(item, sort_keys=True))
