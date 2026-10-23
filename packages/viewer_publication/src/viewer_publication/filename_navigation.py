"""Range-readable navigation: one 16-byte record and one group membership slice.

Maintained for historical v5 navigation generation and runtime ownership verification.
"""
from array import array
import struct
import sys


def publish_navigation(groups, preferred, output):
    rows, entries = len(groups), len(preferred)
    counts = array('I', [0]) * entries
    for group in groups:
        if not 0 <= group < entries:
            raise ValueError('Invalid navigation group')
        counts[group] += 1
    offsets = array('I', [0]) * entries
    cursor = 0
    for group, count in enumerate(counts):
        if not count or not 0 <= preferred[group] < rows or groups[preferred[group]] != group:
            raise ValueError('Invalid preferred source')
        offsets[group] = cursor
        cursor += count
    members = array('I', [0]) * rows
    positions = array('I', offsets)
    nav_path, member_path = output / 'detail-navigation.bin', output / 'detail-members.bin'
    with nav_path.open('wb') as stream:
        for row, group in enumerate(groups):
            members[positions[group]] = row
            positions[group] += 1
            stream.write(struct.pack('<IIII', group, preferred[group], offsets[group], counts[group]))
    if sys.byteorder != 'little':
        members.byteswap()
    with member_path.open('wb') as stream:
        members.tofile(stream)
    # Verify every source's navigation and each group's ordered membership.
    with nav_path.open('rb') as stream:
        for row, group in enumerate(groups):
            raw = stream.read(16)
            if len(raw) != 16 or struct.unpack('<IIII', raw) != (group, preferred[group], offsets[group], counts[group]):
                raise ValueError('Navigation changed during publication')
        if stream.read(1):
            raise ValueError('Unexpected navigation bytes')
    with member_path.open('rb') as stream:
        for group, offset in enumerate(offsets):
            stream.seek(offset * 4)
            previous = -1
            for _ in range(counts[group]):
                raw = stream.read(4)
                if len(raw) != 4:
                    raise ValueError('Navigation membership changed during publication')
                row, = struct.unpack('<I', raw)
                if row >= rows or groups[row] != group or row <= previous:
                    raise ValueError('Navigation membership changed during publication')
                previous = row
        if stream.read(1):
            raise ValueError('Unexpected navigation membership bytes')
    return {'detail_navigation': nav_path, 'detail_members': member_path}
