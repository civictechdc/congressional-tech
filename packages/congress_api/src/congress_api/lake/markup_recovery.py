"""Explicit, review-pinned markup recovery; ordinary readers never enter here."""
from dataclasses import asdict, replace
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path

from congress_api.lake.reading_versions import MARKUP_RECOVERY_BASE_VERSIONS, MARKUP_RECOVERY_VERSIONS, READING_VERSIONS
from congress_api.parsers.body_text import Reading, markup_text

POLICIES = {'html_text': 'html-windows-1252-v1', 'xml_text': 'xml-literals-v1'}
HELPER_SHA256 = 'bd653b578f22d0b0cb1840d5a1d64fdc3125e05dafb3b380d701b13d9b360479'
MAX_BYTES = 64 << 20
MAX_MANIFEST_BYTES = 1 << 20
CASE_FIELDS = {'body_sha256', 'parser', 'policy', 'candidate_sha256', 'text_sha256', 'review_sha256'}


class RecoveryInputError(ValueError):
    """Bad review inputs or output drift leave work pending, not settled as a reading."""


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def validate_case(case):
    if not isinstance(case, dict) or set(case) != CASE_FIELDS:
        raise RecoveryInputError('Recovery case must name exact source, policy, candidate, text and review pins')
    if case['parser'] not in POLICIES or case['policy'] != POLICIES[case['parser']]:
        raise RecoveryInputError('Unsupported reviewed markup recovery policy')
    if not all(_digest(case[key]) for key in CASE_FIELDS - {'parser', 'policy'}):
        raise RecoveryInputError('Recovery pins must be lowercase SHA-256 digests')


def load_manifest(reference):
    """Load bounded explicit review inputs; this does not select any lake reading."""
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'} or not _digest(reference['sha256']):
        raise RecoveryInputError('Recovery requires a manifest path and exact SHA-256')
    with Path(reference['path']).open('rb') as stream:
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES or sha256(raw).hexdigest() != reference['sha256']:
        raise RecoveryInputError('Recovery manifest exceeds its bound or differs from its pin')
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or set(manifest) != {'version', 'cases'}
            or not isinstance(manifest['version'], int) or isinstance(manifest['version'], bool) or manifest['version'] != 1
            or not isinstance(manifest['cases'], list) or not 0 < len(manifest['cases']) <= 4096):
        raise RecoveryInputError('Expected a version 1 recovery manifest with bounded cases')
    cases = {}
    for case in manifest['cases']:
        validate_case(case)
        if case['body_sha256'] in cases:
            raise RecoveryInputError('Duplicate recovery source key')
        cases[case['body_sha256']] = case
    return cases


def stage_cases(planned, items, reference):
    """Bind every staged key to its reviewed meaning before workers or source reads."""
    cases = load_manifest(reference)
    if not planned['versions'] or any(MARKUP_RECOVERY_VERSIONS.get(p) != v for p, v in planned['versions'].items()):
        raise RecoveryInputError('Markup recovery requires its separate declared reading versions')
    selected = {}
    for item in items:
        body = item['body_sha'].hex()
        case = cases.get(body)
        if (case is None or item['parser'] != case['parser']
                or item['parser_version'] != MARKUP_RECOVERY_VERSIONS[case['parser']]
                or planned['versions'].get(case['parser']) != item['parser_version'] or body in selected):
            raise RecoveryInputError('Staged key is missing, duplicated or differs from its recovery review')
        selected[body] = dict(case=case, manifest_sha256=reference['sha256'])
    return selected


