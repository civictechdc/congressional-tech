"""Scratch cleanup races skip only paths which have actually vanished."""
from contextlib import contextmanager
import errno
import os
import shutil
from pathlib import Path

import pytest

from congress_api.lake.capture_backfill import _allocated_bytes,check_scratch


def test_queued_directory_vanishes_before_open_and_retained_blocks_are_counted(tmp_path):
    vanished=tmp_path/'request-temporary';vanished.mkdir()
    retained=tmp_path/'retained';retained.write_bytes(b'x'*8192)
    expected=retained.stat().st_blocks*512
    opened=[]
    @contextmanager
    def scan(path):
        opened.append(Path(path))
        with os.scandir(path) as entries:yield entries
        if Path(path)==tmp_path:vanished.rmdir()
    assert _allocated_bytes(tmp_path,scan=scan)==expected
    assert opened==[tmp_path,vanished] and not vanished.exists()
    assert retained.read_bytes()==b'x'*8192


def test_listed_file_vanishes_before_stat_without_hiding_retained_blocks(tmp_path):
    vanished=tmp_path/'removed';vanished.write_bytes(b'x'*4096)
    retained=tmp_path/'retained';retained.write_bytes(b'y'*8192)
    @contextmanager
    def scan(path):
        with os.scandir(path) as entries:
            listed=list(entries)
            vanished.unlink()
            yield iter(listed)
    assert _allocated_bytes(tmp_path,scan=scan)==retained.stat().st_blocks*512
    assert not vanished.exists()


@pytest.mark.parametrize('operation',['open','is_dir','stat'])
@pytest.mark.parametrize('code',[errno.EACCES,errno.EIO,errno.ENOTDIR,errno.EINTR])
def test_other_scan_and_entry_errors_remain_failures(tmp_path,operation,code):
    (tmp_path/'retained').write_bytes(b'x')
    class Entry:
        def __init__(self,entry):self.entry=entry;self.path=entry.path
        def is_dir(self,*,follow_symlinks):
            if operation=='is_dir':raise OSError(code,'injected non-missing entry error')
            return self.entry.is_dir(follow_symlinks=follow_symlinks)
        def stat(self,*,follow_symlinks):
            if operation=='stat':raise OSError(code,'injected non-missing stat error')
            return self.entry.stat(follow_symlinks=follow_symlinks)
    @contextmanager
    def scan(path):
        if operation=='open':raise OSError(code,'injected non-missing directory error')
        with os.scandir(path) as entries:yield (Entry(entry) for entry in entries)
    with pytest.raises(OSError) as caught:_allocated_bytes(tmp_path,scan=scan)
    assert caught.value.errno==code


@pytest.mark.parametrize('operation',['open','is_dir','stat'])
def test_enoent_from_custom_oserror_subclass_is_also_a_vanished_path(tmp_path,operation):
    vanished=tmp_path/'removed';vanished.mkdir() if operation=='open' else vanished.write_bytes(b'x')
    retained=tmp_path/'retained';retained.write_bytes(b'y'*8192)
    expected=retained.stat().st_blocks*512
    class MissingPath(OSError):pass
    class Entry:
        def __init__(self,entry):self.entry=entry;self.path=entry.path
        def is_dir(self,*,follow_symlinks):
            if self.path==str(vanished) and operation=='is_dir':
                raise MissingPath(errno.ENOENT,'vanished during classification')
            return self.entry.is_dir(follow_symlinks=follow_symlinks)
        def stat(self,*,follow_symlinks):
            if self.path==str(vanished) and operation=='stat':
                raise MissingPath(errno.ENOENT,'vanished during stat')
            return self.entry.stat(follow_symlinks=follow_symlinks)
    @contextmanager
    def scan(path):
        if Path(path)==vanished:raise MissingPath(errno.ENOENT,'vanished directory')
        with os.scandir(path) as entries:yield (Entry(entry) for entry in entries)
    assert _allocated_bytes(tmp_path,scan=scan)==expected


