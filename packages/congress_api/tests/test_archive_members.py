"""ZIP members retain occurrence identity and fail within explicit byte limits."""

from io import BytesIO
import struct
import warnings
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from congress_api.retention.archive_members import (
    ArchiveReadError, ZipLimits, iter_zip_members,
)


def archive(entries, compression=ZIP_STORED):
    target = BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with ZipFile(target, 'w', compression=compression) as output:
            for name, body in entries:
                output.writestr(name, body)
    return target.getvalue()


def read(data, **kwargs):
    return list(iter_zip_members(data, archive_path='captures/parent.zip', **kwargs))


def test_members_preserve_names_bytes_and_entry_positions():
    rows = read(archive([('folder/', b''), ('folder/a.xml', b'<a/>'),
                         ('folder/a.xml', b'<b/>'), ('empty', b'')]))
    assert [row.entry_index for row in rows] == [1, 2, 3]
    assert [row.original_name for row in rows] == ['folder/a.xml', 'folder/a.xml', 'empty']
    assert [row.data for row in rows] == [b'<a/>', b'<b/>', b'']
    assert all(row.archive_path == 'captures/parent.zip' and row.status == 'completed'
               for row in rows)


@pytest.mark.parametrize('name', ['../escape.xml', '/absolute', 'C:\\escape',
                                 'safe/../../escape', 'safe\\..\\escape'])
def test_unsafe_names_are_provenance_only(name, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    row, = read(archive([(name, b'raw')]))
    assert row.original_name == name and row.data == b'raw' and row.unsafe_name
    assert list(tmp_path.iterdir()) == []


def test_compressed_bomb_rejected_before_member_open(monkeypatch):
    data = archive([('bomb', b'x' * 100000)], ZIP_DEFLATED)
    def forbidden(*args, **kwargs):
        pytest.fail('oversize declared member must not be decompressed')
    monkeypatch.setattr(ZipFile, 'open', forbidden)
    row, = read(data, limits=ZipLimits(max_member_bytes=100))
    assert row.status == 'member_size_limit' and row.data is None


def test_aggregate_limit_stops_expansion_without_losing_occurrences():
    rows = read(archive([('one', b'1234'), ('two', b'5678'), ('three', b'9')]),
                limits=ZipLimits(max_total_bytes=6))
    assert [row.status for row in rows] == ['completed', 'aggregate_size_limit', 'aggregate_size_limit']
    assert [row.data for row in rows] == [b'1234', None, None]


def test_corrupt_crc_member_explicit_and_next_member_readable():
    data = bytearray(archive([('bad', b'abcdef'), ('good', b'xyz')]))
    name_size, extra_size = struct.unpack_from('<HH', data, 26)
    data[30 + name_size + extra_size] ^= 1
    rows = read(bytes(data))
    assert rows[0].status == 'corrupt_member' and rows[0].data is None
    assert rows[1].data == b'xyz'


@pytest.mark.parametrize(('flag', 'method', 'status'), [
    (1, 0, 'encrypted_member'), (0, 99, 'unsupported_compression'),
])
def test_unreadable_members_have_explicit_results(flag, method, status):
    data = bytearray(archive([('member', b'abc')]))
    central = data.index(b'PK\x01\x02')
    struct.pack_into('<H', data, 6, flag)
    struct.pack_into('<H', data, central + 8, flag)
    struct.pack_into('<H', data, 8, method)
    struct.pack_into('<H', data, central + 10, method)
    row, = read(bytes(data))
    assert row.status == status and row.data is None


def test_nested_archive_retained_without_recursion_and_depth_refused():
    inner = archive([('inside.xml', b'<inside/>')])
    row, = read(archive([('inner.zip', inner)]))
    assert row.data == inner and row.nested_archive
    with pytest.raises(ArchiveReadError) as error:
        read(inner, depth=1)
    assert error.value.status == 'nesting_limit'


@pytest.mark.parametrize(('payload', 'limits', 'status'), [
    (b'broken', ZipLimits(), 'corrupt_archive'),
    (archive([('a', b'a')]), ZipLimits(max_archive_bytes=5), 'archive_size_limit'),
    (archive([('a', b'a'), ('b', b'b')]), ZipLimits(max_members=1), 'member_count_limit'),
    (archive([('a', b'a')]), ZipLimits(max_directory_bytes=5), 'directory_size_limit'),
])
def test_archive_failure_is_explicit(payload, limits, status):
    with pytest.raises(ArchiveReadError) as error:
        read(payload, limits=limits)
    assert error.value.status == status


def test_forged_low_entry_count_cannot_bypass_actual_count_limit():
    data = bytearray(archive([('a', b'a'), ('b', b'b')]))
    end = data.rfind(b'PK\x05\x06')
    struct.pack_into('<HH', data, end + 8, 1, 1)
    with pytest.raises(ArchiveReadError) as error:
        read(bytes(data), limits=ZipLimits(max_members=1))
    assert error.value.status == 'member_count_limit'


def test_empty_zip_and_comment_containing_end_signature_are_valid():
    target = BytesIO()
    with ZipFile(target, 'w') as output:
        output.comment = b'comment PK\x05\x06 not an end record'
    assert read(target.getvalue()) == []


@pytest.mark.parametrize(('field_offset', 'field_format', 'value', 'status'), [
    (10, '<H', 65535, 'unsupported_zip64'),
    (4, '<H', 1, 'unsupported_multidisk'),
])
def test_unsupported_archive_layouts_are_explicit(field_offset, field_format, value, status):
    data = bytearray(archive([('member', b'abc')]))
    end = data.rfind(b'PK\x05\x06')
    struct.pack_into(field_format, data, end + field_offset, value)
    with pytest.raises(ArchiveReadError) as error:
        read(bytes(data))
    assert error.value.status == status


def test_read_is_lazy_and_only_opens_requested_member(monkeypatch):
    data = archive([('one', b'a'), ('two', b'b')])
    opened = []
    real_open = ZipFile.open
    def track(self, member, *args, **kwargs):
        opened.append(member.filename)
        return real_open(self, member, *args, **kwargs)
    monkeypatch.setattr(ZipFile, 'open', track)
    rows = iter_zip_members(data, archive_path='archive')
    assert opened == []
    assert next(rows).data == b'a'
    assert opened == ['one']
    rows.close()


def test_declared_size_cannot_defeat_runtime_expansion_limits(monkeypatch):
    data = archive([('a', b'a'), ('b', b'b')])
    class ForgedStream(BytesIO):
        def __init__(self):
            super().__init__(b'X' * 100)
    monkeypatch.setattr(ZipFile, 'open', lambda *args, **kwargs: ForgedStream())
    rows = read(data, limits=ZipLimits(max_member_bytes=10, max_total_bytes=15))
    assert rows[0].status == 'member_size_limit' and rows[0].data is None
    assert rows[1].status == 'aggregate_size_limit' and rows[1].data is None
