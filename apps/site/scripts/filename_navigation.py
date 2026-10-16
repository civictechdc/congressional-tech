"""Range-readable navigation: one 16-byte record and one group membership slice."""
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
    navigation = bytearray(rows * 16)
    for row, group in enumerate(groups):
        members[positions[group]] = row
        positions[group] += 1
        struct.pack_into('<IIII', navigation, row * 16, group, preferred[group], offsets[group], counts[group])
    if sys.byteorder != 'little':
        members.byteswap()
    nav_path, member_path = output / 'detail-navigation.bin', output / 'detail-members.bin'
    nav_path.write_bytes(navigation)
    member_path.write_bytes(members.tobytes())
    # Verify every source's navigation and each group's ordered membership.
    packed = nav_path.read_bytes()
    restored = array('I')
    restored.frombytes(member_path.read_bytes())
    if sys.byteorder != 'little':
        restored.byteswap()
    for row, group in enumerate(groups):
        if struct.unpack_from('<IIII', packed, row * 16) != (group, preferred[group], offsets[group], counts[group]):
            raise ValueError('Navigation changed during publication')
    for group, offset in enumerate(offsets):
        subset = restored[offset:offset + counts[group]]
        if any(groups[row] != group for row in subset) or any(a >= b for a, b in zip(subset, subset[1:])):
            raise ValueError('Navigation membership changed during publication')
    return {'detail_navigation': nav_path, 'detail_members': member_path}