def test_walk_counts_allocated_blocks_in_nested_files_and_does_not_follow_symlinks(tmp_path):
    nested=tmp_path/'nested';nested.mkdir()
    sparse=nested/'sparse'
    with sparse.open('wb') as stream:
        stream.write(b'x'*4096);stream.truncate(8<<30)
    linked=tmp_path/'linked';linked.symlink_to(nested,target_is_directory=True)
    expected=sparse.lstat().st_blocks*512+linked.lstat().st_blocks*512
    assert expected<5<<30 and sparse.stat().st_size>5<<30
    assert _allocated_bytes(tmp_path)==expected
    assert check_scratch(tmp_path,nested,min_free_bytes=0)==tmp_path


def test_existing_ownership_and_free_space_refusals_stay_enforced(tmp_path):
    with pytest.raises(ValueError,match='Owned scratch'):
        check_scratch(tmp_path,tmp_path.parent/'unowned',min_free_bytes=0)
    with pytest.raises(RuntimeError,match='Free disk'):
        check_scratch(tmp_path,min_free_bytes=1<<100)


def test_job_scratch_excludes_siblings_but_counts_its_own_allocated_blocks(tmp_path):
    job=tmp_path/'job';job.mkdir()
    sibling=tmp_path/'previous-job';sibling.mkdir()
    (sibling/'evidence').write_bytes(b'x'*16384)
    owned=job/'retained';owned.write_bytes(b'y'*4096)
    cap=owned.stat().st_blocks*512
    assert _allocated_bytes(tmp_path)>cap
    assert check_scratch(job,job/'monitor',min_free_bytes=0,max_owned_scratch_bytes=cap)==job
    (job/'spill').write_bytes(b'z'*4096)
    with pytest.raises(RuntimeError,match='scratch exceeds'):
        check_scratch(job,min_free_bytes=0,max_owned_scratch_bytes=cap)
    assert (sibling/'evidence').read_bytes()==b'x'*16384


@pytest.fixture
def over_default_allocated_root(tmp_path):
    """Exercise block accounting above 5 GiB without writing 5 GiB of test data."""
    root=tmp_path/'allocation';root.mkdir()
    payload=root/'payload';payload.write_bytes(b'x'*(1<<20))
    # The guard counts allocated blocks per directory entry, conservatively
    # including hard-link aliases. One MiB physically backs these cheap entries.
    for index in range(5120):os.link(payload,root/str(index))
    try:
        assert _allocated_bytes(root)>5<<30
        yield root
    finally:
        shutil.rmtree(root)


def test_default_scratch_refuses_and_explicit_owned_allowance_preserves_other_guards(over_default_allocated_root):
    root=over_default_allocated_root
    with pytest.raises(RuntimeError,match='scratch exceeds'):check_scratch(root,min_free_bytes=0)
    assert check_scratch(root,min_free_bytes=0,max_owned_scratch_bytes=17<<30)==root
    with pytest.raises(ValueError,match='Owned scratch'):
        check_scratch(root,root.parent/'outside',min_free_bytes=0,max_owned_scratch_bytes=17<<30)
    with pytest.raises(RuntimeError,match='Free disk'):
        check_scratch(root,min_free_bytes=1<<100,max_owned_scratch_bytes=17<<30)


@pytest.mark.parametrize('limit',[0,-1,True,1.5,None])
def test_explicit_owned_allowance_must_be_a_positive_integer(tmp_path,limit):
    with pytest.raises(ValueError,match='max_owned_scratch_bytes'):
        check_scratch(tmp_path,min_free_bytes=0,max_owned_scratch_bytes=limit)


def test_monitor_applies_explicit_allowance_at_admission_and_periodic_checks(over_default_allocated_root):
    from congress_api.lake.capture_backfill import monitor_command
    import sys
    root=over_default_allocated_root;work=root/'monitor'
    command=[sys.executable,'-I','-c','import time;time.sleep(.7)']
    with pytest.raises(RuntimeError,match='scratch exceeds'):
        monitor_command(command,work=work,scratch_root=root,min_free_bytes=0)
    assert not work.exists()
    result=monitor_command(command,work=work,scratch_root=root,min_free_bytes=0,
                           max_owned_scratch_bytes=17<<30)
    assert result['returncode']==0 and result['samples']>0
