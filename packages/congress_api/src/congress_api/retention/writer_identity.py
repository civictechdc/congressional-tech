"""Raw writer identity: a clean application commit and the locked dependencies."""
import hashlib
from pathlib import Path
import subprocess


def writer_identity(root, job):
    """Refuse uncommitted files before exposing an identity for permanent receipts."""
    root = Path(root).resolve()

    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

    def require_clean():
        if git('status', '--porcelain'):
            raise ValueError('Raw receipt writers require a clean application tree')

    require_clean()
    commit = git('rev-parse', 'HEAD')
    with (root / 'uv.lock').open('rb') as source:
        lockfile_digest = hashlib.file_digest(source, 'sha256').hexdigest()
    require_clean()
    if git('rev-parse', 'HEAD') != commit:
        raise ValueError('Application commit changed while recording writer identity')
    return dict(job=job, commit=commit, lockfile_digest=lockfile_digest)
