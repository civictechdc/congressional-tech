"""Compose retained final PDF pages; inherited pages keep their original interpretation.

This leaf reads pinned review artifacts and returns ordinary body-text/reading
values. It does not extract, normalize, migrate checkpoints, append or select.
The caller owns the source-review decision, not this integrity check.
"""
from hashlib import sha256
import json
from pathlib import Path
import re

from congress_api.parsers import body_text
from congress_api.retention import page_checkpoints
from congress_api.parsers.body_text import Reading, _PageRun, page_offsets
from congress_api.retention.page_checkpoints import unpack

DECLARATION = (
    'body_text pdf_text final-page composition v1: exact completed base reading and text; '
    'validated UTF-8 page starts and one-newline separators; replace only explicit source/page '
    'identities with pinned reviewed final UTF-8 text; preserve every inherited final page verbatim '
    'under its original reading interpretation; retain original replacement policy and intermediate '
    'identities; no extraction, normalization, checkpoint migration or automatic selection'
)
MAX_TEXT_BYTES = 64 << 20
MAX_ARTIFACT_BYTES = 16 << 20
MAX_REPLACEMENTS = 32
MAX_PAGES = 100_000


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('Expected a lowercase SHA-256 identity')
    return value


def _artifact(reference, limit=MAX_ARTIFACT_BYTES):
    if set(reference) != {'path', 'bytes', 'sha256'}:
        raise ValueError('An artifact requires its path, bytes and SHA-256')
    _digest(reference['sha256'])
    size = reference['bytes']
    if type(size) is not int or not 0 <= size <= limit:
        raise ValueError('Artifact exceeds the composition byte bound')
    with Path(reference['path']).open('rb') as source:
        data = source.read(size + 1)
    if len(data) != size or sha256(data).hexdigest() != reference['sha256']:
        raise ValueError('Composition artifact digest or byte count changed')
    return data


def _identity(reference):
    return {name: reference[name] for name in ('bytes', 'sha256')}


def _pages(text, offsets, count):
    if not isinstance(text, str) or len(text) > MAX_TEXT_BYTES:
        raise ValueError('Base text exceeds the composition byte bound')
    data = text.encode()
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError('Base text exceeds the composition byte bound')
    if (type(count) is not int or not 1 <= count <= MAX_PAGES or len(offsets) != count or not offsets
            or any(type(n) is not int for n in offsets) or offsets[0] != 0
            or any(not 0 <= n <= len(data) for n in offsets)
            or any(b <= a for a, b in zip(offsets, offsets[1:]))
            or any(data[n-1:n] != b'\n' for n in offsets[1:])):
        raise ValueError('Invalid final-page offsets or source page count')
    ends = [n-1 for n in offsets[1:]] + [len(data)]
    try:
        pages = [data[start:end].decode() for start, end in zip(offsets, ends)]
    except UnicodeDecodeError as error:
        raise ValueError('Page offsets split a UTF-8 character') from error
    if tuple(offsets) != page_offsets(pages) or '\n'.join(pages) != text:
        raise ValueError('Page offsets do not reproduce the base text')
    return pages, data


