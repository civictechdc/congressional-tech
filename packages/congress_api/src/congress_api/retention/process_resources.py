"""Sample a directly owned child through the host API, never its environment."""
import ctypes
import errno
from functools import lru_cache
import os
from pathlib import Path
import sys


class ProcessResourceError(RuntimeError):
    """The host cannot measure the child reliably."""


class _ProcTaskInfo(ctypes.Structure):
    # macOS SDK sys/proc_info.h: struct proc_taskinfo, in declared ABI order.
    _fields_=[(name,ctypes.c_uint64) for name in (
        'pti_virtual_size','pti_resident_size','pti_total_user','pti_total_system',
        'pti_threads_user','pti_threads_system')]+[(name,ctypes.c_int32) for name in (
        'pti_policy','pti_faults','pti_pageins','pti_cow_faults','pti_messages_sent',
        'pti_messages_received','pti_syscalls_mach','pti_syscalls_unix','pti_csw',
        'pti_threadnum','pti_numrunning','pti_priority')]


@lru_cache(maxsize=1)
def _libproc():
    # Fixed system path avoids find_library helpers that may launch processes.
    library=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True)
    library.proc_pidinfo.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint64,
                                  ctypes.c_void_p,ctypes.c_int]
    library.proc_pidinfo.restype=ctypes.c_int
    return library


def _exited(pid):
    try:os.kill(pid,0)
    except ProcessLookupError:return True
    return False


def _darwin_resident_bytes(pid):
    info=_ProcTaskInfo()
    ctypes.set_errno(0)
    # PROC_PIDTASKINFO=4; libproc.h declares the result as bytes copied.
    copied=_libproc().proc_pidinfo(pid,4,0,ctypes.byref(info),ctypes.sizeof(info))
    if copied==ctypes.sizeof(info):return info.pti_resident_size
    if copied==0 and (ctypes.get_errno()==errno.ESRCH or _exited(pid)):return 0
    raise ProcessResourceError('Process memory measurement unavailable')


def _linux_resident_bytes(pid):
    try:
        with Path(f'/proc/{pid}/statm').open(encoding='ascii') as source:
            fields=source.read(256).split()
    except FileNotFoundError:
        # Missing procfs or a denied namespace is not an exited process.
        if _exited(pid):return 0
        raise ProcessResourceError('Process memory measurement unavailable') from None
    if len(fields)<2:raise ProcessResourceError('Process memory measurement unavailable')
    pages=int(fields[1]);page_size=os.sysconf('SC_PAGE_SIZE')
    if pages<0 or page_size<=0:raise ProcessResourceError('Process memory measurement unavailable')
    return pages*page_size


def resident_bytes(pid):
    """Return current RSS bytes, or zero only for a valid measured/exited process."""
    if type(pid) is not int or not 0<pid<(1<<31):
        raise ProcessResourceError('A positive signed 32-bit process identifier is required')
    try:
        if sys.platform=='darwin':return _darwin_resident_bytes(pid)
        if sys.platform.startswith('linux'):return _linux_resident_bytes(pid)
        raise ProcessResourceError('Process memory measurement unavailable on this host')
    except (OSError,ValueError,AttributeError,ctypes.ArgumentError) as exc:
        raise ProcessResourceError('Process memory measurement unavailable') from exc
