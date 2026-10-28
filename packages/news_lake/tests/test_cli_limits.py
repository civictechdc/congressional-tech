"""Every retained native command forwards an explicitly selected resource file."""
import json
import os
from pathlib import Path

import pytest


@pytest.mark.parametrize('command,extra',[
    ('publish',['--input','records.jsonl','--release-id','release']),
    ('views',['--release-id','release']),
    ('export',['--release-id','release','--destination','export']),
    ('compact-lifecycle',[]),
])
def test_commands_accept_explicit_native_limits(tmp_path,command,extra):
    from news_lake.cli import build_parser
    selected=str(tmp_path/'limits.json')
    args=build_parser().parse_args([command,'--workspace',str(tmp_path/'workspace'),
        '--limits',selected,*extra])
    assert args.limits==selected


def test_publish_refuses_unreadable_limits_instead_of_using_defaults(tmp_path):
    from docspec_client import DocSpecFailure
    from news_lake.cli import main
    from test_docspec_backend import CORPUS,AT
    configuration=Path(os.environ['DOCSPEC_JOB_CONFIG'])
    runtime=json.loads(configuration.read_text())
    binary=str((configuration.parent/runtime['binary']).resolve())
    records=tmp_path/'records.jsonl'
    records.write_text('\n'.join(json.dumps(record) for record in CORPUS)+'\n')
    with pytest.raises(DocSpecFailure):
        main(['publish','--workspace',str(tmp_path/'workspace'),'--input',str(records),
            '--release-id','00000000-0000-4000-8000-000000000001','--recorded-at',AT,
            '--binary',binary,'--limits',str(tmp_path/'missing-limits.json')])
