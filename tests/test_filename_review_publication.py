from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tarfile

import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'apps/site/scripts'))
from filename_reviews import export_reviews, verify_directory, extract_archive
from test_document_review_search import search_catalog

@pytest.mark.parametrize('unsupported',[False,True])
def test_public_export_preserves_complete_findings_and_exact_evidence(tmp_path,unsupported):
    catalog,_=search_catalog(tmp_path,unsupported)
    target=tmp_path/'public'
    descriptor=export_reviews(catalog,target)
    data=verify_directory(target,descriptor['sha256'])
    row=data['rows'][0]
    source=catalog.preferred_sources[next(iter(catalog.review_classifications))]
    original=catalog.review(source)
    assert row['status']==original['status'] and row['selected']==original['selected']
    for field in ['primary_forms','component_forms']:assert row['review'][field]==original['review'][field]
    for key,value in row['review']['body_observation'].items():
        if not key.endswith('_path'):assert value==original['review']['body_observation'][key]
    for kind,path in row['evidence'].items():
        if kind=='pages':
            for page,name in path.items():assert (target/name).read_bytes()==catalog.review_evidence(source,'page',int(page))[0]
        else:assert (target/path).read_bytes()==catalog.review_evidence(source,kind)[0]
    assert len(row['sources'])==2
    assert '/Users/' not in (target/'reviews.json').read_text()
    archive=tmp_path/'publication.tar.gz'
    with tarfile.open(archive,'w:gz') as bundle:
        for path in target.rglob('*'):
            if path.is_file():bundle.add(path,arcname=str(path.relative_to(target)))
    descriptor['archive_sha256']=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
    assert extract_archive(archive,tmp_path/'restored',descriptor)==data
    path=target/row['evidence']['body'];path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='mismatch'):verify_directory(target,descriptor['sha256'])
    bad=dict(descriptor,archive_sha256='wrong')
    with pytest.raises(ValueError,match='archive digest'):extract_archive(archive,tmp_path/'bad',bad)

@pytest.mark.parametrize('name,type_', [('.. /escape',tarfile.REGTYPE),('reviews.json',tarfile.SYMTYPE)])
def test_archive_refuses_paths_and_links_even_with_a_matching_archive_hash(tmp_path,name,type_):
    import io
    archive=tmp_path/'bad.tar.gz'
    with tarfile.open(archive,'w:gz') as bundle:
        member=tarfile.TarInfo(name);member.type=type_;member.linkname='/tmp/escape'
        if type_==tarfile.REGTYPE:member.size=1;bundle.addfile(member,io.BytesIO(b'x'))
        else:bundle.addfile(member)
    descriptor=dict(archive_sha256=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest(),sha256='unused')
    with pytest.raises(ValueError,match='Invalid review archive member'):extract_archive(archive,tmp_path/'output',descriptor)
