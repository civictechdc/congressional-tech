import importlib.util
from types import SimpleNamespace

import pytest

from conftest import REPO

spec = importlib.util.spec_from_file_location('mcp_project_runner', REPO/'scripts/dev.py')
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


def test_root_runner_selects_app_runtime_and_keeps_suite_boundary(monkeypatch):
    monkeypatch.setattr(dev,'inventory',lambda config:set())
    monkeypatch.setattr(dev,'doctor',lambda *args:pytest.fail('MCP must use its own DuckDB runtime'))
    calls=[]
    monkeypatch.setattr(dev.subprocess,'run',lambda command,**kwargs:calls.append(command) or SimpleNamespace(returncode=0))
    assert dev.test(dev.declaration(),'explorer-mcp',[],['-q']) == 0
    assert calls == [[str(REPO/'apps/explorer_mcp/.venv/bin/python'),str(REPO/'apps/explorer_mcp/scripts/dev.py'),
                     'test',str(REPO/'apps/explorer_mcp/tests'),'-q']]
    with pytest.raises(ValueError,match='outside'):
        dev.test(dev.declaration(),'explorer-mcp',['packages/congress_api/tests'],[])
    assert len(calls) == 1
