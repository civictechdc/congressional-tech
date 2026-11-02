"""The contract of the context-free HTML metadata reader."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from congress_api.lake import readings
from congress_api.parsers import html_metadata as reader
from congress_api.parsers.html_metadata import FORMATS, page_is_substantive, read_html_metadata

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = (Path(__file__).parent / 'fixtures/html_metadata/all-formats.html').read_bytes()
PLAIN = b'<html><head><title>t</title></head><body><p>nothing declared</p></body></html>'


def test_every_format_generic_tags_and_repeated_keys_survive():
    result = read_html_metadata(FIXTURE)
    assert {name: result.formats[name].status for name in FORMATS} == dict.fromkeys(FORMATS, 'ok')
    assert result.title == 'Hearing page' and result.document_kind == 'html' and not result.error_title_hint
    assert result.body_sha256 == hashlib.sha256(FIXTURE).hexdigest() and result.body_bytes == len(FIXTURE)
    assert [m['content'] for m in result.head_meta if m.get('property') == 'article:tag'] == ['first', 'second']
    assert [k for k, v in result.formats['opengraph'].items[0]['properties'] if k == 'article:tag'] == ['article:tag'] * 2
    assert [l['rel'] for l in result.head_links] == ['canonical', 'stylesheet']


def test_unknown_properties_survive():
    assert read_html_metadata(FIXTURE).formats['json-ld'].items[0]['unknownProperty'] == 'kept'


def test_malformed_neighbour_leaves_other_formats_ok():
    body = FIXTURE.replace(b'"unknownProperty": "kept"}', b'"unknownProperty": }}}')
    result = read_html_metadata(body)
    assert result.formats['json-ld'].status == 'failed' and result.formats['json-ld'].error_type
    assert all(result.formats[name].status == 'ok' for name in FORMATS if name != 'json-ld')


def test_absent_failed_and_skipped_are_distinct():
    absent = read_html_metadata(PLAIN)
    assert absent.formats['microformat'].status == 'absent' and absent.formats['microformat'].basis == 'marker'
    assert absent.formats['json-ld'].status == 'absent' and absent.formats['json-ld'].basis == 'extractor'
    only = read_html_metadata(FIXTURE, formats=('opengraph',))
    assert only.formats['opengraph'].status == 'ok'
    assert only.formats['rdfa'].status == 'skipped' and only.formats['rdfa'].skip_reason == 'not_requested'


def test_marker_bypass_does_not_run_the_extractor(monkeypatch):
    import extruct
    called = []
    real = extruct.extract
    monkeypatch.setattr(extruct, 'extract', lambda *a, **k: called.append(k['syntaxes']) or real(*a, **k))
    read_html_metadata(PLAIN.replace(b'<p>', b'<p id="x">'))
    assert ['microformat'] not in called and ['rdfa'] not in called


def test_recursion_failure_is_failed_not_empty():
    body = b'<html><body>' + b'<div class="h-entry">' * 3000 + b'x' + b'</div>' * 3000 + b'<meta property="og:title" content="t"></body></html>'
    result = read_html_metadata(body).formats
    assert result['microformat'].status == 'failed' and result['microformat'].error_type == 'RecursionError'
    assert result['opengraph'].status != 'failed' or result['opengraph'].error_type == 'RecursionError'


def test_deadline_marks_timeout_and_restores_handler(monkeypatch):
    import signal
    import extruct
    import time
    real = extruct.extract
    def slow(body, **kwargs):
        if kwargs['syntaxes'] == ['rdfa']:
            try:
                time.sleep(5)
            except Exception:  # a library's handler must not swallow the deadline
                pass
        return real(body, **kwargs)
    monkeypatch.setattr(extruct, 'extract', slow)
    previous = signal.getsignal(signal.SIGALRM)
    result = read_html_metadata(FIXTURE, format_timeout_seconds=0.05)
    assert result.formats['rdfa'].status == 'failed' and result.formats['rdfa'].error_type == 'format_timeout'
    assert result.formats['opengraph'].status == 'ok' and result.wall_clock_dependent
    assert signal.getsignal(signal.SIGALRM) == previous and signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_non_html_is_skipped_and_not_substantive():
    result = read_html_metadata(b'%PDF-1.7 not markup')
    assert result.document_kind == 'non_html'
    assert {r.status for r in result.formats.values()} == {'skipped'} and result.formats['rdfa'].skip_reason == 'non_html'
    assert not page_is_substantive(result, 200)


def test_error_page_rich_in_opengraph_is_not_substantive():
    body = FIXTURE.replace(b'<title>Hearing page</title>', b'<title>Page Not Found | Committee</title>')
    result = read_html_metadata(body)
    assert result.error_title_hint and result.formats['opengraph'].status == 'ok'
    assert not page_is_substantive(result, 200)
    assert not page_is_substantive(read_html_metadata(FIXTURE), 404)
    assert page_is_substantive(read_html_metadata(FIXTURE), 200)


def test_error_markers_cover_capture_inspection():
    source = (ROOT / 'packages/congress_api/src/congress_api/retention/capture_inspection.py').read_text()
    titles = re.findall(r'b"<title>([^"]+)"', source)
    assert titles and set(titles) <= set(reader.ERROR_TITLE_MARKERS)


def test_relative_urls_stay_literal():
    formats = read_html_metadata(FIXTURE).formats
    text = json.dumps({name: formats[name].items for name in FORMATS})
    assert '/relative/ld' in text and '/relative/md' in text and '/relative/og' in text and '/relative/rd' in text
    assert 'http://' not in json.dumps(formats['microdata'].items[0]['properties'])
    assert not formats['microformat'].urls_resolved_against_base


def test_base_resolved_microformat_urls_are_flagged():
    body = FIXTURE.replace(b'<title>', b'<base href="https://base.example/x/"><title>', 1)
    result = read_html_metadata(body)
    assert result.declared_base == 'https://base.example/x/'
    assert result.formats['microformat'].urls_resolved_against_base
    assert 'https://base.example/relative/ev' in json.dumps(result.formats['microformat'].items)
    assert '/relative/md' in json.dumps(result.formats['microdata'].items)
    assert 'base.example' not in json.dumps(result.formats['microdata'].items)


@pytest.mark.parametrize('codec,bom', [('utf-16-le', b'\xff\xfe'), ('utf-16-be', b'\xfe\xff')])
def test_utf16_bodies(codec, bom):
    page = '<html><head><title>Café</title><meta property="og:title" content="Café"></head></html>'
    result = read_html_metadata(bom + page.encode(codec))
    assert result.title == 'Café' and result.formats['opengraph'].items[0]['properties'] == [['og:title', 'Café']]


def test_declared_latin1_body():
    page = '<html><head><meta charset="iso-8859-1"><title>Café</title><meta property="og:title" content="Café"></head></html>'
    result = read_html_metadata(page.encode('iso-8859-1'))
    assert result.title == 'Café' and result.formats['opengraph'].items[0]['properties'] == [['og:title', 'Café']]


def test_result_is_identical_across_hash_seeds_and_runs():
    # role= yields blank nodes: random IDs each run, and a set's order under each seed.
    body = FIXTURE.replace(b'<body>', b'<body><a role="button">a</a><b role="presentation">b</b>'
                           b'<div typeof="foaf:Person" rel="foaf:knows" xmlns:foaf="http://xmlns.com/foaf/0.1/">'
                           b'<i typeof="foaf:Person" property="foaf:name">Same</i><i typeof="foaf:Person" property="foaf:name">Same</i></div>')
    code = ('import hashlib,json,sys; from congress_api.parsers.html_metadata import read_html_metadata as r; '
            'print(hashlib.sha256(json.dumps(r(sys.stdin.buffer.read()).source_dict(),sort_keys=True).encode()).hexdigest())')
    digests = {subprocess.run([sys.executable, '-c', code], input=body, capture_output=True, check=True,
                              env={**os.environ, 'PYTHONHASHSEED': seed}).stdout for seed in ('1', '2', '3')}
    assert len(digests) == 1 and len(digests.pop()) > 60


def test_rdfa_blank_nodes_keep_their_references():
    items = [{'@id': '_:random', 'http://p': [{'@id': '_:other'}]}, {'@id': '_:other', 'http://q': [{'@value': 'v'}]}]
    canonical = reader._canonical_rdfa(items)
    by_value = next(item for item in canonical if 'http://q' in item)
    assert next(item for item in canonical if 'http://p' in item)['http://p'] == [{'@id': by_value['@id']}]
    assert 'random' not in json.dumps(canonical) and 'other' not in json.dumps(canonical)


def relabelled(items, prefix):
    return json.loads(json.dumps(items).replace('_:n', '_:' + prefix))


@pytest.mark.parametrize('items', [
    [{'@id': f'_:n{i}', 'http://p': [{'@id': f'_:n{i + 1}'}]} for i in range(40)] + [{'@id': '_:n40', 'http://q': [{'@value': 'end'}]}],
    [item for i in range(6) for item in ({'@id': f'_:n{i}', 'http://p': [{'@id': f'_:nc{i}'}]}, {'@id': f'_:nc{i}', 'http://q': [{'@value': 'same'}]})],
], ids=['chain-past-any-round-cap', 'identical-pairs'])
def test_rdfa_labels_do_not_depend_on_input_ids_or_order(items):
    first = reader._canonical_rdfa(items)
    assert first == reader._canonical_rdfa(list(reversed(relabelled(items, 'zz'))))


def test_rdfa_cycle_of_alike_nodes_fails_the_format(monkeypatch):
    # Two 2-cycles and one 4-cycle look alike to refinement; merging them would invent a fact.
    cycle = [{'@id': f'_:n{i}', 'http://p': [{'@id': f'_:n{(i + 1) % 4}'}]} for i in range(4)]
    with pytest.raises(ValueError, match='cycle'):
        reader._canonical_rdfa(cycle)
    import extruct
    monkeypatch.setattr(extruct, 'extract', lambda body, **kwargs: {'rdfa': cycle})
    assert reader._read_format(b'<html></html>', 'rdfa', 1.0).status == 'failed'


@pytest.mark.parametrize('charset', ['zlib', 'undefined', 'rot13', 'hex', 'no-such-codec'])
def test_a_declared_charset_never_raises(charset):
    body = f'<html><head><meta charset={charset}><title>Caf\u00e9</title><meta property="og:title" content="t"></head></html>'.encode()
    result = read_html_metadata(body)
    assert result.title == 'Caf\u00e9' and result.formats['opengraph'].status == 'ok'


def test_content_past_the_parser_depth_is_failed_not_absent():
    deep = b'<div>' * 300 + b'<p property="schema:name" itemprop="name">x</p>' + b'</div>' * 300
    result = read_html_metadata(b'<html><head><title>t</title><meta property="og:title" content="o"></head><body>' + deep + b'</body></html>')
    assert result.document_truncated
    assert result.formats['rdfa'].error_type == 'document_too_deep' and result.formats['microdata'].error_type == 'document_too_deep'
    assert result.formats['opengraph'].status == 'ok'


def test_depth_is_detected_past_many_earlier_parser_errors():
    noisy = b'<div></span></div>' * 5000 + b'<div>' * 300 + b'x' + b'</div>' * 300
    assert read_html_metadata(b'<html><body>' + noisy + b'</body></html>').document_truncated


def test_shallow_document_is_not_truncated():
    assert not read_html_metadata(FIXTURE).document_truncated


def test_machine_dependent_failures_are_marked_not_reusable(monkeypatch):
    assert not read_html_metadata(FIXTURE).wall_clock_dependent
    import extruct
    real = extruct.extract
    def fail(body, **kwargs):
        if kwargs['syntaxes'] == ['rdfa']:
            raise MemoryError
        return real(body, **kwargs)
    monkeypatch.setattr(extruct, 'extract', fail)
    assert read_html_metadata(FIXTURE).wall_clock_dependent


def test_legacy_roots_cover_the_installed_mf2py_rules():
    import mf2py
    rules = {path.stem for path in (Path(mf2py.__file__).parent / 'backcompat-rules').glob('*.json')}
    assert rules and rules <= set(reader.MICROFORMAT_LEGACY_ROOTS)


def test_version_tracks_lock_options_and_source(monkeypatch, tmp_path):
    version = readings.current_version('html_metadata')
    monkeypatch.setattr(reader, 'FORMAT_TIMEOUT_SECONDS', 99.0)
    assert readings.current_version('html_metadata') != version
    monkeypatch.undo()
    source = Path('packages/congress_api/src/congress_api')
    (tmp_path / 'uv.lock').write_bytes((ROOT / 'uv.lock').read_bytes())
    for name in ('models/html_metadata.py', 'parsers/html_metadata.py', 'parsers/main_content.py'):
        target = tmp_path / source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / source / name).read_bytes())
    assert readings.current_version('html_metadata', root=tmp_path) == version
    target.write_bytes(target.read_bytes() + b'\n')
    moved = readings.current_version('html_metadata', root=tmp_path)
    assert moved != version
    (tmp_path / 'uv.lock').write_bytes(b'other')
    assert readings.current_version('html_metadata', root=tmp_path) != moved


def test_the_worker_policy_is_in_the_version_and_the_bundle_is_not(monkeypatch):
    version, bundle = readings.current_version('html_metadata'), readings.current_version('html')
    monkeypatch.setattr(readings, 'WORKER_TIMEOUT_SECONDS', 16)
    assert readings.current_version('html_metadata') != version
    assert readings.current_version('html') == bundle
    assert readings.worker_limits('html_metadata')['timeout_seconds'] == len(FORMATS) * reader.FORMAT_TIMEOUT_SECONDS + 16


def test_a_main_content_change_moves_only_the_html_metadata_pin(monkeypatch, tmp_path):
    from congress_api.lake import compatible_versions
    before = compatible_versions.current_pins()
    real = readings.current_version
    monkeypatch.setattr(readings, 'current_version', lambda p, **k: 'moved' if p == 'html_metadata' else real(p, **k))
    after = compatible_versions.current_pins()
    assert {p for p in before if before[p] != after[p]} == {'html_metadata'}


def test_each_reading_records_the_extruct_version():
    from importlib.metadata import version
    assert read_html_metadata(FIXTURE).extruct_version == version('extruct')
    assert read_html_metadata(b'%PDF-1.7').extruct_version is None
