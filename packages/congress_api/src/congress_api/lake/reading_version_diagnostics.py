"""Advisory source and dependency fingerprints for declared reading versions."""
import argparse
import ast
from collections import defaultdict
from hashlib import sha256
from importlib.metadata import packages_distributions
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import tomllib

from congress_api.lake.versions import version_digest

ROOT = Path(__file__).resolve().parents[5]
SOURCE = Path('packages/congress_api/src/congress_api')
BASELINE = Path('model/reading-version-diagnostics.json')
SCHEMA = Path('model/lake/readings.schema.json')
BODY_TEXT_SCHEMA = Path('model/lake/body-text.schema.json')
DECLARATIONS = SOURCE / 'lake/reading_versions.py'
DRIVER = SOURCE / 'lake/readings.py'
SHARED_READING_FILES = (DRIVER, SOURCE / 'retention/parser_worker.py',
                        SOURCE / 'retention/process_resources.py')
BUNDLE_SQL = ('pinned-readings', 'sniff-observations', 'sniff-conflicts', 'sniff-facts', 'body-admissions')


def _normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


class ImportClosure:
    """Follow static imports across this checkout and lock dependencies.

    This adapts the locked-package walk from 1f6effdf. Workspace resolution
    uses the checkout's source roots and never imports a module to inspect it.
    """

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.entries = defaultdict(list)
        self.sources = []
        self.requested_extras = defaultdict(set)
        self.distributions = packages_distributions()
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
        for source in self.sources:
            module = source.joinpath(*parts)
            for path in (module / '__init__.py', module.with_suffix('.py')):
                if path.is_file():
                    return path
        return None

    def _imports(self, path):
        # Include imports inside functions, plus package initializers and possible
        # submodules named by "from package import name".
        parts, directory = [], path.parent
        while (directory / '__init__.py').is_file():
            parts.insert(0, directory.name)
            directory = directory.parent
        for node in ast.walk(ast.parse(path.read_bytes(), filename=str(path))):
            if isinstance(node, ast.Import):
                yield from (alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                module = node.module
                if node.level:
                    module = '.'.join([*parts[:len(parts) - node.level + 1], *([module] if module else [])])
                if module:
                    yield module
                    yield from (f'{module}.{alias.name}' for alias in node.names)

    def _reachable(self, files):
        seen, external = set(), set()
        pending = [self.root / file for file in files]
        while pending:
            path = pending.pop()
            if path in seen:
                continue
            seen.add(path)
            if path.suffix != '.py':
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

    def _locked(self, modules):
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

    def fingerprints(self, files, *, shared_files=()):
        workspace, modules = self._reachable(files)
        # The common dispatcher imports all readers. Include its bytes in each
        # leaf without attributing one parser's imports to every other parser.
        workspace.update(self.root / file for file in shared_files)
        return dict(
            workspace_sha256=version_digest(packages={}, files={
                path.relative_to(self.root).as_posix(): path for path in workspace
                # Declared IDs already appear in the snapshot. A bump for a
                # separate parser does not change this parser's source evidence.
                if path != self.root / DECLARATIONS
            }),
            locked_sha256=version_digest(packages={}, files={}, values=self._locked(modules)),
        )


def snapshot(root=ROOT):
    """Compute fingerprints separately from IDs, with policy and native tool evidence."""
    from congress_api.lake import compatible_versions, readings
    from congress_api.parsers.html_metadata import FORMATS, FORMAT_TIMEOUT_SECONDS
    from congress_api.retention.pdf_tools import reader_versions

    closure = ImportClosure(root)
    limits = dict(stored_bytes=readings.MAX_STORED_BYTES, decoded_bytes=readings.MAX_DECODED_BYTES,
                  page_parse_bytes=readings.PAGE_PARSE_MAX_BYTES)
    sniff = closure.fingerprints((SOURCE / 'retention/sniff.py', SCHEMA), shared_files=SHARED_READING_FILES)
    page = closure.fingerprints((SOURCE / 'parsers/archive_readings.py', SCHEMA), shared_files=SHARED_READING_FILES)
    metadata = closure.fingerprints((SOURCE / 'parsers/html_metadata.py', SCHEMA), shared_files=SHARED_READING_FILES)
    bundle = closure.fingerprints((DRIVER, SCHEMA, *(
        Path('model/sql') / f'{name}.sql' for name in BUNDLE_SQL
    )))
    pins = compatible_versions.current_pins()
    return {
        'sniff': dict(version=pins['sniff'], **sniff, readers=reader_versions()),
        **{parser: dict(version=pins[parser], **page, limits=limits) for parser in compatible_versions.PAGE_PARSERS},
        'html_metadata': dict(version=pins['html_metadata'], **metadata, limits=limits,
                              policy=readings.worker_limits('html_metadata'),
                              formats=list(FORMATS), format_timeout_seconds=FORMAT_TIMEOUT_SECONDS),
        'readings': dict(version=pins['readings'], **bundle, limits=limits, policy=readings.worker_limits()),
        **body_text_evidence(closure),
    }


def body_text_evidence(closure):
    """The body-text parsers' evidence (data model §6.6): source and lock closure, PyMuPDF,
    the spicy-docs derivation digest, the OCR page rule and bounds, and for PDF-reading parsers
    the macOS build OCR would run on (null on a host without Vision)."""
    from importlib.metadata import version
    from spicy_docs.extraction import BODY_TEXT_DERIVATION_VERSION, derivation_code_digest
    from congress_api.lake import body_text
    from congress_api.parsers import body_text as derivation
    code = closure.fingerprints((SOURCE / 'lake/body_text.py', SOURCE / 'parsers/body_text.py', BODY_TEXT_SCHEMA))
    common = dict(**code, limits=dict(stored_bytes=body_text.MAX_STORED_BYTES, decoded_bytes=body_text.MAX_DECODED_BYTES),
                  policy=body_text.worker_limits(), page_deadline_seconds=body_text.PAGE_DEADLINE_SECONDS,
                  spicy_docs=dict(version=version('spicy-docs'), derivation=BODY_TEXT_DERIVATION_VERSION,
                                  digest=derivation_code_digest()))
    pdf = dict(pymupdf=version('pymupdf'), ocr_rule=dict(min_chars=derivation.OCR_MIN_CHARS,
               garble=derivation.GARBLE, dpi=derivation.OCR_DPI, default_strategy=derivation.DEFAULT_STRATEGY,
               engine_strategy=derivation.VISION_STRATEGY), macos_build=derivation.macos_build())
    return {parser: dict(version=version_, **common, **(pdf if parser in ('pdf_text', 'warc') else {}))
            for parser, version_ in body_text.current_versions().items()}


def drift_messages(previous, current):
    """Name the changed evidence and preserve the declared selection."""
    for parser, new in current.items():
        old = previous.get(parser, {})
        # A host without Vision (macos_build null) cannot OCR, so its build is no evidence.
        ignored = {'sample_sha256'} | ({'macos_build'} if 'macos_build' in new and new['macos_build'] is None else set())
        fields = sorted(name for name in (set(old) | set(new)) - ignored if old.get(name) != new.get(name))
        if fields:
            yield parser, (f'{parser} reading version evidence changed ({", ".join(fields)}); '
                           f'using {new["version"]}. Record equivalence or a deliberate bump.')


def _case(parser):
    def body(root):
        cases = json.loads((root / 'model/fixtures/parser-cases.json').read_text())
        return next(case['body'] for case in cases if case['parser'] == parser).encode()
    return body


def _warc_case(root):
    """The html case inside a WARC response member; the record's date and ID reach no value."""
    import io
    from warcio.statusandheaders import StatusAndHeaders
    from warcio.warcwriter import WARCWriter
    out = io.BytesIO()
    writer = WARCWriter(out, gzip=True)
    writer.write_record(writer.create_warc_record('https://example.house.gov/', 'response',
        payload=io.BytesIO(_case('html')(root)), http_headers=StatusAndHeaders(
            '200 OK', [('Content-Type', 'text/html')], protocol='HTTP/1.1')))
    return out.getvalue()


BODY_TEXT_SAMPLES = {
    'pdf_text': lambda root: (root / 'packages/congress_api/tests/fixtures/document-covers/house-hearing.pdf').read_bytes(),
    'html_text': _case('html'),
    'xml_text': _case('xml'),
    'warc': _warc_case,
}


def sample_digest(parser, *, root=ROOT):
    """Re-read one fixed fixture through the relevant reader and compare its values."""
    from congress_api.lake import compatible_versions, readings
    from congress_api.retention.sniff import read_sniff

    if parser in BODY_TEXT_SAMPLES:
        from congress_api.lake.body_text import _sniff_format
        from congress_api.parsers import body_text as derivation
        reading = derivation.derive(BODY_TEXT_SAMPLES[parser](root), parser, strategy=derivation.native_only(),
            page_deadline_seconds=0, sniff_format=_sniff_format, max_bytes=64 << 20)
        values = dict(reading.row(), page_offsets=list(reading.page_offsets), ocr_pages=list(reading.ocr_pages))
    elif parser == 'html_metadata':
        fixture = root / 'packages/congress_api/tests/fixtures/html_metadata/marked-no-statement.html'
        values = readings.read_body(fixture.read_bytes(), parser)
    else:
        cases = json.loads((root / 'model/fixtures/parser-cases.json').read_text())
        sample_parser = 'html' if parser in {'sniff', 'readings'} else parser
        body = next(case['body'] for case in cases if case['parser'] == sample_parser).encode()
        if parser == 'sniff':
            values = read_sniff(lambda offset, length: body[offset:offset + length], stored_size=len(body))
            values.pop('parser_version')
        elif parser == 'readings':
            with TemporaryDirectory() as directory:
                path = Path(directory) / 'fixture.html'
                path.write_bytes(body)
                versions = {name: 'sample' for name in compatible_versions.LEAF_PARSERS}
                payload = json.dumps(dict(
                    path=str(path), cache=str(path.with_suffix('.cache')), stored_bytes=len(body),
                    versions=versions, known_format=None, skip_parsers=[],
                    body_sha=sha256(body).hexdigest(),
                )).encode()
                # Doctor already supervises this process. The fixed plain HTML
                # sample only needs a marker for its local reads.
                marker = 'DOCSPEC_PARSER_IO_MARKER'
                previous = os.environ.get(marker)
                os.environ[marker] = str(path.with_suffix('.phase'))
                try:
                    values = readings.parse_once_payload(payload)
                finally:
                    if previous is None:
                        os.environ.pop(marker, None)
                    else:
                        os.environ[marker] = previous
        else:
            values = readings.read_body(body, parser)
    return version_digest(packages={}, files={}, values=values)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='store_true', help='Print current evidence for maintainer review')
    args = parser.parse_args(argv)
    if args.snapshot:
        current = snapshot()
        for name, evidence in current.items():
            evidence['sample_sha256'] = sample_digest(name)
        print(json.dumps(current, indent=2, sort_keys=True))
        return
    try:
        previous = json.loads((ROOT / BASELINE).read_text())
        for name, warning in drift_messages(previous, snapshot()):
            print('WARNING: ' + warning, flush=True)
            try:
                expected = previous.get(name, {}).get('sample_sha256')
                outcome = 'unavailable' if expected is None else (
                    'matched' if sample_digest(name) == expected else 'changed')
                print(f'  {name} fixed fixture sample {outcome}. The sample covers only its fixture.')
            except Exception as exc:
                print(f'  {name} fixed fixture sample unavailable: {exc}')
    except (OSError, ValueError, KeyError, AttributeError, TypeError, SyntaxError) as exc:
        print(f'WARNING: Reading version diagnostics unavailable: {exc}')


if __name__ == '__main__':
    main()
