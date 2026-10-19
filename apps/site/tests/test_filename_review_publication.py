from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tarfile

import pytest
sys.path.insert(0,str(Path(__file__).parents[3]/'apps/site/scripts'))
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


def test_staging_preserves_verified_tree_after_interruption_and_retries(tmp_path, monkeypatch):
    import filename_reviews
    catalog, _ = search_catalog(tmp_path, False)
    target = tmp_path / 'public'
    descriptor = export_reviews(catalog, target)
    original = (target / 'reviews.json').read_bytes()
    archive = tmp_path / 'publication.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in target.rglob('*'):
            if path.is_file(): bundle.add(path, arcname=str(path.relative_to(target)))
    with archive.open('rb') as stream:
        descriptor['archive_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    copy = filename_reviews.shutil.copyfileobj
    monkeypatch.setattr(filename_reviews.shutil, 'copyfileobj', lambda *a: (_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError, match='interrupted'):
        extract_archive(archive, target, descriptor)
    assert (target / 'reviews.json').read_bytes() == original
    assert not list(tmp_path.glob('.public-*'))
    monkeypatch.setattr(filename_reviews.shutil, 'copyfileobj', copy)
    # An incomplete cache can be repaired with the pinned archive.
    (target / 'reviews.json').write_bytes(b'partial')
    extract_archive(archive, target, descriptor)
    assert (target / 'reviews.json').read_bytes() == original
    assert verify_directory(target, descriptor['sha256'])


def test_staging_recovers_install_failure_and_process_death_gap(tmp_path, monkeypatch):
    import filename_reviews
    catalog, _ = search_catalog(tmp_path, False)
    target = tmp_path / 'public'
    descriptor = export_reviews(catalog, target)
    original = (target / 'reviews.json').read_bytes()
    archive = tmp_path / 'publication.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in target.rglob('*'):
            if path.is_file(): bundle.add(path, arcname=str(path.relative_to(target)))
    with archive.open('rb') as stream:
        descriptor['archive_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    replace = filename_reviews.os.replace
    def fail_install(source, destination):
        if Path(source).name == 'verified': raise OSError('install interrupted')
        return replace(source, destination)
    monkeypatch.setattr(filename_reviews.os, 'replace', fail_install)
    with pytest.raises(OSError, match='install interrupted'):
        extract_archive(archive, target, descriptor)
    assert (target / 'reviews.json').read_bytes() == original
    monkeypatch.setattr(filename_reviews.os, 'replace', replace)
    # Model SIGKILL after the first rename; no Python exception handler runs.
    previous = target.with_name('.public.previous')
    replace(target, previous)
    filename_reviews.recover_directory(target)
    assert (target / 'reviews.json').read_bytes() == original
    extract_archive(archive, target, descriptor)
    assert not previous.exists()


def test_changed_descriptor_installs_only_fully_verified_replacement(tmp_path):
    catalog, _ = search_catalog(tmp_path, False)
    target = tmp_path / 'public'; descriptor = export_reviews(catalog, target)
    original = (target / 'reviews.json').read_bytes()
    replacement = tmp_path / 'replacement'; export_reviews(catalog, replacement)
    value = json.loads((replacement / 'reviews.json').read_bytes())
    value['independent_reference'] = 'replacement fixture'
    new_bytes = json.dumps(value).encode(); (replacement / 'reviews.json').write_bytes(new_bytes)
    archive = tmp_path / 'replacement.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in replacement.rglob('*'):
            if path.is_file(): bundle.add(path, arcname=str(path.relative_to(replacement)))
    with archive.open('rb') as stream:
        new_descriptor = {**descriptor, 'archive_sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    with pytest.raises(ValueError, match='digest mismatch'):
        extract_archive(archive, target, new_descriptor)
    assert (target / 'reviews.json').read_bytes() == original
    new_descriptor['sha256'] = hashlib.sha256(new_bytes).hexdigest()
    extract_archive(archive, target, new_descriptor)
    assert (target / 'reviews.json').read_bytes() == new_bytes


def test_consecutive_install_interruptions_preserve_newest_current_tree(tmp_path, monkeypatch):
    import filename_reviews
    catalog, _ = search_catalog(tmp_path, False)
    target = tmp_path / 'public'; descriptor = export_reviews(catalog, target)
    original = (target / 'reviews.json').read_bytes()
    previous = target.with_name('.public.previous')
    __import__('shutil').copytree(target, previous)
    (previous / 'reviews.json').write_bytes(b'old generation A')
    archive = tmp_path / 'publication.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for path in target.rglob('*'):
            if path.is_file(): bundle.add(path, arcname=str(path.relative_to(target)))
    with archive.open('rb') as stream:
        descriptor['archive_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    replace = filename_reviews.os.replace
    def fail_install_and_restore(source, destination):
        if Path(source).name in ('verified', '.public.previous'):
            raise OSError('process interrupted')
        return replace(source, destination)
    monkeypatch.setattr(filename_reviews.os, 'replace', fail_install_and_restore)
    with pytest.raises(OSError, match='process interrupted'):
        extract_archive(archive, target, descriptor)
    assert not target.exists()
    assert (previous / 'reviews.json').read_bytes() == original
    monkeypatch.setattr(filename_reviews.os, 'replace', replace)
    filename_reviews.recover_directory(target)
    assert (target / 'reviews.json').read_bytes() == original


def test_review_export_batches_complete_rows_and_reuses_selection_across_pages(tmp_path, monkeypatch):
    catalog, _ = search_catalog(tmp_path, False, pages=3)
    reads = []
    class Reader:
        def __init__(self, wrapped, kind): self.wrapped, self.kind = wrapped, kind
        def read_row_group(self, group):
            reads.append((self.kind, group)); return self.wrapped.read_row_group(group)
    catalog.file = Reader(catalog.file, 'source')
    catalog.document_file = Reader(catalog.document_file, 'document')
    original = catalog.review_snapshot.selection
    selections = []
    def selection(*args, **kwargs):
        selections.append(True); return original(*args, **kwargs)
    monkeypatch.setattr(catalog.review_snapshot, 'selection', selection)
    descriptor = export_reviews(catalog, tmp_path / 'export')
    exported = verify_directory(tmp_path / 'export', descriptor['sha256'])
    assert len(exported['rows'][0]['sources']) == 2
    assert len(exported['rows'][0]['evidence']['pages']) == 3
    assert reads == [('document', 0), ('source', 0)]
    assert len(selections) == 1
    assert catalog._complete_group_bytes <= catalog.row_group_budget
    catalog.close()
    assert not catalog._complete_groups
