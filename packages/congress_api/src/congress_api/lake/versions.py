"""Content versions for parser packages, their inputs and the locked packages they import."""
import ast
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import tomllib


# ct-an6o: producer identities hashed the whole uv.lock until this change, so
# every unrelated patch moved them. They now hash the locked packages their
# parsers import. At the switch, the old rule computed exactly the published
# IDs below from the same tree; each new fingerprint maps to that published ID.
# Any later source, schema, parameter or imported-package change produces an
# unmapped fingerprint. Add an entry only with a reviewed equivalence decision.
_REVIEWED_PRODUCER_VERSIONS = {
    # appearance_records.congress_gov
    "7f9ac402f23815c37f5c53dec202ea9094abf172dd8bd32a9efa6b811a779252":
        "6d9460f5ec203c24c508846092505a875710f565e1ff026479b542c7555e7d48",
    # appearance_records.house_xml
    "2daadbeb9c249c4dc19b58969ef6f9305392b1aafcffdcf6d5b826f763d5a69e":
        "5078ef426e0e262ffcd972b244c3b472669583f164121cc6189ccf69e6abf3a5",
    # appearance_records.mods
    "059195144f6963fd02f8062ae7eb45084f9cfe3033eaf0a2e575dfd635cd1241":
        "1d57eb4426f67b84116bdb4a66774d0e401668b277586939b5c014db8547e32e",
    # appearance_records.senate_page
    "d2faf6985353f72219cd6a8a99feebb142170e4936c1d1eefad9d91de654e67a":
        "9d48c0f61a9f8ab1407c07f9c49cba7d6e9253a6369d73a8d14389d9bfee6bbb",
    # committee_records.house_xml
    "6c2519acf32de655f13ca491eaa3808dd68a9328ed49d76663989a3d18044b28":
        "e1c6ad0d1398f1d1985e085a0fb9b94c6c42ad38a2d9175ad3e8908eb46c531e",
    # filename_readings
    "59d2a03312cff0ac590bf8b3da6aee712f39b6cbc37af96b2ce8d4e79b3a5312":
        "c65e505ef8eb085e38072297aad395ca532fdc76a348a72b86f88c7734a83b09",
    # meeting_records.congress_gov
    "5a7309c794d57c040addbb5db3d3cf18acd02faf56dfb703129383709c3d8f8c":
        "325702c1794f246323ed30d7430650355121dd4891a7cea62b44a34a8ae5084d",
    # meeting_records.house_xml
    "75cb286456a185f89c0081658d4569ced72a148324155df91d2f0945681f3c71":
        "24c88e855dab86f0c362387ffd4c40cf196e2a6f5c14d8aa1dba66f821ca0df5",
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
    return _REVIEWED_PRODUCER_VERSIONS.get(fingerprint, fingerprint)


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
                                       if path.is_file()), None)
        return self._paths[parts]

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
