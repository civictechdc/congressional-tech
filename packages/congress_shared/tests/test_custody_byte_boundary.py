"""Metadata custody and actual byte verification remain separate checks."""
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import sys

import pytest

from congress_shared.custody import issue_verified_file,verify_local_file


@contextmanager
def opened_paths(target):
    active=True;opened=[]
    def audit(event,args):
        if active and event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
            if Path(os.fsdecode(args[0])).absolute()==target.absolute():opened.append(args[0])
    sys.addaudithook(audit)
    try:yield opened
    finally:active=False


def test_metadata_custody_requires_unchanged_issued_file_without_opening_bytes(tmp_path):
    target=tmp_path/'opaque';target.write_bytes(b'opaque provenance')
    proof=verify_local_file(target)
    with opened_paths(target) as opened:
        assert proof._require_custody(target) is proof
    assert opened==[]
    target.write_bytes(b'replaced payload')
    with pytest.raises(ValueError,match='custody'):
        proof._require_custody(target)


def test_actual_byte_consumer_require_hashes_current_file(tmp_path):
    target=tmp_path/'opaque';payload=b'opaque provenance';target.write_bytes(payload)
    proof=verify_local_file(target)
    with opened_paths(target) as opened:
        assert proof.require(target) is proof
    assert len(opened)==1
    assert proof['sha256']==sha256(payload).hexdigest()


def test_actual_byte_consumer_rejects_incorrect_digest_despite_valid_metadata(tmp_path):
    target=tmp_path/'opaque';payload=b'opaque provenance';target.write_bytes(payload)
    proof=issue_verified_file(target,dict(sha256='0'*64,bytes=len(payload)))
    with pytest.raises(ValueError,match='custody or bytes changed'):
        proof.require(target)
