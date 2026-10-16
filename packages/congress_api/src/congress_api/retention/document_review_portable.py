"""Export verified review evidence without rewriting its original locator text."""
import argparse
import json
from pathlib import Path
import re
import shutil

from . import document_review_bundle
from .document_review_receipts import file_digest, verified


def _reader_policy():
    return {Path(path).name:file_digest(path) for path in [__file__,document_review_bundle.__file__]}


def _add_binding(bindings, locator, digest):
    locator = str(locator)
    if locator in bindings and bindings[locator] != digest:
        raise ValueError('Conflicting portable evidence locator')
    bindings[locator] = digest


class _EvidenceFiles:
    def __init__(self, manifest_path, expected):
        self.manifest_path = verified(manifest_path,expected,{})
        self.expected = expected
        self.root = self.manifest_path.parent.resolve()
        manifest = json.loads(self.manifest_path.read_text())
        if type(manifest.get('portable_version')) is not int or manifest['portable_version'] != 1:
            raise ValueError('Unsupported portable evidence version')
        self.policy = _reader_policy()
        if manifest['reader_policy'] != self.policy:
            raise ValueError('Portable review reader implementation changed')
        self.locators = manifest['locators']
        if not isinstance(self.locators,dict) or any(not isinstance(k,str) or not isinstance(v,str)
                or not re.fullmatch(r'[0-9a-f]{64}',v) for k,v in self.locators.items()):
            raise ValueError('Invalid portable evidence locators')
        self.summary_locator = manifest['summary_locator']
        self.summary_sha256 = self.locators[self.summary_locator]
        self.summary = json.loads(self.verified_path(self.summary_locator).read_text())
        required = dict(self.summary['bindings'])
        _add_binding(required,self.summary_locator,self.summary_sha256)
        _add_binding(required,Path(self.summary_locator).parent/'candidates.jsonl',
                     self.summary['outputs']['candidates.jsonl'])
        if self.locators != required:
            raise ValueError('Portable evidence does not match the complete admission bindings')

    def path(self, locator):
        """Resolve only recorded objects; never fall back to an original path."""
        digest = self.locators.get(str(locator))
        if digest is None:
            raise ValueError('Unbound portable evidence locator')
        path = self.root/'objects'/digest
        if not path.resolve().is_relative_to(self.root/'objects') or not path.is_file():
            raise ValueError('Portable evidence object is missing or outside the store')
        return path

    def verified_path(self, locator):
        return verified(self.path(locator),self.locators[str(locator)],{})

    def recheck(self):
        verified(self.manifest_path,self.expected,{})
        if _reader_policy() != self.policy:
            raise ValueError('Portable review reader changed during verification')


def export_bundle(summary_path, summary_sha256, sources, documents, output):
    """Copy a verified local bundle and every bound file into a new object store."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    policy = _reader_policy()
    document_review_bundle.load_bundle(summary_path,summary_sha256,sources,documents)
    summary_path = verified(summary_path,summary_sha256,{})
    summary = json.loads(summary_path.read_text())
    locators = dict(summary['bindings'])
    _add_binding(locators,summary_path,summary_sha256)
    _add_binding(locators,summary_path.parent/'candidates.jsonl',summary['outputs']['candidates.jsonl'])
    objects = output/'objects'
    objects.mkdir(parents=True)
    for locator,digest in locators.items():
        source = verified(locator,digest,{})
        target = objects/digest
        if not target.exists():
            with source.open('rb') as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming,outgoing,length=1024*1024)
        verified(target,digest,{})
    if _reader_policy() != policy:
        raise ValueError('Portable review reader changed during export')
    manifest = dict(portable_version=1,summary_locator=str(summary_path),locators=locators,reader_policy=policy)
    # The manifest is the completion marker. Never reuse partial export directories.
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def load_portable(manifest_path, manifest_sha256):
    """Verify a relocated store and return the same detached candidate mapping."""
    files = _EvidenceFiles(manifest_path,manifest_sha256)
    sources,documents = [files.path(files.summary['baseline'][role]['path']) for role in ['sources','documents']]
    result = document_review_bundle._load_bundle(files.summary_locator,files.summary_sha256,sources,documents,
                                                resolve=files.path,portable=True)
    files.recheck()
    return result


def resolve_evidence(manifest_path, manifest_sha256, locator):
    """Return one verified local object for an unchanged original locator string."""
    files = _EvidenceFiles(manifest_path,manifest_sha256)
    path = files.verified_path(locator)
    files.recheck()
    return path


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['summary','summary-sha256','sources','documents','output']:
        parser.add_argument('--'+name,required=True)
    args = parser.parse_args()
    export_bundle(args.summary,args.summary_sha256,args.sources,args.documents,args.output)
    manifest = Path(args.output)/'manifest.json'
    print(json.dumps(dict(manifest=str(manifest),sha256=file_digest(manifest))))
