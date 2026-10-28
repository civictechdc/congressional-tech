"""D1 reuses explicit immutable qualification without reopening source bytes."""
from hashlib import sha256
import json
import os
import subprocess
import sys

import pytest


def qualified_source(root, *, embedded_path=True):
    source = root/'receipt.gz'
    data = b'creation-buffer'
    source.write_bytes(data)
    facts = dict(sha256=sha256(data).hexdigest(), size=len(data), rows=2,
                 note='creation bytes qualified')
    if embedded_path:
        facts['path'] = str(source)
    authority = root/'qualification.json'
    authority.write_text(json.dumps(facts))
    return source, authority, facts


def admit(source, authority):
    from congress_api.lake.receipt_metadata import source_pins
    return source_pins(files=[dict(path=str(source))],
                       qualifications={str(source): str(authority)})


@pytest.mark.parametrize('embedded_path', [True, False])
def test_reuses_exact_authority_without_opening_source(tmp_path, embedded_path):
    source, authority, facts = qualified_source(tmp_path, embedded_path=embedded_path)
    script = '''
import json, os, sys
from congress_api.lake.receipt_metadata import source_pins, recheck_source_pins
source, authority = sys.argv[1:]
def deny_source(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes)) and os.fsdecode(args[0]) == source:
        raise AssertionError('Pinning opened source payload')
sys.addaudithook(deny_source)
pins = source_pins(files=[dict(path=source)], qualifications={source:authority})
recheck_source_pins(pins)
print(json.dumps(pins))
'''
    result = subprocess.run([sys.executable, '-I', '-c', script, str(source), str(authority)],
                            capture_output=True, text=True, check=True)
    [pin] = json.loads(result.stdout)
    assert (pin['path'], pin['sha256'], pin['size']) == (
        str(source), facts['sha256'], facts['size'])
    qualification = pin['qualification']
    assert qualification['kind'] == 'reused_qualification'
    assert qualification['path'] == str(authority)
    assert qualification['sha256'] == sha256(authority.read_bytes()).hexdigest()
    assert qualification['rows'] == 2 and qualification['note'] == facts['note']
    assert len(pin['identity']) == len(qualification['identity']) == 5


@pytest.mark.parametrize('value', [None, [], 'bad', {}, {'sha256':'a'*64},
    {'sha256':'g'*64,'size':15}, {'sha256':'a'*63,'size':15},
    {'sha256':'a'*64,'size':True}, {'sha256':'a'*64,'size':-1},
    {'sha256':123,'size':15}, {'sha256':'a'*64,'size':15.0},
    {'sha256':'a'*64,'size':15,'rows':True},
    {'sha256':'a'*64,'size':15,'rows':1.5}])
def test_malformed_qualification_refuses(tmp_path, value):
    source, authority, _ = qualified_source(tmp_path)
    authority.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        admit(source, authority)


@pytest.mark.parametrize('problem', ['json', 'size', 'path', 'relative-path',
    'source-symlink', 'authority-symlink', 'authority-directory', 'authority-missing',
    'source-directory', 'source-missing', 'oversize'])
def test_invalid_binding_refuses(tmp_path, problem):
    source, authority, facts = qualified_source(tmp_path)
    if problem == 'json':
        authority.write_text('{')
    elif problem in ('size', 'path', 'relative-path'):
        facts.update({'size':1} if problem == 'size' else
                     {'path': 'receipt.gz' if problem == 'relative-path' else str(tmp_path/'other')})
        authority.write_text(json.dumps(facts))
    elif problem in ('source-symlink', 'authority-symlink'):
        target = source if problem == 'source-symlink' else authority
        moved = target.with_suffix('.original')
        target.rename(moved)
        target.symlink_to(moved)
    elif problem == 'oversize':
        authority.write_bytes(b' '*(1024*1024+1))
    else:
        path = source if problem.startswith('source-') else authority
        path.unlink()
        if problem.endswith('-directory'):
            path.mkdir()
    with pytest.raises((ValueError, OSError)):
        admit(source, authority)


