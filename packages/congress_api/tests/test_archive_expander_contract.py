"""B2 archive fixtures: content only, exact member positions, explicit refusals."""
import io
from pathlib import Path
import zipfile

import pytest


def archive(tmp_path, entries):
    path = tmp_path/'source'
    with zipfile.ZipFile(path,'w') as z:
        for name,data in entries: z.writestr(name,data)
    return path


def test_archive_members_keep_duplicate_names_and_directory_positions(tmp_path):
    from congress_api.retention.archive_expander import expand_archive
    from congress_api.retention.archive_members import ZipLimits
    path = archive(tmp_path,[('directory/',b''),('same.pdf',b'one'),('same.pdf',b'two'),('../bad',b'safe bytes')])
    result = expand_archive(path,directory=tmp_path/'members',limits=ZipLimits())
    assert result.status == 'expanded'
    assert [(m.member_path,m.entry_index,m.body.path.read_bytes()) for m in result.members] == [
        ('same.pdf',1,b'one'),('same.pdf',2,b'two'),('../bad',3,b'safe bytes')]
    assert not (tmp_path/'bad').exists()
    assert all(m.body.media_type is None for m in result.members)


@pytest.mark.parametrize('entries', [[('[Content_Types].xml',b'<Types/>'),('word/document.xml',b'<w/>')],
                                     [('mimetype',b'application/vnd.oasis.opendocument.text'),('content.xml',b'<doc/>')]])
def test_office_content_stays_whole(tmp_path,entries):
    from congress_api.retention.archive_expander import expand_archive
    from congress_api.retention.archive_members import ZipLimits
    result=expand_archive(archive(tmp_path,entries),directory=tmp_path/'members',limits=ZipLimits())
    assert result.status is None and result.members == ()


def test_member_limit_refusal_is_on_container(tmp_path):
    from congress_api.retention.archive_expander import expand_archive
    from congress_api.retention.archive_members import ZipLimits
    result=expand_archive(archive(tmp_path,[('large',b'x'*100)]),directory=tmp_path/'members',
                          limits=ZipLimits(max_member_bytes=10))
    assert result.status=='member_size_limit' and result.members==()


def test_nested_archive_stays_one_member(tmp_path):
    from congress_api.retention.archive_expander import expand_archive
    from congress_api.retention.archive_members import ZipLimits
    result=expand_archive(archive(tmp_path,[('nested.zip',b'PK\x03\x04nested')]),
                          directory=tmp_path/'members',limits=ZipLimits())
    assert result.status=='expanded' and len(result.members)==1


def test_malformed_mapped_zip_keeps_corrupt_refusal_during_cleanup(tmp_path):
    from congress_api.retention.archive_expander import expand_archive
    from congress_api.retention.archive_members import ZipLimits
    from congress_api.retention.sniff import read_sniff_file
    path=archive(tmp_path,[('a',b'x')])
    data=path.read_bytes().replace(b'PK\x01\x02',b'BAD!',1)
    path.write_bytes(data)
    result=expand_archive(path,directory=tmp_path/'members',limits=ZipLimits())
    assert result.status=='corrupt_archive' and result.members==()
    row=read_sniff_file(path)
    assert row['status']=='error' and row['error_type']=='corrupt_archive'


def test_malformed_mapped_rtfd_releases_internal_payload_views(tmp_path):
    import gzip
    from congress_api.retention.archive_expander import expand_archive
    from congress_api.retention.archive_members import ZipLimits
    fixture=Path(__file__).parent/'fixtures/capture-failures/wrapped-letter.rtfd.gz'
    data=bytearray(gzip.decompress(fixture.read_bytes()))
    data[-30]=99  # Reject attributes after the parser has created its payload views.
    path=tmp_path/'source'
    path.write_bytes(data)
    result=expand_archive(path,directory=tmp_path/'members',limits=ZipLimits())
    assert result.status=='corrupt_archive' and result.members==()


@pytest.mark.parametrize('entries',[[],[('member.txt',b'abc')]])
def test_zip_comment_end_signature_uses_the_validated_directory(tmp_path,entries):
    from congress_api.retention.archive_expander import expand_archive
    from congress_api.retention.archive_members import ZipLimits
    path=tmp_path/'source'
    with zipfile.ZipFile(path,'w') as archive:
        archive.comment=b'comment PK\x05\x06 not an end record'
        for name,data in entries:
            archive.writestr(name,data)
    result=expand_archive(path,directory=tmp_path/'members',limits=ZipLimits())
    assert result.status=='expanded'
    assert [(member.member_path,member.body.path.read_bytes()) for member in result.members]==entries
