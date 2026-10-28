"""Sample resident memory for a process and its children.

Publication cost measurement and the viewer benchmark share this sampler.
Missing samples stay explicit at the call site.
"""
import subprocess
import ctypes
import errno
import sys


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


def physical_tree(pid):
    """Sample macOS charged memory, including compressed memory; None elsewhere.

    RUSAGE_INFO_V0 follows the installed macOS SDK's sys/resource.h layout.
    RSS alone can miss compressed private allocations on a memory-busy Mac.
    """
    if sys.platform!='darwin':return None
    class Rusage(ctypes.Structure):
        _fields_=[('uuid',ctypes.c_uint8*16)]+[(name,ctypes.c_uint64) for name in
            ('user','system','pkg_idle','interrupt','pageins','wired','resident','footprint','start','exit')]
    sample=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True).proc_pid_rusage
    sample.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_void_p];sample.restype=ctypes.c_int
    total=0
    for process in process_tree(pid):
        usage=Rusage()
        if sample(process,0,ctypes.byref(usage)):
            code=ctypes.get_errno()
            if code==errno.ESRCH:continue
            raise OSError(code,'Cannot sample owned physical footprint')
        total+=usage.footprint
    return total