def test_unqualified_missing_extra_and_duplicate_bindings_refuse(tmp_path):
    from congress_api.lake.receipt_metadata import source_pins
    source, authority, _ = qualified_source(tmp_path)
    files = [dict(path=str(source))]
    for mapping in (None, {}, {str(source): {'sha256':'a'*64,'size':15}},
                    {str(source):str(authority), str(tmp_path/'extra'):str(authority)},
                    {str(source):str(authority), source:str(authority)}):
        with pytest.raises((ValueError, TypeError)):
            source_pins(files=files, qualifications=mapping)


@pytest.mark.parametrize('target', ['source', 'authority'])
@pytest.mark.parametrize('mutation', ['append', 'rewrite', 'replace', 'same-bytes'])
def test_custody_drift_refuses_even_when_mtime_restored(tmp_path, target, mutation):
    from congress_api.lake.receipt_metadata import recheck_source_pins
    source, authority, _ = qualified_source(tmp_path)
    pins = admit(source, authority)
    path = source if target == 'source' else authority
    stat = path.stat()
    data = path.read_bytes()
    changed = data if mutation == 'same-bytes' else bytes([data[0] ^ 1])+data[1:]
    if mutation == 'append':
        path.write_bytes(data+b'x')
    elif mutation == 'replace':
        replacement = tmp_path/'replacement'
        replacement.write_bytes(changed)
        replacement.replace(path)
    else:
        path.write_bytes(changed)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError, match='changed'):
        recheck_source_pins(pins)


@pytest.mark.parametrize('target', ['source', 'authority'])
@pytest.mark.parametrize('mutation_call', [1, 2])
def test_native_drift_refuses_before_public_acceptance(tmp_path, target, mutation_call):
    from congress_api.lake.captures import stage_captures
    source, authority, _ = qualified_source(tmp_path)
    class MutatingEngine:
        source_revision = 'fixture'
        binary_sha256 = 'a'*64
        calls = 0
        def run_job(self, path):
            self.calls += 1
            if self.calls == mutation_call:
                changed = source if target == 'source' else authority
                changed.write_bytes(changed.read_bytes()+b'x')
            return dict(outputs=[],queries=[dict(name='violations',data=[]),
                dict(name='source_counts',data=[dict(rows=2,receipts=1)]),
                dict(name='counts',data=[dict(rows=2,receipts=1)]),
                dict(name='receipts',data=[dict(receipt_key='receipts/f/undated/one.gz')])])
    engine = MutatingEngine()
    work = tmp_path/'stage'
    with pytest.raises(ValueError, match='changed'):
        stage_captures([dict(key='receipts/f/undated/one.gz',path=str(source))],
            engine=engine,work=work,source_qualifications={str(source):str(authority)})
    assert engine.calls == mutation_call
    assert (work/'export').exists() == (mutation_call == 2)
    assert not (work/'ingested-receipts.json').exists()


def test_authority_change_during_its_read_refuses(tmp_path):
    source, authority, _ = qualified_source(tmp_path)
    active = [True]
    def mutate_authority(event, args):
        if active[0] and event == 'open' and args[0] == str(authority):
            active[0] = False
            authority.write_text('{}')
    sys.addaudithook(mutate_authority)
    try:
        with pytest.raises(ValueError, match='changed'):
            admit(source, authority)
    finally:
        active[0] = False


def test_missing_qualification_refuses_before_native_read(tmp_path):
    from congress_api.lake.captures import stage_captures
    source, _, _ = qualified_source(tmp_path)
    class UnopenedEngine:
        source_revision = 'fixture'
        binary_sha256 = 'a'*64
        def run_job(self, path):
            raise AssertionError('Unqualified source reached native execution')
    with pytest.raises(ValueError, match='qualification'):
        stage_captures([dict(key='receipts/f/undated/one.gz',path=str(source))],
            engine=UnopenedEngine(),work=tmp_path/'stage')
    assert not (tmp_path/'stage/job.json').exists()
