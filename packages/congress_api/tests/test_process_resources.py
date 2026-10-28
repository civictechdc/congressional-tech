"""Direct worker memory sampling neither launches processes nor hides failures."""
import subprocess
import sys

import pytest

from congress_api.retention.process_resources import ProcessResourceError,resident_bytes


def test_owned_child_rss_and_exit_without_a_sampling_subprocess():
    child_code="import sys; memory=bytearray(8*1024**2); print('ready',flush=True); sys.stdin.buffer.read(1)"
    guard={'active':False}
    def audit(event,args):
        if guard['active'] and event in {'subprocess.Popen','os.posix_spawn','os.system','os.exec'}:
            raise AssertionError('Memory sampling must not launch a process')
    sys.addaudithook(audit)
    with subprocess.Popen([sys.executable,'-I','-u','-c',child_code],stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE) as child:
        assert child.stdout.readline()==b'ready\n'
        try:
            guard['active']=True
            for _ in range(5):assert resident_bytes(child.pid)>0
        finally:guard['active']=False
        child.stdin.write(b'x');child.stdin.flush()
        child.wait(timeout=10)
        try:
            guard['active']=True
            assert resident_bytes(child.pid)==0
        finally:guard['active']=False


@pytest.mark.parametrize('pid',[None,True,'1',1.0,0,-1,1<<31])
def test_invalid_process_identifiers_refuse(pid):
    with pytest.raises(ProcessResourceError):resident_bytes(pid)


def test_unavailable_native_measurement_refuses_instead_of_reporting_zero():
    # The OS audit policy denies only this child's native sampler. No replacement
    # function or fabricated sampler result can turn an unavailable API into zero.
    script='''import os,sys
from congress_api.retention.process_resources import ProcessResourceError,resident_bytes
pid=os.getpid()
def deny(event,args):
    if sys.platform=='darwin' and event=='ctypes.dlopen':
        raise OSError('Sampler library unavailable')
    if sys.platform.startswith('linux') and event=='open' and args[0]==f'/proc/{pid}/statm':
        raise PermissionError('Sampler file unavailable')
sys.addaudithook(deny)
try:resident_bytes(pid)
except ProcessResourceError:print('refused')
else:raise AssertionError('An unavailable sampler must refuse')
'''
    result=subprocess.run([sys.executable,'-I','-c',script],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert result.stdout=='refused\n'


def test_direct_virtual_size_includes_an_untouched_mapping_without_a_subprocess():
    import mmap
    import os
    from congress_api.retention.process_resources import virtual_bytes
    pid=os.getpid();before=virtual_bytes(pid)
    with mmap.mmap(-1,64<<20):
        assert virtual_bytes(pid)>=before+(64<<20)
        assert resident_bytes(pid)<virtual_bytes(pid)
    assert virtual_bytes(pid)>0


@pytest.mark.parametrize('pid',[None,True,'1',1.0,0,-1,1<<31])
def test_virtual_size_rejects_invalid_process_identifiers(pid):
    from congress_api.retention.process_resources import virtual_bytes
    with pytest.raises(ProcessResourceError):virtual_bytes(pid)
