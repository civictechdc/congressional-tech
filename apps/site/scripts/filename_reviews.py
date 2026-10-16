"""Export verified assistant reviews for the public viewer without catalog mutation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tarfile

FIELDS = ('document_kind', 'document_family', 'document_kind_source')


def export_reviews(catalog, target):
    """Require the maintained complete-bundle verifier before publishing any row."""
    if catalog.review_error or not catalog.review_snapshot:
        raise ValueError(catalog.review_error or 'No verified review snapshot')
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    (target/'evidence').mkdir()
    position = {entry: group for group, entry in enumerate(catalog.order.to_pylist())}
    rows, files = [], {}
    def save(data, suffix):
        digest = hashlib.sha256(data).hexdigest()
        name = f'evidence/{digest}.{suffix}'
        if name not in files:
            (target/name).write_bytes(data)
            files[name] = dict(sha256=digest, bytes=len(data))
        return name
    for entry in sorted(catalog.review_classifications):
        source = catalog.preferred_sources[entry]
        document, members = catalog.review_rows(source)
        result = catalog.review_snapshot.selection(document, members)
        observed = result['review']['body_observation']
        links = {}
        for kind, suffix, field in [('body','pdf','path'),('text','txt','text_path'),('native-text','txt','native_text_path')]:
            if field in observed:
                data, _ = catalog.review_snapshot.evidence(document, members, kind)
                links[kind] = save(data, suffix)
        links['pages'] = {}
        for page in range(1, observed['pages']+1):
            data, _ = catalog.review_snapshot.evidence(document, members, 'page', page)
            links['pages'][str(page)] = save(data, 'png')
        # Publish the complete observations and section boundaries, with public
        # evidence locators replacing machine-specific receipt and file paths.
        public_observed = {key: deepcopy(value) for key, value in observed.items() if key in
            {'pages','sha256','notes','observations','source_completeness_observations','page_sections'}}
        for kind, field in [('text','text_path'),('native-text','native_text_path')]:
            if kind in links: public_observed[field] = links[kind]
        review = {key: deepcopy(result['review'][key]) for key in ('primary_forms','component_forms')}
        review['body_observation'] = public_observed
        rows.append(dict(group=position[entry], sources=catalog.members[entry], document_id=document['document_id'],
            status=result['status'], baseline=result['baseline'], selected=result['selected'], review=review, evidence=links))
    catalog.review_snapshot.check()
    value = dict(version=1, catalog_id=catalog.info['catalog_id'], review_sha256=catalog.review_snapshot.pin,
        baseline={name: hashlib.file_digest(path.open('rb'),'sha256').hexdigest() for name,path in
                  [('filenames',catalog.path),('documents',catalog.document_path)]},
        rows=rows, files=files, independent_reference=False, automatic_classifier_approved=False)
    data = (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
    (target/'reviews.json').write_bytes(data)
    return dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), groups=len(rows),
                evidence_files=len(files), evidence_bytes=sum(row['bytes'] for row in files.values()))


def verify_directory(root, expected):
    root=Path(root)
    data=(root/'reviews.json').read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected: raise ValueError('Review publication digest mismatch')
    value=json.loads(data)
    for name, item in value['files'].items():
        if not re.fullmatch(r'evidence/[a-f0-9]{64}\.(pdf|png|txt)',name): raise ValueError('Invalid evidence path')
        path=root/name
        if path.is_symlink() or path.stat().st_size!=item['bytes']:
            raise ValueError('Review evidence size mismatch')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=item['sha256']:
                raise ValueError('Review evidence digest mismatch')
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    if actual!=set(value['files'])|{'reviews.json'}: raise ValueError('Unexpected review publication files')
    return value


def extract_archive(archive, target, descriptor):
    archive, target=Path(archive),Path(target)
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=descriptor['archive_sha256']:
            raise ValueError('Review archive digest mismatch')
    target.mkdir(parents=True,exist_ok=False)
    with tarfile.open(archive,'r:gz') as bundle:
        for member in bundle:
            if not member.isfile() or not re.fullmatch(r'reviews.json|evidence/[a-f0-9]{64}\.(pdf|png|txt)',member.name):
                raise ValueError('Invalid review archive member')
            path=target/member.name
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as out, bundle.extractfile(member) as source:
                import shutil
                shutil.copyfileobj(source,out)
    return verify_directory(target,descriptor['sha256'])


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('descriptor',type=Path)
    parser.add_argument('archive',type=Path)
    parser.add_argument('target',type=Path)
    args=parser.parse_args()
    value=extract_archive(args.archive,args.target,json.loads(args.descriptor.read_text()))
    print(f"Verified {len(value['rows'])} reviews and {len(value['files'])} evidence files")
