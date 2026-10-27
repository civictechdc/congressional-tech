"""CLI failures replace stale success reports before any mutation client exists."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'scripts/publication')]
import publication_cli as cli
import viewer_publication.attempt as attempts


def descriptor():
    return dict(version=1,revision='a'*40,run_id='123',run_attempt='2',artifact_id='456',artifact_digest='b'*64,
        artifact_name='viewer-prepared-123-2-'+'c'*64,attempt='123-2-'+'c'*64,repository='fixture/repo')

@pytest.mark.parametrize('arguments,diagnostic', [
    (['prepare','--directory','new'], 'run-id'),
    (['verify-prepared','--directory','new','--resume'], 'require publish'),
    (['publish','--directory','new','--attempt','original'], 'required together'),
    (['publish','--directory','new','--resume'], 'required together'),
    (['publish','--directory','new'], 'requires original artifact'),
    (['describe-attempt'], 'requires --repository'),
    (['verify-prepared','--directory','new','--renderer-upgrade'], 'require prepare'),
    (['prepare','--directory','new','--resume-preparation'], 'run-id'),
])
def test_invalid_command_combinations_fail_before_client_and_replace_report(tmp_path, monkeypatch, arguments, diagnostic):
    for name in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REPOSITORY'):
        monkeypatch.delenv(name, raising=False)
    report=tmp_path/'outcome.json'; report.write_text('{"status":"prepared"}')
    monkeypatch.setattr(cli,'make_client',lambda:pytest.fail('constructed mutation client'))
    with pytest.raises(ValueError,match=diagnostic):
        cli.main(SimpleNamespace(PUBLIC_URL='unused'), [*arguments,'--report',str(report)])
    assert json.loads(report.read_text())['status']=='failed'


def test_original_exception_survives_diagnostic_save_failure(tmp_path,monkeypatch):
    original=OSError('original failure')
    monkeypatch.setattr(attempts,'verify_prepared',lambda *a:(_ for _ in ()).throw(original))
    monkeypatch.setattr(cli,'save_report',lambda *a:(_ for _ in ()).throw(OSError('receipt failed')))
    with pytest.raises(OSError) as caught:
        cli.main(SimpleNamespace(PUBLIC_URL='unused'),['verify-prepared','--directory',str(tmp_path),'--report',str(tmp_path/'report')])
    assert caught.value is original
    assert any('receipt save failed' in note for note in original.__notes__)


def test_read_only_lookup_emits_one_original_resume_descriptor(monkeypatch):
    d=descriptor()
    def github(route):
        if '/artifacts?' in route:
            return {'artifacts':[{'id':456,'name':d['artifact_name'],'digest':'sha256:'+d['artifact_digest'],'expired':False}]}
        return {'id':123,'head_sha':d['revision']}
    monkeypatch.setattr(attempts,'github_json',github)
    assert attempts.lookup_attempt('fixture/repo','123')==d
    assert attempts.validate_resume_descriptor(d)==d
    for name in ('revision','run_id','artifact_id','artifact_digest','attempt','repository'):
        with pytest.raises(ValueError,match='descriptor'):
            attempts.validate_resume_descriptor(dict(d,**{name:'invalid/../field'}))


def test_resume_descriptor_requires_explicit_resume_and_original_checkout(tmp_path,monkeypatch):
    d=descriptor(); path=tmp_path/'resume.json';path.write_text(json.dumps(d))
    for name in ('GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REPOSITORY'):
        monkeypatch.delenv(name, raising=False)
    args=cli.arguments(['publish','--directory',str(tmp_path),'--resume-descriptor',str(path)])
    with pytest.raises(ValueError,match='explicit --resume'):
        cli.validate(args,attempts)
    args.resume=True
    monkeypatch.setattr(cli.subprocess,'check_output',lambda *a,**kw:'b'*40)
    with pytest.raises(ValueError,match='original revision'):
        cli.validate(args,attempts)
    monkeypatch.setattr(cli.subprocess,'check_output',lambda *a,**kw:d['revision'])
    cli.validate(args,attempts)
    assert args.attempt==d['attempt'] and args.run_id=='123' and args.artifact_id=='456'


def test_descriptor_overrides_current_run_environment_but_refuses_explicit_conflicts(tmp_path, monkeypatch):
    d=descriptor(); path=tmp_path/'descriptor.json'; path.write_text(json.dumps(d))
    monkeypatch.setenv('GITHUB_RUN_ID','999')
    monkeypatch.setattr(cli.subprocess,'check_output',lambda *a,**k:d['revision'])
    args=cli.arguments(['publish','--directory',str(tmp_path),'--resume','--resume-descriptor',str(path)])
    cli.validate(args,attempts)
    assert args.run_id=='123'
    args=cli.arguments(['publish','--directory',str(tmp_path),'--resume','--resume-descriptor',str(path),'--run-id','999'])
    with pytest.raises(ValueError,match='conflicts with --run-id'):
        cli.validate(args,attempts)


@pytest.mark.parametrize('field,wrong,message', [('id',457,'ID differs'),('expired',True,'expired'),
    ('name','wrong','name differs'),('digest','sha256:'+'0'*64,'digest differs'),
    ('workflow_run',{'id':999},'original run ID differs')])
def test_each_artifact_custody_mismatch_is_exact_and_before_mutation(monkeypatch,field,wrong,message):
    metadata=dict(id=456,expired=False,name='expected',digest='sha256:'+'a'*64,workflow_run={'id':123})
    metadata[field]=wrong
    monkeypatch.setattr(attempts,'github_json',lambda route:metadata)
    with pytest.raises(ValueError,match=message):
        attempts.verify_github_artifact({'id':'456','digest':'a'*64,'repository':'fixture/repo','run_id':'123'}, {'artifact_name':'expected'})


@pytest.mark.parametrize('arguments', [['unknown-command'],['prepare','--unknown'],['prepare','--run-id']])
def test_argparse_failures_replace_stale_success_report_and_keep_system_exit(tmp_path,monkeypatch,arguments):
    report=tmp_path/'outcome.json';report.write_text('{"status":"prepared"}')
    monkeypatch.setattr(cli,'make_client',lambda:pytest.fail('constructed mutation client'))
    with pytest.raises(SystemExit) as caught:
        cli.main(SimpleNamespace(PUBLIC_URL='unused'),[*arguments,'--report',str(report),'--directory',str(tmp_path)])
    assert caught.value.code==2
    assert json.loads(report.read_text())['status']=='failed'
    assert json.loads((tmp_path/'command-outcome.json').read_text())['error_type']=='SystemExit'


@pytest.mark.parametrize('expiry',[None,'false',0])
def test_missing_or_malformed_artifact_expiry_never_means_unexpired(monkeypatch,expiry):
    metadata=dict(id=456,name='expected',digest='sha256:'+'a'*64,workflow_run={'id':123})
    if expiry is not None:metadata['expired']=expiry
    monkeypatch.setattr(attempts,'github_json',lambda route:metadata)
    with pytest.raises(ValueError,match='expired'):
        attempts.verify_github_artifact({'id':'456','digest':'a'*64,'repository':'fixture/repo','run_id':'123'}, {'artifact_name':'expected'})
    d=descriptor();metadata.update(name=d['artifact_name'],digest='sha256:'+d['artifact_digest'])
    def github(route):
        return {'artifacts':[metadata]} if '/artifacts?' in route else {'id':123,'head_sha':d['revision']}
    monkeypatch.setattr(attempts,'github_json',github)
    with pytest.raises(ValueError,match='Expected one original'):
        attempts.lookup_attempt('fixture/repo','123')


def test_explicit_upgrade_flags_reach_existing_preparation(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.delenv('DOCSPEC_CONFIG',raising=False)
    monkeypatch.setattr(cli,'make_client',lambda:'fixture-client')
    def prepare(*args,**options):
        calls.append((args,options));return {'status':'prepared'}
    monkeypatch.setattr(attempts,'prepare',prepare)
    assert cli.main(SimpleNamespace(PUBLIC_URL='fixture-public'),['prepare','--directory',str(tmp_path),
        '--run-id','upgrade','--run-attempt','1','--renderer-upgrade','--resume-preparation'])==0
    options = calls[0][1]
    assert callable(options.pop('stage_event'))
    assert options==dict(run_id='upgrade',run_attempt='1',public_url='fixture-public',
        renderer_upgrade=True,resume_preparation=True)


def test_export_pins_cli_requires_directory():
    with pytest.raises(ValueError, match='export-pins requires --directory'):
        cli.arguments(['export-pins'])
        cli.validate(cli.arguments(['export-pins']), attempts)


def test_export_pins_cli_workflow(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    target = tmp_path / 'pins_out'
    target.mkdir()
    sources = pa.Table.from_pylist([
        {'source_id': 's1', 'document_id': 'd1', 'filename': 'a.pdf', 'source_url': 'http://a', 'body_key': None,
         'record_role': ['doc'], 'document_kind': ['kind'], 'document_family': ['fam'], 'format': ['PDF'],
         'congress': ['118'], 'http_status': ['200'], 'response_usable': ['true'],
         'response_body_complete': ['true'], 'state_checked_at': ['2026-10-23T12:00:00Z'],
         'raw_leaf': ['l'], 'normalized_leaf': ['nl'], 'header_leaf': ['hl']}
    ])
    components = pa.Table.from_pylist([
        {'component_id': 'c1', 'document_id': 'd1', 'source_id': 's1', 'filename': 'a.pdf',
         'file_bytes': 100, 'sha256': 'a' * 64}
    ])
    pq.write_table(sources, target / 'sources.parquet')
    pq.write_table(components, target / 'components.parquet')

    exit_code = cli.main(SimpleNamespace(PUBLIC_URL='http://test.public/'), ['export-pins', '--directory', str(target)])
    assert exit_code == 0
    assert (target / 'manifest.json').is_file()
    manifest = json.loads((target / 'manifest.json').read_text())
    assert manifest['version'] == 6
    assert 'sources' in manifest['exports']
    assert 'components' in manifest['exports']


def test_export_pins_cli_publish_to_r2(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq

    target = tmp_path / 'pins_out_r2'
    target.mkdir()
    sources = pa.Table.from_pylist([
        {'source_id': 's1', 'document_id': 'd1', 'filename': 'b.pdf', 'source_url': 'http://b', 'body_key': None,
         'record_role': ['doc'], 'document_kind': ['kind'], 'document_family': ['fam'], 'format': ['PDF'],
         'congress': ['118'], 'http_status': ['200'], 'response_usable': ['true'],
         'response_body_complete': ['true'], 'state_checked_at': ['2026-10-23T12:00:00Z'],
         'raw_leaf': ['l'], 'normalized_leaf': ['nl'], 'header_leaf': ['hl']}
    ])
    components = pa.Table.from_pylist([
        {'component_id': 'c1', 'document_id': 'd1', 'source_id': 's1', 'filename': 'b.pdf',
         'file_bytes': 200, 'sha256': 'b' * 64}
    ])
    pq.write_table(sources, target / 'sources.parquet')
    pq.write_table(components, target / 'components.parquet')

    puts = []
    class FakeS3:
        def put_object(self, **kwargs):
            body = kwargs['Body']
            payload = body if isinstance(body, bytes) else body.read()
            assert len(payload) == kwargs['ContentLength']
            puts.append(dict(kwargs, Body=payload))
            return {'ETag': '"etag-123"'}

    monkeypatch.setattr(cli, 'make_client', lambda: FakeS3())
    exit_code = cli.main(
        SimpleNamespace(PUBLIC_URL='http://test.public/'),
        ['export-pins', '--directory', str(target), '--publish-to-r2', '--version', 'v-test-export'],
    )
    assert exit_code == 0
    # Must have uploaded immutable assets (sources, components) and manifest pointer
    keys = [p['Key'] for p in puts]
    assert any('viewer-publications/releases/v-test-export/viewer-v2/sources.parquet' in k for k in keys)
    assert any('viewer-publications/manifest.json' in k for k in keys)
    for name in ('sources.parquet', 'components.parquet'):
        uploaded = next(put['Body'] for put in puts if put['Key'].endswith('/' + name))
        assert uploaded == (target / name).read_bytes()



def test_initial_preparation_resume_needs_no_renderer_upgrade_and_flushes_progress(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('DOCSPEC_CONFIG', raising=False)
    monkeypatch.setattr(cli, 'make_client', lambda: 'fixture-client')
    def prepare(*args, **options):
        assert options['resume_preparation'] is True
        assert 'renderer_upgrade' not in options
        assert options['run_id'] == '999' and options['run_attempt'] == '2'
        options['stage_event'](dict(event='stage_started', stage='component_preparation'))
        return dict(status='prepared')
    monkeypatch.setattr(attempts, 'prepare', prepare)
    assert cli.main(SimpleNamespace(PUBLIC_URL='fixture-public'), ['prepare', '--directory', str(tmp_path),
        '--run-id', '999', '--run-attempt', '2', '--resume-preparation']) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[0])['event'] == 'stage_started'


def test_publish_refuses_preparation_checkpoint_descriptor_before_client(tmp_path, monkeypatch):
    descriptor_path = tmp_path / 'checkpoint.json'
    descriptor_path.write_text('{}')
    monkeypatch.setattr(cli, 'parse_resume_descriptor', lambda raw: dict(version=2, kind='preparation_checkpoint'))
    monkeypatch.setattr(cli, 'make_client', lambda: pytest.fail('constructed mutation client'))
    with pytest.raises(ValueError, match='accepted-publication resume descriptor'):
        cli.main(SimpleNamespace(PUBLIC_URL='unused'), ['publish', '--directory', str(tmp_path), '--resume',
            '--resume-descriptor', str(descriptor_path)])
