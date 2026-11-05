"""Audit failure and optional-context handling must not depend on interpreter flags."""
import json
import subprocess
import sys
from time import monotonic

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


# Allow for interpreter startup and imports when other jobs share the machine.
CLI_HANG_TIMEOUT_SECONDS = 60


def run_cli(*args):
    command = [sys.executable, *args]
    started = monotonic()
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=CLI_HANG_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        pytest.fail(
            f"House naming CLI timed out after {monotonic() - started:.1f}s: {command!r}\n"
            f"stdout: {error.stdout!r}\nstderr: {error.stderr!r}",
            pytrace=False,
        )


@pytest.fixture
def inventory(tmp_path):
    path = tmp_path / 'names.parquet'
    pq.write_table(pa.Table.from_pylist([
        {'filename': 'alpha.pdf', 'variants': []},
        {'filename': 'alpha-other.pdf', 'variants': []},
    ]), path)
    return path


@pytest.mark.parametrize('optimized', [False, True])
@pytest.mark.parametrize('corruption', ['none', 'piece', 'field', 'token'])
def test_corpus_rejects_corrupted_evidence_even_with_optimization(tmp_path, inventory, optimized, corruption):
    code = '''import sys
from house_naming import filename_corpus as c
mode=sys.argv.pop(1)
real=c.parse_filename
def corrupted(name,**kwargs):
 r=real(name,**kwargs)
 if mode=='piece':
  pieces=list(r.pieces);pieces[0]=pieces[0].model_copy(update={'raw':'WRONG'})
  return r.model_copy(update={'pieces':tuple(pieces)})
 if mode=='field':
  matches=list(r.matches);fields=list(matches[0].fields)
  fields[0]=fields[0].model_copy(update={'raw':'WRONG'})
  matches[0]=matches[0].model_copy(update={'fields':tuple(fields)})
  return r.model_copy(update={'matches':tuple(matches)})
 return r
c.parse_filename=corrupted
if mode=='token': c.shared_token_pattern=lambda *args: r'(?P<token>NEVER_MATCH)'
raise SystemExit(c.main())
'''
    output = tmp_path / 'output'
    flags = ['-O'] if optimized else []
    run = run_cli(*flags, '-c', code, corruption, str(inventory), str(output))
    if corruption == 'none':
        assert run.returncode == 0, run.stderr
        report = json.loads((output / 'coverage.json').read_text())
        assert report['mechanical_gate'] and report['lossless_filenames_checked'] == 2
        assert report['shared_token_occurrences_checked'] > 0
    else:
        assert run.returncode == 1, run.stdout + run.stderr
        assert json.loads(run.stderr)['error']['code'] == 'audit-failed'
        assert not (output / 'coverage.json').exists()


@pytest.mark.parametrize('payload,code,status', [
    (b'{"119":["Clyburn"],"119":["Smith"]}', 'duplicate-json-key', 1),
    (b' ' * 65_537, 'input-too-large', 2),
    (b'{', 'invalid-json', 1),
])
def test_both_commands_reject_the_same_bad_surname_json(tmp_path, inventory, payload, code, status):
    reference = tmp_path / 'surnames.json'
    reference.write_bytes(payload)
    for args in [
        ['house_naming', 'extract', 'BILLS-119HR42RepClyburnTitleih.pdf'],
        ['house_naming.filename_corpus', str(inventory), str(tmp_path / 'output')],
    ]:
        run = run_cli('-m', *args, '--member-surnames', str(reference))
        assert run.returncode == status, run.stdout + run.stderr
        assert json.loads(run.stderr)['error']['code'] == code
    assert not (tmp_path / 'output/coverage.json').exists()


def test_long_revision_does_not_abort_corpus(tmp_path):
    from house_naming.filename_corpus import build_corpus
    report = build_corpus(['notes-U' + '9' * 5000 + '.pdf'], tmp_path)
    assert report['lossless_filenames_checked'] == 1


def test_refinement_limit_reaches_all_consumers(tmp_path):
    from house_naming import NamingError
    from house_naming.filenames import parse_filename
    from house_naming.filename_corpus import build_corpus
    name = '1-1-' * 4000 + '.pdf'
    for call in (lambda: parse_filename(name), lambda: build_corpus([name], tmp_path)):
        with pytest.raises(NamingError) as failure:
            call()
        assert failure.value.code == 'extraction-limit'
    run = run_cli('-m', 'house_naming', 'extract', name)
    assert run.returncode == 2
    assert json.loads(run.stderr)['error']['code'] == 'extraction-limit'
