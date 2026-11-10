"""The scheduled nightly runs with enough open files and at normal priority, however it is started."""
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location('nightly_publish_launch', ROOT / 'scripts/nightly_publish.py')
nightly = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nightly)

PROBE = '''
import importlib.util, json, resource, sys
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (256, hard))
spec = importlib.util.spec_from_file_location('probe', sys.argv[1])
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
before, after = module.raise_file_limit()
again = module.raise_file_limit()
print(json.dumps(dict(before=before, after=after, again=list(again), hard=hard, infinity=resource.RLIM_INFINITY)))
'''


def test_a_launchd_sized_file_limit_is_raised_and_never_lowered():
    """launchd gives an agent 256 open files; the engine's late input open failed under it."""
    result = json.loads(subprocess.run([sys.executable, '-c', PROBE, str(ROOT / 'scripts/nightly_publish.py')],
                                       check=True, capture_output=True, text=True).stdout)
    ceiling = nightly.FILE_LIMIT if result['hard'] == result['infinity'] else min(nightly.FILE_LIMIT, result['hard'])
    assert result['before'] == 256
    assert result['after'] in (ceiling, min(ceiling, 10240)) and result['after'] > 256
    # A second call finds nothing to do: the limit only ever goes up.
    assert result['again'] == [result['after'], result['after']]


def test_the_launch_agent_runs_at_normal_priority_with_the_file_limit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nightly, 'real_tool', lambda name: f'/opt/tools/{name}/bin/{name}')
    monkeypatch.setattr(nightly.Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(nightly.subprocess, 'run', lambda command, **options: calls.append(command))
    (tmp_path / 'Library/LaunchAgents').mkdir(parents=True)
    assert nightly.install(tmp_path / 'main', 5, 30) == 0
    agent = plistlib.loads((tmp_path / 'Library/LaunchAgents' / f'{nightly.LABEL}.plist').read_bytes())
    # Background would put the whole build on the efficiency cores at priority 4.
    assert agent['ProcessType'] == 'Standard'
    assert agent['SoftResourceLimits'] == {'NumberOfFiles': nightly.FILE_LIMIT}
    assert [command[1] for command in calls] == ['bootout', 'bootstrap']
