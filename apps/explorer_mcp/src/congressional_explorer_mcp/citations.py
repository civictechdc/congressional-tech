"""Passage identity shared by body reads, hearing captions, and search consumers."""
from hashlib import sha256

from .models import ExplorerError

CITATION_VERSION = 1
TEXT_READER_VERSION = 'archive-body-text-v3'


def caption_source_id(video_key,body_hex,language=None,production=None):
    """Shared identity for a selected caption root, including roots without a meeting."""
    return sha256(f'captions:{video_key}:{body_hex.lower()}:{language or ""}:{production or ""}'.encode()).hexdigest()


def validate_witness_claim(target, witness_key=None, claimed=None):
    """Check an occurrence and attribution against the published source association."""
    witnesses = target.get('witness_keys') or []
    prior = target.get('prior_witness_keys') or []
    if witness_key is not None and witness_key not in witnesses and witness_key not in prior:
        raise ExplorerError('Witness occurrence is not associated with this source')
    attribution = 'source_association' if witness_key else ('ambiguous' if len(witnesses) > 1 else 'unavailable')
    if claimed is not None and claimed != attribution:
        raise ExplorerError('Witness attribution differs from this source association')
    return attribution


def text_citation(target, location, text, witness_key=None):
    """Cite exact returned text at a release/body-bound location, without name matching."""
    reference = target.get('reference') or dict(release_id=target['release_id'], link_key=target['link_key'])
    witnesses = target.get('witness_keys') or []
    if witness_key is None and len(witnesses) == 1:
        witness_key = witnesses[0]
    return dict(version=CITATION_VERSION, source=reference, saved_body=target.get('saved_body'),
                reader_version=target.get('reader_version') or TEXT_READER_VERSION,
                location=location, text_sha256=sha256(text.encode()).hexdigest(),
                witness_key=witness_key,
                witness_attribution=validate_witness_claim(target,witness_key))


def add_body_citations(result, target):
    """A snippet's match is exact; decorative snippet context is not its cited passage."""
    for row in result.get('rows', []):
        text = row.get('match', row.get('text', ''))
        row['citation'] = text_citation(target, dict(kind='body_text', page=row.get('page'),
                                                   offset=row.get('offset', 0), length=len(text)), text)
    if not result.get('query') and result.get('rows'):
        result['citation'] = result['rows'][0]['citation']
    return result
