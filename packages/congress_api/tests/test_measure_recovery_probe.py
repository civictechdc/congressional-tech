"""Moved recovery measurements keep each selected revision internally consistent."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
PROBE = ROOT / 'scripts/measure/probe_corpus_recovery_memory.py'


@pytest.mark.parametrize('baseline_ref', ['37ee074', 'HEAD'])
@pytest.mark.parametrize('mode', ['import', 'preservation'])
def test_historical_and_current_probe_arms_complete(mode, baseline_ref):
    result = subprocess.run([sys.executable, str(PROBE), '--baseline-ref', baseline_ref,
                             '--mode', mode, '--rows', '8', '--additions', '2'],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    evidence = json.loads(result.stdout)
    assert evidence['synthetic_only']
    assert [item['ref'] for item in evidence['results']] == [baseline_ref, 'worktree']
    if mode == 'import':
        assert all(item['complete'] for item in evidence['results'])
        assert all(item['states_preserved'] == 8 and item['new_pending_states'] == 2
                   for item in evidence['results'])
    else:
        assert all(item['local_preservation_verified'] and item['existing_states_preserved'] == 8
                   and item['new_pending_states'] == 2 for item in evidence['results'])


def test_package_baseline_imports_its_selected_assembly_and_acknowledgment(monkeypatch):
    spec = importlib.util.spec_from_file_location('recovery_probe', PROBE)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    # Isolate package/module replacement as the real probe's child process does.
    before = dict(sys.modules)
    def selected(command, **kwargs):
        path = command[-1].split(':', 1)[1]
        name = Path(path).stem
        sources = {
            'acknowledge': 'def reconcile_lost_acknowledgment(*args): return "selected"',
            'inventory': 'def head_body(): pass\ndef reusable_result(): pass',
            'assemble': 'def assemble(): return "selected"\ndef index_rows(): pass',
            'preservation': 'def verify(root): return {"selected": True}',
            'transfer': ('from corpus_recovery.assemble import assemble\n'
                         'from corpus_recovery.acknowledge import reconcile_lost_acknowledgment\n'),
        }
        return sources.get(name, '')
    monkeypatch.setattr(probe.subprocess, 'check_output', selected)
    try:
        importer, verifier = probe.implementation('HEAD')
        assert importer.assemble() == 'selected'
        assert importer.reconcile_lost_acknowledgment() == 'selected'
        assert importer.assemble is sys.modules['corpus_recovery.assemble'].assemble
        assert verifier.verify(None) == {'selected': True}
        assert importer.__name__ == 'corpus_recovery.transfer'
    finally:
        for name in list(sys.modules):
            if name == 'corpus_recovery' or name.startswith('corpus_recovery.'):
                if name in before:
                    sys.modules[name] = before[name]
                else:
                    del sys.modules[name]
