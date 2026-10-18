"""One verified review snapshot for a read-only local viewer."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import weakref

_selections = weakref.WeakValueDictionary()


class ReviewSelection(dict):
    """Optimization for owned, unchanged complete rows; not mutable-row attestation."""

from .document_review_bundle import select_document
from .document_review_portable import load_portable, resolve_evidence
from .document_review_receipts import verified


CLASSIFICATION_FIELDS = ('document_kind', 'document_family', 'document_kind_source')


def _stamp(path):
    stat = Path(path).stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class ReviewSnapshot:
    """Verify once, then select against complete current rows on every use.

    Catalog files must remain immutable for the life of this reader. File identity
    changes require a fresh reader; evidence bytes are rehashed before serving.
    """
    def __init__(self, manifest, pin, sources, documents):
        self.manifest, self.pin = Path(manifest), pin
        self.paths = [Path(sources), Path(documents), self.manifest]
        self.stamps = [_stamp(path) for path in self.paths]
        metadata = json.loads(verified(self.manifest, pin, {}).read_text())
        summary = json.loads(resolve_evidence(self.manifest, pin, metadata['summary_locator']).read_text())
        for role, path in zip(('sources', 'documents'), self.paths):
            verified(path, summary['baseline'][role]['sha256'], {})
        self.candidates = load_portable(self.manifest, pin)
        self.check()

    def check(self):
        if [_stamp(path) for path in self.paths] != self.stamps:
            raise ValueError('The catalog or review snapshot changed. Restart the viewer to verify it again.')

    def classifications(self):
        """Detached search fields already selected against the exact immutable pair."""
        self.check()
        return {key: dict(status=row['status'], **{field: deepcopy(row['document'].get(field))
                    for field in CLASSIFICATION_FIELDS}) for key, row in self.candidates.items()}

    def selection(self, document, sources, *, withdrawn=False):
        self.check()
        reviewed = select_document(document, sources, self.candidates)
        selected = select_document(document, sources) if withdrawn else reviewed
        self.check()
        result = ReviewSelection(status='withdrawn' if withdrawn and reviewed['review'] else reviewed['status'],
                    baseline={key: deepcopy(document.get(key)) for key in CLASSIFICATION_FIELDS},
                    selected={key: selected['document'].get(key) for key in CLASSIFICATION_FIELDS},
                    review=reviewed['review'])
        result.snapshot, result.document, result.sources = self, document, sources
        result.verified_review = deepcopy(reviewed['review'])
        _selections[id(result)] = result
        return result

    def evidence(self, document, sources, kind, page=None, *, selection=None):
        if selection is None:
            selection = self.selection(document, sources)
        if (not isinstance(selection, ReviewSelection) or _selections.get(id(selection)) is not selection
                or selection.snapshot is not self or selection.document is not document or selection.sources is not sources):
            raise ValueError('Review selection does not cover these complete rows')
        self.check()
        review = selection.verified_review
        if review is None:
            raise ValueError('This document has no verified complete-body review.')
        observed = review['body_observation']
        if kind == 'body':
            locator, digest = observed['path'], observed['sha256']
            content_type, signature = 'application/pdf', b'%PDF-'
        elif kind == 'page':
            pages = {int(re.search(r'-(\d+)\.png$', path)[1]): (path, digest)
                     for path, digest in observed['rendered_pages'].items()}
            if page not in pages:
                raise ValueError('Reviewed page does not exist.')
            locator, digest = pages[page]
            content_type, signature = 'image/png', b'\x89PNG\r\n\x1a\n'
        elif kind in {'text', 'native-text'}:
            prefix = 'native_text' if kind == 'native-text' else 'text'
            if prefix + '_path' not in observed:
                raise ValueError('This review has no saved text of that type.')
            locator, digest = observed[prefix + '_path'], observed[prefix + '_sha256']
            content_type, signature = 'text/plain; charset=utf-8', b''
        else:
            raise ValueError('Unknown review evidence type.')
        data = resolve_evidence(self.manifest, self.pin, locator).read_bytes()
        if sha256(data).hexdigest() != digest or not data.startswith(signature):
            raise ValueError('Review evidence bytes or format changed.')
        self.check()
        return data, content_type