def read_reviewed_markup(data, request, *, evidence_dir):
    """Run original -> bounded candidate -> actual CT reader, preserving each identity.

    A helper refusal remains an error with no text. Review/hash drift is a pending
    input failure. A completed reading still requires separate publication selection.
    """
    from spicy_docs.reading import markup_recovery as helper

    case = request['case']
    validate_case(case)
    if READING_VERSIONS[case['parser']] != MARKUP_RECOVERY_BASE_VERSIONS[case['parser']]:
        raise RecoveryInputError('Ordinary reader declaration changed; recovery requires renewed qualification')
    if not _digest(request.get('manifest_sha256')):
        raise RecoveryInputError('Missing recovery manifest identity')
    if len(data) > MAX_BYTES or sha256(data).hexdigest() != case['body_sha256']:
        raise RecoveryInputError('Recovery original exceeds its bound or differs from its reviewed identity')
    if sha256(Path(helper.__file__).read_bytes()).hexdigest() != HELPER_SHA256:
        raise RecoveryInputError('Recovery helper differs from the reviewed source')
    original = markup_text(data, case['parser'])
    if original.status == 'completed':
        raise RecoveryInputError('Ordinary markup already completes; no reviewed refusal to recover')
    directory = Path(evidence_dir)
    directory.mkdir(parents=True, exist_ok=False)

    def write(name, body):
        path = directory / name
        with path.open('xb') as stream:
            stream.write(body)
        return dict(path=str(path), sha256=sha256(body).hexdigest(), bytes=len(body))

    def write_json(name, value):
        return write(name, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())

    files = dict(original=write('original.raw', data), original_reading=write_json('original-reading.json', original.row()))
    if original.diagnostic:
        files['original_diagnostic'] = write('original-diagnostic.txt', original.diagnostic.encode())
    repair = (helper.recover_html_encoding_candidate(data, source_encoding='windows-1252')
              if case['parser'] == 'html_text' else helper.recover_xml_literal_candidate(data))
    metadata = asdict(repair)
    candidate = metadata.pop('candidate_body')
    for edit in metadata['changes']:
        edit['original_hex'] = edit.pop('original').hex()
        edit['replacement_hex'] = edit.pop('replacement').hex()
    metadata.update(review=case, manifest_sha256=request['manifest_sha256'], helper_sha256=HELPER_SHA256,
                    spicy_docs_version=version('spicy-docs'), adapter_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                    consumer_source_sha256=sha256(Path(markup_text.__code__.co_filename).read_bytes()).hexdigest(),
                    original_parser_version=READING_VERSIONS[case['parser']],
                    recovery_parser_version=MARKUP_RECOVERY_VERSIONS[case['parser']], selected=False)
    files['recovery'] = write_json('recovery.json', metadata)
    fields = dict(source_sha256=case['body_sha256'], recovery_policy=case['policy'], recovery_status=repair.status,
                  recovery_evidence=json.dumps(files['recovery'], sort_keys=True),
                  recovery_review_sha256=case['review_sha256'], recovery_manifest_sha256=request['manifest_sha256'],
                  recovery_helper_sha256=HELPER_SHA256, recovery_spicy_docs_version=version('spicy-docs'))
    if candidate is None:
        result = Reading('error', 'MarkupRecoveryRefused', fields=fields, diagnostic=repair.reason)
    else:
        files['candidate'] = write('candidate.raw', candidate)
        if repair.candidate_sha256 != case['candidate_sha256']:
            write_json('input-refusal.json', dict(reason='candidate_digest_differs', files=files))
            raise RecoveryInputError('Recovered candidate differs from the reviewed bytes')
        result = markup_text(candidate, case['parser'])
        if result.text is not None and sha256(result.text.encode()).hexdigest() != case['text_sha256']:
            files['unmatched_text'] = write('unmatched-text.txt', result.text.encode())
            write_json('input-refusal.json', dict(reason='text_digest_differs', files=files))
            raise RecoveryInputError('Recovered text differs from the reviewed output')
        fields.update(candidate_sha256=repair.candidate_sha256, candidate_bytes=repair.candidate_bytes,
                      recovery_byte_positions_address='candidate')
        result = replace(result, fields=dict(result.fields, **fields))
    if result.text is not None:
        files['text'] = write('text.txt', result.text.encode())
    write_json('output.json', dict(schema='ct-reviewed-markup-recovery-v1',
        reading_key=dict(body_sha256=case['body_sha256'], parser=case['parser'],
                         parser_version=MARKUP_RECOVERY_VERSIONS[case['parser']]),
        reading=result.row(), files=files, selected=False))
    return result
