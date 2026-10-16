import json,sys,tempfile,subprocess,types
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['/Users/mikewolfd/.codex/worktrees/recovery-mvp-integration/congressional-tech/scripts','/Users/mikewolfd/.codex/worktrees/recovery-mvp-integration/congressional-tech/tests']
import run_corpus_recovery as runner
import test_coalesce_corpus_recovery_batches as fixtures
from coalesce_corpus_recovery_batches import coalesce
from recovery_guards import RecoveryGuard
output={}
current_runner=runner
runner=types.ModuleType('original_runner')
exec(compile(subprocess.check_output(['git','show','bca225c:scripts/run_corpus_recovery.py'],text=True),'<original_runner>','exec'),runner.__dict__)
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);dest=root/'run'
    runner.prepare(dest,cwd=root,command=[sys.executable,'-c','import time;time.sleep(15)'],
                   resume_command=[sys.executable,'-c','print("second command")'],reserve_bytes=0)
    actual_atomic=runner.atomic;actual_popen=subprocess.Popen;children=[]
    def fail_dispatch(path,value):
        if Path(path).name=='dispatch.json':raise OSError('simulated crash before identity save')
        return actual_atomic(path,value)
    def tracked(*args,**kwargs):
        child=actual_popen(*args,**kwargs)
        if args[0][0]==sys.executable:children.append(child)
        return child
    try:
        with patch.object(runner,'atomic',side_effect=fail_dispatch),patch.object(runner.subprocess,'Popen',side_effect=tracked):
            try:runner.run(dest,interval=.01)
            except OSError:pass
        before=runner.status(dest)
        code=runner.run(dest,resume=True,interval=.01)
        output['dispatch_crash']={'prior_status':before,'resume_exit':code,'old_child_still_alive':children[0].poll() is None}
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
            child.wait()
runner=current_runner
record=dict(pid=123,parent_pid=222,started='Fri Oct 16 00:00:00 2026',command='python worker.py')
with patch.object(runner,'identity',return_value=dict(record,parent_pid=1)):
    output['orphan_identity']={'same_pid_start_command_parent_changed':runner.same_process(record)}
# Guard clock refresh spans the complete multi-request scan, but marks freshness at its end.
clock=[0.0];calls=[]
def slow_cloud():
    calls.append(clock[0]);clock[0]+=100
r=RecoveryGuard(pins={},local_check=lambda:None,cloud_check=slow_cloud,protected_check=lambda:None,clock=lambda:clock[0])
r.check();clock[0]+=1;r.check()
output['cloud_scan_age']={'cloud_scan_started':calls,'now':clock[0],'freshness_recorded_at':r._cloud_at,'second_check_reused':len(calls)==1}
f=fixtures.CoalesceTests();f.setUp()
try:
    batch=f.batch('one','kept',b'new body')
    coalesce([batch],baseline=f.baseline,destination=f.root/'combined')
    output['baseline_overwrite']=json.loads((f.root/'combined/accepted.json').read_text())
finally:f.doCleanups()
print(json.dumps(output,indent=2))
