"""B5: approved local bytes and metadata precede CI runtime admission."""
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest
import yaml

ROOT=Path(__file__).parents[2]
FIXTURE=json.loads((ROOT/'model/fixtures/local-job-runtime.json').read_text())

@pytest.fixture
def installer():
    spec=importlib.util.spec_from_file_location('local_job_runtime',ROOT/'.github/scripts/setup-local-job-runtime.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archive(tmp_path, *, change=None, extra=None):
    data={name:json.dumps(FIXTURE[key]).encode() for name,key in [('runtime.json','runtime'),('limits.json','limits'),('build.json','build')]}
    data['docspec']=bytes.fromhex(FIXTURE['binary_hex'])
    if change:
        change(data)
    path=tmp_path/'runtime.tar.gz'
    with tarfile.open(path,'w:gz') as out:
        for name,payload in data.items():
            member=tarfile.TarInfo(name);member.size=len(payload);member.mode=0o755 if name=='docspec' else 0o644
            out.addfile(member,io.BytesIO(payload))
        if extra:
            member=tarfile.TarInfo(extra[0]);member.type=extra[1];member.linkname='outside'
            out.addfile(member,io.BytesIO(b''))
    return path,sha256(path.read_bytes()).hexdigest()


def test_approved_local_archive_preserves_owner_limits_and_literal_pins(tmp_path,installer):
    source,digest=archive(tmp_path)
    config=installer.install_archive(source,digest,tmp_path/'installed')
    assert json.loads(config.read_text())==FIXTURE['runtime']
    assert json.loads((config.parent/'limits.json').read_text())==FIXTURE['limits']
    assert set(p.name for p in config.parent.iterdir())==set(FIXTURE['expected']['archive_files'])
    assert (config.parent/'docspec').stat().st_mode&0o111
    assert not (config.parent/'workspace').exists()


def test_unapproved_archive_digest_creates_no_executable(tmp_path,installer):
    source,_=archive(tmp_path)
    with pytest.raises(ValueError,match='digest|SHA'):
        installer.install_archive(source,'0'*64,tmp_path/'installed')
    assert not (tmp_path/'installed').exists()


@pytest.mark.parametrize('name,kind',[
    ('../escape',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE),('docspec',tarfile.SYMTYPE),
    ('docspec',tarfile.LNKTYPE),('unexpected',tarfile.REGTYPE),('runtime.json',tarfile.REGTYPE)])
def test_unsafe_duplicate_or_extra_archive_members_refuse_before_install(tmp_path,name,kind,installer):
    source,digest=archive(tmp_path,extra=(name,kind))
    with pytest.raises(ValueError):
        installer.install_archive(source,digest,tmp_path/'installed')
    assert not (tmp_path/'installed').exists()
    assert not (tmp_path.parent/'escape').exists()


@pytest.mark.parametrize('case',['remote','credentials','path','platform','source','features','binary','limits'])
def test_config_or_build_contradictions_refuse_before_install(tmp_path,case,installer):
    def change(data):
        runtime=json.loads(data['runtime.json']);build=json.loads(data['build.json'])
        if case in {'remote','credentials'}:runtime[case]='forbidden.json'
        elif case=='path':runtime['binary']='../docspec'
        elif case=='platform':runtime['platform']=build['platform']='linux-x86_64'
        elif case=='source':runtime['source_revision']='b'*40
        elif case=='features':runtime['build_features']=build['build_features']=['remote','test-util']
        elif case=='binary':runtime['binary_sha256']=build['binary_sha256']='c'*64
        elif case=='limits':data['limits.json']=json.dumps(dict(FIXTURE['limits'],memory_bytes=True)).encode()
        data['runtime.json']=json.dumps(runtime).encode();data['build.json']=json.dumps(build).encode()
    source,digest=archive(tmp_path,change=change)
    with pytest.raises(ValueError):
        installer.install_archive(source,digest,tmp_path/'installed')
    assert not (tmp_path/'installed').exists()


def test_local_archive_bootstrap_precedes_each_offline_ci_consumer():
    for workflow,job in [('validate-explorer.yml','validate'),('update-data.yml','meetings'),('capture-archive.yml','capture')]:
        value=yaml.load((ROOT/'.github/workflows'/workflow).read_text(),Loader=yaml.BaseLoader)
        steps=value['jobs'][job]['steps']
        setup=next(i for i,s in enumerate(steps) if s.get('uses')=='./.github/actions/setup-local-job-runtime')
        consumer=next(i for i,s in enumerate(steps) if 'production-offline' in s.get('run','') or 'capture_schedule' in s.get('run',''))
        assert setup<consumer
        assert steps[setup]['with']=={'artifact':'${{ vars.DOCSPEC_RUNTIME_ARTIFACT }}',
            'credentials':'${{ secrets.DOCSPEC_ENGINE_CREDENTIALS }}',
            'account-id':'${{ vars.CLOUDFLARE_ACCOUNT_ID }}'}
    action=(ROOT/'.github/actions/setup-local-job-runtime/action.yml').read_text()
    assert 'secrets.' not in action and 'setup-native-runtime.py' in action
    assert '--local' in action
    helper=(ROOT/'.github/scripts/setup-native-runtime.py').read_text()
    assert 'DOCSPEC_JOB_CONFIG=' in helper
    assert 'DOCSPEC_BINARY=' in helper


def test_existing_ci_commands_enroll_all_site_mechanism_checks():
    scripts=json.loads((ROOT/'apps/site/package.json').read_text())['scripts']
    assert 'scripts/archive-presentation.test.mjs' in scripts['test:explorer']
    assert 'scripts/archive-tools.test.mjs' in scripts['test:explorer']
    browser=(ROOT/'.github/scripts/verify-archive-contract.py').read_text()
    assert 'test:archive-saved-browser' in browser and 'test:archive-heap-browser' in browser


@pytest.mark.parametrize('failed',[None,'test:archive-saved-browser'])
def test_actual_browser_wrapper_runs_checked_children_and_stops_at_failure(tmp_path,failed):
    tools=tmp_path/'bin';tools.mkdir()
    npm=tools/'npm'
    npm.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS_FILE"\n'
        'if [ -n "$FAIL_SCRIPT" ]; then case "$*" in *"$FAIL_SCRIPT"*) exit 9;; esac; fi\n')
    npm.chmod(0o755)
    calls=tmp_path/'calls.txt'
    result=subprocess.run([sys.executable,'-I',str(ROOT/'.github/scripts/verify-archive-contract.py'),
        '--work',str(tmp_path/'work'),'--browser-executable','/approved/chrome'],
        env={**os.environ,'PATH':str(tools)+os.pathsep+os.defpath,'CALLS_FILE':str(calls),'FAIL_SCRIPT':failed or ''},
        text=True,capture_output=True,timeout=15)
    commands=calls.read_text().splitlines()
    assert 'contract:archive' in commands[0]
    assert 'test:archive-saved-browser' in commands[1]
    assert all('--browser-executable /approved/chrome' in call for call in commands)
    if failed:
        assert result.returncode!=0 and len(commands)==2
    else:
        assert result.returncode==0 and len(commands)==3
        assert 'test:archive-heap-browser' in commands[2]
