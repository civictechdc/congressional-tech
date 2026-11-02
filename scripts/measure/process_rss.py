"""Sample resident memory for a process tree, and own that tree's lifetime.

Publication cost measurement, the viewer benchmark, the capture backfill monitor and
the archive watchdog share this sampler and start_owned/stop_owned. Missing samples
stay explicit at the call site. Standard library only.
"""
import subprocess
import ctypes
import errno
import os
import signal
import sys
from pathlib import Path


def process_tree(pid):
    """Return the same owned descendant inventory used by memory samples."""
    rows = subprocess.run(['ps', '-axo', 'pid=,ppid=,rss='], capture_output=True, text=True, check=True, timeout=5).stdout
    processes = {int(p): (int(parent), int(rss) * 1024) for p, parent, rss in (line.split() for line in rows.splitlines())}
    children = {pid}
    while True:
        found = {p for p, (parent, _) in processes.items() if parent in children}
        if found <= children:
            return {p:processes[p] for p in children if p in processes}
        children.update(found)


def resident_tree(pid):
    """Same process-tree RSS sampler for every arm; missing samples are explicit."""
    return sum(value[1] for value in process_tree(pid).values())


def _running(pid):
    result=subprocess.run(['ps','-p',str(pid),'-o','stat='],capture_output=True,text=True,timeout=5)
    if result.returncode not in (0,1):raise OSError('Cannot check sampled process state')
    state=result.stdout.strip()
    return bool(state) and not state.startswith('Z')


def _physical_sum(processes,sample,is_running):
    total=0
    for process in processes:
        try:total+=sample(process)
        except OSError as error:
            if error.errno in (errno.EPERM,errno.ESRCH) and not is_running(process):continue
            raise
    return total


def physical_tree(pid):
    """Sample macOS charged memory, or a conservative Linux RSS+swap proxy.

    RUSAGE_INFO_V0 follows the installed macOS SDK's sys/resource.h layout.
    RSS alone can miss compressed private allocations on a memory-busy Mac.
    """
    if sys.platform=='linux':
        total=0
        for process,(_,rss) in process_tree(pid).items():
            try:
                with (Path('/proc')/str(process)/'status').open() as stream:
                    swap=next((int(line.split()[1])*1024 for line in stream if line.startswith('VmSwap:')),0)
            except FileNotFoundError:continue
            total+=rss+swap
        return total  # Conservative RSS+swap proxy, not a cgroup high-water mark.
    if sys.platform!='darwin':return None
    class Rusage(ctypes.Structure):
        _fields_=[('uuid',ctypes.c_uint8*16)]+[(name,ctypes.c_uint64) for name in
            ('user','system','pkg_idle','interrupt','pageins','wired','resident','footprint','start','exit')]
    sample=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True).proc_pid_rusage
    sample.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_void_p];sample.restype=ctypes.c_int
    def footprint(process):
        usage=Rusage()
        if sample(process,0,ctypes.byref(usage)):
            code=ctypes.get_errno()
            raise OSError(code,'Cannot sample owned physical footprint')
        return usage.footprint
    return _physical_sum(process_tree(pid),footprint,_running)


class MemorySamples:
    """Tolerate two transient tree-sampling gaps, retaining the last valid peak."""
    def __init__(self,sampler):
        self.sampler=sampler
        self.consecutive_failures=0

    def sample(self,pid):
        try:
            rss=self.sampler.resident_tree(pid);physical=self.sampler.physical_tree(pid)
            if physical is None:raise RuntimeError('Missing process memory sample')
        except InterruptedError:
            raise
        except (OSError,RuntimeError,subprocess.SubprocessError) as error:
            self.consecutive_failures+=1
            if self.consecutive_failures>=3:
                raise RuntimeError('Three consecutive whole-tree memory samples failed') from error
            return None
        self.consecutive_failures=0
        return rss,physical


# The owned group leader watches its starter: if the starter dies, even by SIGKILL,
# the leader TERMs and then KILLs its whole group, so no job outlives its owner.
_OWNER = """import os,signal,subprocess,sys,time
parent=int(sys.argv[1])
process=subprocess.Popen(sys.argv[2:])
while process.poll() is None:
 if os.getppid()!=parent:
  signal.signal(signal.SIGTERM,signal.SIG_IGN)
  os.killpg(os.getpgrp(),signal.SIGTERM)
  time.sleep(2)
  os.killpg(os.getpgrp(),signal.SIGKILL)
 time.sleep(.1)
raise SystemExit(process.returncode)
"""


def _group_is_live(group):
    result=subprocess.run(['ps','-axo','pgid=,stat='],capture_output=True,text=True,check=True,timeout=5)
    return any(int(parts[0])==group and not parts[1].startswith('Z')
        for line in result.stdout.splitlines() if len(parts:=line.split())==2)


def _signal_group(group,number,send,is_live):
    try:send(group,number)
    except OSError as error:
        if error.errno in (errno.EPERM,errno.ESRCH) and not is_live(group):
            return dict(signal=number,errno=error.errno,group_exited=True)
        raise


def _cleanup_child(child,send):
    errors=[]
    def attempt(operation):
        try:
            note=operation()
            if isinstance(note,dict):errors.append(note)
        except Exception as error:
            errors.append(dict(type=type(error).__name__,message=str(error)))
    if child.poll() is None:
        attempt(lambda:send(signal.SIGTERM))
        attempt(lambda:child.wait(timeout=5))
    # A TERM-ignoring descendant may outlive the already-exited leader.
    attempt(lambda:send(signal.SIGKILL))
    attempt(lambda:child.wait(timeout=5))
    return errors


def start_owned(command,**popen):
    """Start a command in its own process group, led by the parent-death trampoline."""
    return subprocess.Popen([sys.executable,'-I','-c',_OWNER,str(os.getpid()),*command],start_new_session=True,**popen)


def stop_owned(child):
    """TERM the owned group, wait 5 s, then always KILL it; return cleanup notes, never raise."""
    return _cleanup_child(child,lambda number:_signal_group(child.pid,number,os.killpg,_group_is_live))
