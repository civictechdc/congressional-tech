"""Read the observed v3 regular-file subset of Apple's serialized FileWrapper.

This is not a general RTFD directory reader. Exact field names, block boundaries,
and types must agree; unfamiliar layouts are refused. Differential fixtures
come from Foundation FileWrapper, including both audited publisher responses.
"""
from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class WrappedFile:
    name: str
    offset: int
    data: memoryview


def regular_file(data: bytes) -> WrappedFile:
    """Return a zero-copy, length-delimited payload; never search for PDF magic."""
    if data[:16] != b'rtfd' + struct.pack('<3I', 0, 3, 4):
        raise ValueError('Unsupported serialized file wrapper')
    cursor = 16

    def word():
        nonlocal cursor
        if cursor + 4 > len(data):
            raise ValueError('Truncated file wrapper')
        result = struct.unpack_from('<I', data, cursor)[0]
        cursor += 4
        return result

    for expected in (b'..', b'__@PreferredName@__', b'__@UTF8PreferredName@__', b'.'):
        size = word()
        if size != len(expected) or data[cursor:cursor + size] != expected:
            raise ValueError('Unsupported file wrapper fields')
        cursor += size
    sizes = [word() for _ in range(4)]
    if cursor + sum(sizes) != len(data):
        raise ValueError('File wrapper block lengths disagree')
    payloads = []
    for index, size in enumerate(sizes):
        end = cursor + size
        if size < 8 or word() != 1:
            raise ValueError('Unsupported file wrapper block')
        length = word()
        if length == 0x80000000:
            if index != 0 or size < 16:
                raise ValueError('Unsupported padded file wrapper block')
            length, padding = word(), word()
            if cursor + padding + length != end or any(memoryview(data)[cursor:cursor + padding]):
                raise ValueError('File wrapper padding disagrees')
            cursor += padding
        if cursor + length != end:
            raise ValueError('File wrapper payload length disagrees')
        payloads.append((cursor, memoryview(data)[cursor:end]))
        cursor = end
    # The observed regular-file metadata describes exactly one '..' entry,
    # with a 16-byte attribute record. Only its permissions value varies.
    attributes = payloads[3][1]
    if (len(attributes) != 30
            or attributes[:18] != struct.pack('<2I', 1, 2) + b'..' + struct.pack('<2I', 16, 0)
            or attributes[22:] != struct.pack('<2I', 2, 1)):
        raise ValueError('Unsupported file wrapper attributes')
    if len(payloads[2][1]) > 16384:
        raise ValueError('File wrapper name exceeds limit')
    name = payloads[2][1].tobytes().decode('utf-8')
    if not name or len(name) > 4096 or '\x00' in name:
        raise ValueError('Invalid file wrapper name')
    return WrappedFile(name, payloads[0][0], payloads[0][1])
