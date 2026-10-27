"""Expand completed source archives from disk; members never become local paths."""
from dataclasses import dataclass
import hashlib
import mmap
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZIP_STORED, ZIP_DEFLATED, ZipFile
import zlib

from congress_api.models.raw_fetch import BodyFile
from congress_api.parsers.file_wrapper import regular_file
from congress_api.retention.archive_members import ArchiveReadError, _directory_preflight, inspect_office_zip
from congress_api.retention.sniff import read_sniff_file

CHUNK = 1024**2


@dataclass(frozen=True)
class ExpandedMember:
    member_path: str
    entry_index: int
    body: BodyFile


@dataclass(frozen=True)
class Expansion:
    status: str | None
    members: tuple = ()


def _body(path, digest, size):
    facts = read_sniff_file(path)
    return BodyFile(path,digest,size,None,facts['format'],facts['parser_version'],facts['intact'],facts['error_type'])


def expand_archive(path, *, directory, limits):
    """Return complete members and a container-level refusal or expanded status.

    Memory is O(chunk + bounded ZIP directory), disk O(allowed expanded bytes).
    The supplied registry limits are mandatory; no transport or page policy
    enters this component. Nested archives are retained as ordinary members.
    """
    path, directory = Path(path), Path(directory)
    with path.open('rb') as source:
        magic = source.read(4)
        size = source.seek(0,2)
    if magic not in {b'PK\x03\x04',b'PK\x05\x06',b'rtfd'}:
        return Expansion(None)
    if size > limits.max_archive_bytes:
        return Expansion('archive_size_limit')
    members, refusal = [], None
    try:
        with path.open('rb') as source, mmap.mmap(source.fileno(),0,access=mmap.ACCESS_READ) as view:
            if magic == b'rtfd':
                wrapped = regular_file(view)
                length = len(wrapped.data)
                if length > limits.max_member_bytes or length > limits.max_total_bytes:
                    del wrapped
                    return Expansion('member_size_limit' if length > limits.max_member_bytes else 'aggregate_size_limit')
                directory.mkdir(parents=True,exist_ok=True)
                output = directory/(uuid4().hex+'.member')
                digest = hashlib.sha256()
                with output.open('xb') as target:
                    for start in range(0,length,CHUNK):
                        chunk = wrapped.data[start:start+CHUNK]
                        target.write(chunk)
                        digest.update(chunk)
                        del chunk
                name = wrapped.name
                del wrapped
                return Expansion('expanded',(ExpandedMember(name,0,_body(output,digest.hexdigest(),length)),))
            _directory_preflight(view,limits)
            if inspect_office_zip(view,limits=limits):
                return Expansion(None)
        total = 0
        with ZipFile(path) as archive:
            for position, entry in enumerate(archive.infolist()):
                if entry.is_dir():
                    continue
                reason = ('encrypted_member' if entry.flag_bits & 1 else
                          'unsupported_compression' if entry.compress_type not in {ZIP_STORED,ZIP_DEFLATED} else
                          'member_size_limit' if entry.file_size > limits.max_member_bytes else
                          'aggregate_size_limit' if entry.file_size > limits.max_total_bytes-total else None)
                if reason:
                    refusal = refusal or reason
                    continue
                directory.mkdir(parents=True,exist_ok=True)
                output = directory/(uuid4().hex+'.member')
                digest, count = hashlib.sha256(), 0
                try:
                    with archive.open(entry) as member, output.open('xb') as target:
                        while chunk := member.read(min(CHUNK,limits.max_member_bytes-count+1)):
                            count += len(chunk)
                            total += len(chunk)
                            if count > limits.max_member_bytes or total > limits.max_total_bytes:
                                raise ArchiveReadError('member_size_limit' if count > limits.max_member_bytes else
                                                       'aggregate_size_limit','Expanded member exceeds registry limit')
                            target.write(chunk)
                            digest.update(chunk)
                    if count != entry.file_size:
                        raise ArchiveReadError('corrupt_member','Expanded member size differs')
                except (BadZipFile,EOFError,ValueError,RuntimeError,NotImplementedError,zlib.error) as exc:
                    output.unlink(missing_ok=True)
                    refusal = refusal or getattr(exc,'status','corrupt_member')
                    continue
                members.append(ExpandedMember(entry.orig_filename,position,_body(output,digest.hexdigest(),count)))
    except (ArchiveReadError,BadZipFile,UnicodeError,ValueError,NotImplementedError) as exc:
        return Expansion(getattr(exc,'status','corrupt_archive'),tuple(members))
    return Expansion(refusal or 'expanded',tuple(members))