def compose_pages(base, base_reading, *, source_bytes, source_page_count, source_evidence, replacements):
    """Return (body_text row, Reading, receipt) without mutating the base.

    Each replacement names page, policy, intermediate, final and review. The
    intermediate is an unchanged CT-packed PageResult, not a rewritten cache
    record. File pins are {path, bytes, sha256}; locators do not enter the new
    reading version. Source evidence binds the caller's physical page count.
    """
    if (base.get('parser') != 'pdf_text' or base_reading.get('status') != 'completed'
            or base_reading.get('error_type') is not None
            or any(base.get(k) != base_reading.get(k) for k in ('body_sha', 'parser', 'parser_version'))):
        raise ValueError('Composition requires the exact completed PDF base reading')
    body = base['body_sha']
    if not isinstance(body, bytes) or len(body) != 32:
        raise ValueError('Invalid base body identity')
    _digest(base['parser_version'])
    if type(source_bytes) is not int or source_bytes < 1:
        raise ValueError('Explicit source byte count is required')
    pages, data = _pages(base['text'], base['page_offsets'], source_page_count)
    text_hash = sha256(data).digest()
    if base.get('text_sha256') != text_hash or base_reading.get('text_bytes') != len(data):
        raise ValueError('Base text digest or reading byte count changed')
    ocr = base['ocr_pages']
    if (any(type(n) is not int or not 1 <= n <= source_page_count for n in ocr)
            or list(ocr) != sorted(set(ocr))):
        raise ValueError('Invalid base OCR page identities')
    if ocr and (not isinstance(base.get('macos_build'), str) or not base['macos_build']):
        raise ValueError('Base OCR build is unavailable')
    _artifact(source_evidence)
    if not isinstance(replacements, (list, tuple)) or not 1 <= len(replacements) <= MAX_REPLACEMENTS:
        raise ValueError('Composition requires a bounded nonempty replacement list')
    numbers = []
    for replacement in replacements:
        if set(replacement) != {'page', 'policy', 'intermediate', 'final', 'review'}:
            raise ValueError('A replacement requires page, policy, intermediate, final and review')
        n = replacement['page']
        if type(n) is not int or not 1 <= n <= source_page_count or n in numbers:
            raise ValueError('Duplicate or invalid replacement page')
        numbers.append(n)

    inherited_ocr = set(ocr) - set(numbers)
    builds = {base['macos_build']} if inherited_ocr else set()
    output_ocr = set(inherited_ocr)
    resolved = []
    final_bytes = len(data)
    for replacement in sorted(replacements, key=lambda row: row['page']):
        number = replacement['page']
        policy = _artifact(replacement['policy'], 64 << 10)
        intermediate = _artifact(replacement['intermediate'])
        final = _artifact(replacement['final'])
        _artifact(replacement['review'])
        # A policy is retained as original evidence, never assigned to inherited pages.
        policy_value = json.loads(policy)
        if (not isinstance(policy_value, dict) or not isinstance(policy_value.get('backend'), dict)
                or not isinstance(policy_value.get('reader'), dict)
                or not isinstance(policy_value['backend'].get('backend'), str)
                or type(policy_value['reader'].get('dpi')) is not int or policy_value['reader']['dpi'] < 1):
            raise ValueError('Replacement policy must retain its actual settings object')
        packed = json.loads(intermediate)
        meta = packed.get('metadata', {})
        if (meta.get('source_sha256') != body.hex() or meta.get('page') != number
                or type(meta.get('page')) is not int
                or meta.get('page_count') != source_page_count or type(meta.get('page_count')) is not int):
            raise ValueError('Replacement intermediate has the wrong source or page identity')
        if type(meta.get('source_size_bytes')) is not int or meta['source_size_bytes'] != source_bytes:
            raise ValueError('Replacement intermediate has the wrong source byte identity')
        if meta.get('media_type') != 'application/pdf':
            raise ValueError('Replacement intermediate is not a PDF page')
        if meta.get('geometry', {}).get('dpi') != policy_value['reader'].get('dpi'):
            raise ValueError('Replacement reader settings disagree with the intermediate')
        observed = unpack(packed)
        accounting = _PageRun(None, 0)
        accounting.observe(observed.content, number)
        if any(o.configuration.get('backend') != 'apple-vision' for o in observed.content.observations
               if o.id != 'native' or any(i.code == body_text.REPLACED_ISSUE for i in o.issues)):
            raise ValueError('Composition supports retained native or Apple Vision page observations')
        if any(o.configuration != policy_value['backend'] for o in observed.content.observations
               if o.id != 'native' or any(i.code == body_text.REPLACED_ISSUE for i in o.issues)):
            raise ValueError('Replacement backend settings disagree with the intermediate')
        if accounting.ocr and len(accounting.builds) != 1:
            raise ValueError('Replacement OCR build is unavailable or ambiguous')
        output_ocr.update(accounting.ocr)
        builds.update(accounting.builds)
        try:
            text = final.decode()
        except UnicodeDecodeError as error:
            raise ValueError('Replacement final text is not UTF-8') from error
        final_bytes += len(final) - len(pages[number-1].encode())
        if final_bytes > MAX_TEXT_BYTES:
            raise ValueError('Composed text exceeds the byte bound')
        pages[number-1] = text
        resolved.append(dict(page=number, source_sha256=body.hex(), source_bytes=meta['source_size_bytes'],
            source_page_count=source_page_count,
            **{name: _identity(replacement[name]) for name in ('policy', 'intermediate', 'final', 'review')},
            policy_settings={key: policy_value[key] for key in (
                'backend', 'reader', 'routing', 'strategy', 'min_chars', 'require_images', 'garble',
                'native_normalization', 'final_normalization', 'cleanup') if key in policy_value},
            ocr=bool(accounting.ocr), macos_build=next(iter(accounting.builds), None)))
    if len({row['source_bytes'] for row in resolved}) != 1:
        raise ValueError('Replacement source byte identities disagree')
    if len(builds) > 1:
        raise ValueError('Composed OCR pages have different macOS builds')
    provenance = dict(
        declaration=DECLARATION,
        implementation={name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
            ('composition', __file__), ('body_text', body_text.__file__),
            ('page_checkpoints', page_checkpoints.__file__))},
        base=dict(body_sha256=body.hex(), parser='pdf_text', parser_version=base['parser_version'],
                  text_sha256=text_hash.hex(), text_bytes=len(data), page_offsets=list(base['page_offsets']),
                  ocr_pages=list(ocr), macos_build=base.get('macos_build')),
        source_bytes=source_bytes, source_page_count=source_page_count, source_evidence=_identity(source_evidence),
        replacements=resolved,
        inherited_interpretation='Each unreplaced final page retains its original base reading interpretation.',
    )
    version = sha256(_encoded(provenance)).hexdigest()
    text = '\n'.join(pages)
    reading = Reading('completed', text=text, page_offsets=page_offsets(pages),
        ocr_pages=tuple(sorted(output_ocr)), macos_build=next(iter(builds), None),
        fields=dict(page_count=source_page_count, ocr_pages=len(output_ocr),
                    page_composition_sha256=version, page_composition=_encoded(provenance).decode()))
    row = dict(body_sha=body, parser='pdf_text', parser_version=version, text=text,
               page_offsets=list(reading.page_offsets), ocr_pages=list(reading.ocr_pages),
               text_sha256=sha256(text.encode()).digest(), macos_build=reading.macos_build)
    receipt = dict(provenance=provenance, parser_version=version, inherited_pages=source_page_count-len(numbers),
                   replaced_pages=sorted(numbers), text_sha256=row['text_sha256'].hex(),
                   text_bytes=len(text.encode()), sources=[dict(r) for r in replacements],
                   source_evidence=dict(source_evidence), selection_performed=False, publication_performed=False)
    return row, reading, receipt

