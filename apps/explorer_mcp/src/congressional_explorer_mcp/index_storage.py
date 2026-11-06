"""Immutable SQLite snapshots and explicitly qualified filesystem clones."""
import ctypes
from hashlib import sha256, md5
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from .models import ExplorerError
from .release import atomic_json, stamp, same_stamp

_qualified_devices=set()


def _native_clone(source,target):
    if sys.platform=='darwin':
        library=ctypes.CDLL(None,use_errno=True)
        clone=getattr(library,'clonefile',None)
        if clone is None:
            raise ExplorerError('This filesystem has no native copy-on-write clone operation')
        clone.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int];clone.restype=ctypes.c_int
        if clone(os.fsencode(source),os.fsencode(target),0):
            code=ctypes.get_errno()
            raise OSError(code,os.strerror(code))
        return 'clonefile'
    if sys.platform.startswith('linux'):
        subprocess.run(['cp','--reflink=always','--',str(source),str(target)],check=True,capture_output=True)
        return 'reflink=always'
    raise ExplorerError('Freeze mode requires native copy-on-write clones; use separately admitted copy storage')


def preflight(work):
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    device=work.stat().st_dev
    if device in _qualified_devices:
        return
    try:
        with TemporaryDirectory(dir=work,prefix='.cow-probe-') as directory:
            source,target=Path(directory)/'source',Path(directory)/'clone'
            source.write_bytes(b'Accepted immutable source\n'*100)
            _native_clone(source,target)
            if source.stat().st_ino==target.stat().st_ino:
                raise ExplorerError('Clone reused the source inode')
            target.write_bytes(b'Independent writable generation')
            if source.read_bytes()!=b'Accepted immutable source\n'*100:
                raise ExplorerError('Clone mutation changed the immutable source')
    except (OSError,subprocess.SubprocessError) as error:
        raise ExplorerError('Native copy-on-write storage is unavailable; freeze preparation refused before writes') from error
    _qualified_devices.add(device)


def facts(path):
    digest,checksum=sha256(),md5()
    with Path(path).open('rb') as source:
        while block:=source.read(1<<20):
            digest.update(block);checksum.update(block)
    return dict(sha256=digest.hexdigest(),md5=checksum.hexdigest(),size=Path(path).stat().st_size)


def _verified(receipt):
    path=Path(receipt['path'])
    if path.is_symlink() or not path.is_file():
        raise ExplorerError('Retained immutable index is missing or a symlink; preserve its receipt')
    if not same_stamp(path,receipt['stamp']):
        # Removing another hardlink changes ctime. A necessary requalification
        # reads the accepted bytes, never the source corpus or its parser again.
        if facts(path)!=receipt['facts']:
            raise ExplorerError('Retained immutable index custody changed; preserve it for diagnosis')
        receipt['stamp']=stamp(path)
    return path


def prepare_work(work, *, mode):
    work=Path(work)
    if mode!='freeze':
        return
    preflight(work)
    recover(work)
    target=work/'work.sqlite'
    if target.exists():
        marker=work/'frozen-index.json'
        if marker.exists():
            state=json.loads(marker.read_bytes())
            if any(Path(item['path']).exists() and os.path.samefile(target,item['path']) for item in state.get('snapshots',[])):
                raise ExplorerError('Writable index work shares an accepted immutable inode')
        return
    marker=work/'frozen-index.json'
    if not marker.exists():
        return
    state=json.loads(marker.read_bytes())
    if not state.get('snapshots'):
        raise ExplorerError('Retained index marker has no accepted snapshot')
    source=_verified(state['snapshots'][-1])
    try:
        _native_clone(source,target)
        if source.stat().st_ino==target.stat().st_ino:
            raise ExplorerError('Writable index generation shares the accepted inode')
        target.chmod(0o600)
        state['snapshots'][-1]['stamp']=stamp(source)
        atomic_json(marker,state)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def recover(work):
    work=Path(work);intent_path=work/'freeze-intent.json'
    if not intent_path.exists():
        return
    intent=json.loads(intent_path.read_bytes())
    mutable,frozen,output=map(Path,(intent['mutable'],intent['path'],intent['output']))
    if mutable.parent!=work or frozen.parent!=work or mutable.name!='work.sqlite':
        raise ExplorerError('Freeze intent escapes its owned work directory')
    if not frozen.exists():
        if not mutable.is_file() or mutable.is_symlink() or (not same_stamp(mutable,intent.get('mutable_stamp')) and facts(mutable)!=intent['facts']):
            raise ExplorerError('Interrupted freeze has no matching complete SQLite bytes')
        mutable.chmod(0o444)
        os.replace(mutable,frozen)
    elif frozen.is_symlink() or facts(frozen)!=intent['facts']:
        raise ExplorerError('Interrupted immutable index differs from its accepted byte pin')
    if output.exists():
        if output.is_symlink():
            raise ExplorerError('Freeze output is a symlink')
        if not os.path.samefile(frozen,output):
            raise ExplorerError('Freeze output already identifies another immutable file')
    else:
        os.link(frozen,output)
    descriptor=os.open(output.parent,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    receipt={key:intent[key] for key in ('path','facts','source_data_id','definition')}
    receipt['stamp']=stamp(frozen)
    marker=work/'frozen-index.json'
    state=json.loads(marker.read_bytes()) if marker.exists() else dict(version=1,snapshots=[])
    if not any(item['facts']==receipt['facts'] for item in state['snapshots']):
        state['snapshots'].append(receipt)
    atomic_json(marker,state)
    intent_path.unlink()
    descriptor=os.open(work,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def freeze(work,output,report):
    work,output=Path(work),Path(output)
    preflight(work)
    if work.stat().st_dev!=output.parent.stat().st_dev:
        raise ExplorerError('Freeze output must share the qualified filesystem; no bulk-copy fallback')
    identity=facts(work/'work.sqlite')
    frozen=work/f"index-{identity['sha256']}.sqlite"
    atomic_json(work/'freeze-intent.json',dict(mutable=str(work/'work.sqlite'),path=str(frozen),output=str(output),
        mutable_stamp=stamp(work/'work.sqlite'),facts=identity,source_data_id=report['source_data_id'],definition=report['definition']['sha256']))
    descriptor=os.open(work,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    recover(work)
    return dict(identity,stamp=stamp(output),path=str(output))


def historical(work):
    marker=Path(work)/'frozen-index.json'
    if not marker.exists():
        return []
    state=json.loads(marker.read_bytes())
    return list(reversed(state['snapshots']))


def register_copy(work,output,report,identity):
    marker=Path(work)/'frozen-index.json'
    state=json.loads(marker.read_bytes()) if marker.exists() else dict(version=1,snapshots=[])
    receipt=dict(path=str(output),facts=identity,stamp=stamp(output),source_data_id=report['source_data_id'],definition=report['definition']['sha256'])
    if not any(item['facts']==identity for item in state['snapshots']):
        state['snapshots'].append(receipt)
    atomic_json(marker,state)


def output_identity(work,output):
    for receipt in historical(work):
        if Path(receipt['path']).exists() and os.path.samefile(receipt['path'],output):
            verify_historical(work,receipt)
            return dict(receipt['facts'],path=str(output),stamp=stamp(output))
    return dict(facts(output),path=str(output),stamp=stamp(output))


def verify_historical(work,receipt):
    path=_verified(receipt)
    marker=Path(work)/'frozen-index.json'
    state=json.loads(marker.read_bytes())
    for index,value in enumerate(state['snapshots']):
        if value['path']==receipt['path']:
            state['snapshots'][index]=receipt
            atomic_json(marker,state)
            break
    return path
