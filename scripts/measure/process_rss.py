"""Sample resident memory for a process and its children.

Publication cost measurement and the viewer benchmark share this sampler.
Missing samples stay explicit at the call site.
"""
import subprocess
import ctypes
import errno
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
