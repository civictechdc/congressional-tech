"""Advisory source and dependency fingerprints for declared reading versions."""
import argparse
from hashlib import sha256
from importlib.metadata import packages_distributions
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from congress_api.lake.versions import ImportClosure, version_digest

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


def _fingerprints(closure, files, *, shared_files=()):
    workspace, modules = closure.reachable(files)
    # The common dispatcher imports all readers. Include its bytes in each
    # leaf without attributing one parser's imports to every other parser.
    workspace.update(closure.root / file for file in shared_files)
    return dict(
        workspace_sha256=version_digest(packages={}, files={
            path.relative_to(closure.root).as_posix(): path for path in workspace
            # Declared IDs already appear in the snapshot. A bump for a
            # separate parser does not change this parser's source evidence.
            if path != closure.root / DECLARATIONS
        }),
        locked_sha256=version_digest(packages={}, files={}, values=closure.locked(modules)),
    )


def snapshot(root=ROOT):
    """Compute fingerprints separately from IDs, with policy and native tool evidence."""
    from congress_api.lake import compatible_versions, readings
    from congress_api.parsers.html_metadata import FORMATS, FORMAT_TIMEOUT_SECONDS
    from congress_api.retention.pdf_tools import reader_versions

    closure = ImportClosure(root, distributions=packages_distributions())
    limits = dict(stored_bytes=readings.MAX_STORED_BYTES, decoded_bytes=readings.MAX_DECODED_BYTES,
                  page_parse_bytes=readings.PAGE_PARSE_MAX_BYTES)
    sniff = _fingerprints(closure, (SOURCE / 'retention/sniff.py', SCHEMA), shared_files=SHARED_READING_FILES)
    page = _fingerprints(closure, (SOURCE / 'parsers/archive_readings.py', SCHEMA), shared_files=SHARED_READING_FILES)
    metadata = _fingerprints(closure, (SOURCE / 'parsers/html_metadata.py', SCHEMA), shared_files=SHARED_READING_FILES)
    bundle = _fingerprints(closure, (DRIVER, SCHEMA, *(
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
    code = _fingerprints(closure, (SOURCE / 'lake/body_text.py', SOURCE / 'parsers/body_text.py', BODY_TEXT_SCHEMA))
    common = dict(**code, limits=dict(stored_bytes=body_text.MAX_STORED_BYTES, decoded_bytes=body_text.MAX_DECODED_BYTES),
                  policy=body_text.worker_limits(), page_deadline_seconds=body_text.PAGE_DEADLINE_SECONDS,
                  spicy_docs=dict(version=version('spicy-docs'), derivation=BODY_TEXT_DERIVATION_VERSION,
                                  digest=derivation_code_digest()))
    rule = derivation.native_only().strategy  # the declared routing, read off the object, not restated
    name = lambda function: f'{function.__module__}.{function.__qualname__}'
    pdf = dict(pymupdf=version('pymupdf'), ocr_rule=dict(min_chars=rule.min_chars,
               require_images=rule.require_images, garble=name(rule.garble), normalize=name(rule.normalize),
               bands=derivation.OCR_BANDS, dpi=derivation.OCR_DPI, default_strategy=derivation.DEFAULT_STRATEGY,
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
