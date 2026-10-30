"""Production checks must not accidentally claim test-util pause qualification."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import native_test_helpers as helpers


def test_pause_hooks_need_explicit_variant_even_when_production_binary_exists(monkeypatch):
    monkeypatch.delenv('DOCSPEC_TEST_UTIL_BINARY', raising=False)
    monkeypatch.setenv('DOCSPEC_BINARY', '/approved/production/docspec')
    with pytest.raises(pytest.skip.Exception, match='DOCSPEC_TEST_UTIL_BINARY'):
        helpers.native_test_util_binary()


def test_explicit_production_binary_cannot_impersonate_test_util(monkeypatch):
    monkeypatch.setenv('DOCSPEC_TEST_UTIL_BINARY', '/approved/production/docspec')
    check = Mock(return_value=SimpleNamespace(returncode=2))
    monkeypatch.setattr(helpers.subprocess, 'run', check)
    with pytest.raises(pytest.fail.Exception, match='compiled test-util'):
        helpers.native_test_util_binary()
    assert check.call_args.args[0] == ['/approved/production/docspec', 'pause-after', '--help']
    assert check.call_args.kwargs['timeout'] == 10


def test_explicit_test_util_checks_capability_without_running_fixture_work(monkeypatch):
    monkeypatch.setenv('DOCSPEC_TEST_UTIL_BINARY', '/same-source/test-util/docspec')
    check = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(helpers.subprocess, 'run', check)
    assert helpers.native_test_util_binary() == '/same-source/test-util/docspec'
    assert check.call_args.args[0] == ['/same-source/test-util/docspec', 'pause-after', '--help']


@pytest.mark.parametrize('value', ['0', '121', '-1', 'nan', '1.5', ''])
def test_emulation_prerequisite_budget_stays_bounded(monkeypatch, value):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / 'scripts/dev.py'
    spec = importlib.util.spec_from_file_location('emulation_dev', path)
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)
    monkeypatch.setenv('CT_PREREQUISITE_TIMEOUT_SECONDS', value)
    with pytest.raises(ValueError, match='integer from 1 to 120'):
        dev.doctor(dev.declaration(), 'production-offline')


@pytest.mark.parametrize('value,expected', [(None, 15), ('60', 60)])
def test_prerequisite_budget_changes_only_bounded_import_checks(monkeypatch, value, expected):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / 'scripts/dev.py'
    spec = importlib.util.spec_from_file_location('bounded_dev', path)
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)
    if value is None:
        monkeypatch.delenv('CT_PREREQUISITE_TIMEOUT_SECONDS', raising=False)
    else:
        monkeypatch.setenv('CT_PREREQUISITE_TIMEOUT_SECONDS', value)
    calls = []
    config = dev.declaration()
    root = path.parent.parent
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if 'import pyarrow' in command[2]:
            return SimpleNamespace(stdout='25.0.1')
        name = command[-1]
        return SimpleNamespace(stdout=str(root / config['environment']['imports'][name] / '__init__.py'))
    monkeypatch.setattr(dev, 'run', run)
    config['environment']['native'] = {}
    config['lanes']['production-offline'].pop('required_job_config_env', None)
    dev.doctor(config, 'production-offline')
    assert calls and all(kwargs['timeout'] == expected for _, kwargs in calls)


def test_native_prerequisite_skips_only_when_unconfigured_and_absent(monkeypatch):
    monkeypatch.delenv('DOCSPEC_BINARY', raising=False)
    monkeypatch.delenv('DOCSPEC_BIN', raising=False)
    monkeypatch.setattr(helpers, 'resolve_docspec_binary', Mock(side_effect=FileNotFoundError))
    with pytest.raises(pytest.skip.Exception, match='Native DocSpec fixture'):
        helpers.require_native_docspec()


def test_explicit_missing_native_prerequisite_fails(monkeypatch):
    monkeypatch.setenv('DOCSPEC_BINARY', '/missing/docspec')
    resolve = Mock(side_effect=FileNotFoundError('configured path missing'))
    monkeypatch.setattr(helpers, 'resolve_docspec_binary', resolve)
    with pytest.raises(FileNotFoundError, match='configured path missing'):
        helpers.require_native_docspec()
    resolve.assert_called_once_with('/missing/docspec')


def test_configured_native_prerequisite_is_selected(monkeypatch):
    monkeypatch.setenv('DOCSPEC_BINARY', '/approved/docspec')
    resolve = Mock(return_value='/approved/docspec')
    monkeypatch.setattr(helpers, 'resolve_docspec_binary', resolve)
    assert helpers.require_native_docspec() == '/approved/docspec'
    resolve.assert_called_once_with('/approved/docspec')


def test_validation_installs_private_runtime_only_for_trusted_sources(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load((root / '.github/workflows/validate-explorer.yml').read_text(), Loader=yaml.BaseLoader)
    for job in ('validate', 'offline'):
        steps = workflow['jobs'][job]['steps']
        install = next(step for step in steps if step.get('uses') == './.github/actions/setup-local-job-runtime')
        assert install['if'] == "github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository"
        assert install['with']['artifact'] == '${{ vars.DOCSPEC_RUNTIME_ARTIFACT }}'
    action = yaml.load((root / '.github/actions/setup-local-job-runtime/action.yml').read_text(), Loader=yaml.BaseLoader)
    runtime_steps = [step for step in action['runs']['steps']
                     if 'setup-native-runtime.py' in step.get('run', '')]
    assert len(runtime_steps) == 1
    assert '--local' in runtime_steps[0]['run']
    assert runtime_steps[0]['env']['DOCSPEC_ENGINE_CREDENTIALS'] == '${{ inputs.credentials }}'
    assert all('DOCSPEC_ENGINE_CREDENTIALS' not in step.get('env', {})
               for step in action['runs']['steps'] if step is not runtime_steps[0])
    assert any(step.get('run') == (
        'set +e\n'
        '.venv/bin/python scripts/dev.py test production-offline --shard ${{ matrix.shard }}/6 -- \\\n'
        '  -v --junitxml=${{ runner.temp }}/offline-${{ matrix.shard }}.xml\n'
        'test_status=$?\n'
        "printf 'CT_OFFLINE_EXIT_STATUS=%s\\n' \"$test_status\"\n"
        'exit "$test_status"\n')
        for step in workflow['jobs']['offline']['steps'])
    # Exercise the maintained missing-artifact refusal before any download or export.
    spec = importlib.util.spec_from_file_location('landing_native_setup', root/'.github/scripts/setup-native-runtime.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    monkeypatch.delenv('DOCSPEC_RUNTIME_ARTIFACT', raising=False)
    monkeypatch.delenv('DOCSPEC_ENGINE_CREDENTIALS', raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail('Missing runtime reached private storage')
    monkeypatch.setattr(helper, 'make_client', forbidden)
    envfile = tmp_path/'github-env'; envfile.touch()
    assert helper.main(['--local','--directory',str(tmp_path/'runtime'),
        '--output',str(tmp_path/'report.json'),'--github-env',str(envfile)]) == 1
    assert envfile.read_text() == '' and not (tmp_path/'runtime').exists()
