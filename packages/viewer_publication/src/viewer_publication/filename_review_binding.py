"""Bind published assistant reviews to each catalog version by stable identity.

A review publication (reviews.json, pinned by its sha256) records row positions
for the catalog it was exported from. Positions change with every catalog
version, so a publication pinned to positions goes dark after each rebuild.
document-review-identities.json records each review's stable identity instead:
its document_id, member source_ids and stored body_key. Every viewer
publication recomputes positions from those identities and keeps a review only
when its document, members and body are unchanged; anything else is withdrawn
and shows the original catalog category.
"""
import hashlib
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / 'data'
IDENTITIES = DATA_DIR / 'document-review-identities.json'
DESCRIPTOR = DATA_DIR / 'document-review-publication.json'


def validate_identities(value, descriptor=None):
    """Reject ambiguous rows and unpinned input before any binding is emitted."""
    if (not isinstance(value, dict) or value.get('version') != 1
            or not isinstance(value.get('review_sha256'), str)
            or not re.fullmatch('[a-f0-9]{64}', value['review_sha256'])
            or not isinstance(value.get('catalog_id'), str) or not value['catalog_id']
            or not isinstance(value.get('rows'), list)):
        raise ValueError('Unsupported review identity file or missing pins')
    indexes, documents = set(), set()
    for row in value['rows']:
        if (not isinstance(row, dict) or type(row.get('index')) is not int or row['index'] < 0
                or not isinstance(row.get('document_id'), str) or not row['document_id']
                or not isinstance(row.get('body_key'), (str, type(None)))
                or not isinstance(row.get('source_ids'), list) or not row['source_ids']
                or any(not isinstance(source, str) or not source for source in row['source_ids'])
                or len(set(row['source_ids'])) != len(row['source_ids'])):
            raise ValueError('Invalid review identity row')
        if row['index'] in indexes or row['document_id'] in documents:
            raise ValueError('Duplicate review identity index or document')
        indexes.add(row['index']); documents.add(row['document_id'])
    if indexes != set(range(len(value['rows']))):
        raise ValueError('Review identity indexes must be complete')
    if descriptor is not None and (value['review_sha256'] != descriptor['review_sha256']
            or value['catalog_id'] != descriptor['catalog_id'] or len(value['rows']) != descriptor['groups']):
        raise ValueError('Review identity pins differ from publication descriptor')
    return value


def load_identities(path=IDENTITIES, *, descriptor=DESCRIPTOR):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'Required review identity file is missing: {path}')
    identities = json.loads(path.read_text())
    return validate_identities(identities, json.loads(Path(descriptor).read_text()) if descriptor else None)


def bind(catalog, identities):
    """Positions for reviews whose document, members and body are unchanged.

    O(D + sum(k_i log k_i)) for D documents and k_i members of each review:
    reuse positional indexes and compare complete member multisets.
    """
    validate_identities(identities)
    position = getattr(catalog, 'entry_positions', None)
    if position is None:
        position = {entry: index for index, entry in enumerate(catalog.order.to_pylist())}
    entries = getattr(catalog, 'document_id_entries', None)
    if entries is None:
        entries = {key: index for index, key in enumerate(catalog.documents['document_id'].to_pylist())}
    source_ids, body_keys = catalog.table['source_id'], catalog.documents['body_key']
    rows, withdrawn = [], []
    for item in identities['rows']:
        entry = entries.get(item['document_id'])
        reason = withdrawal_reason(exists=entry is not None,
            sources_match=entry is not None and sorted(source_ids[row].as_py() for row in catalog.members[entry]) == sorted(item['source_ids']),
            body_matches=entry is not None and body_keys[entry].as_py() == item['body_key'])
        if reason is None:
            rows.append(dict(index=item['index'], group=position[entry], sources=list(catalog.members[entry])))
            continue
        withdrawn.append(dict(index=item['index'], document_id=item['document_id'], reason=reason))
    return dict(version=1, review_sha256=identities['review_sha256'], catalog_id=catalog.info['catalog_id'],
                rows=rows, withdrawn=withdrawn)


def withdrawal_reason(*, exists, sources_match, body_matches):
    """The maintained document/member/body policy, independent of placement."""
    if not exists:
        return 'document_missing'
    if not sources_match:
        return 'sources_changed'
    if not body_matches:
        return 'body_changed'
    return None


def catalog_source_ids_digest(sorted_source_ids):
    """Hash an ordered unique membership set without retaining another ID list."""
    digest, previous = hashlib.sha256(b'['), None
    for source_id in sorted_source_ids:
        if not isinstance(source_id, str) or previous is not None and source_id <= previous:
            raise ValueError('Catalog membership IDs must be unique sorted strings')
        if previous is not None:
            digest.update(b',')
        digest.update(json.dumps(source_id, ensure_ascii=True, allow_nan=False).encode('utf-8'))
        previous = source_id
    digest.update(b']')
    return digest.hexdigest()


def bind_selected(catalog_id, identities, component_lookup, *, previous=None):
    """Place reviews by stable IDs using retained exact membership proofs."""
    validate_identities(identities)
    prior = {}
    if previous is not None:
        if previous.get('version') not in (1, 2) or previous.get('review_sha256') != identities['review_sha256']:
            raise ValueError('Changed review input requires an explicit new review policy')
        expected = {item['index']: item for item in identities['rows']}
        for item in previous['withdrawn']:
            original = expected.get(item['index'])
            if (original is None or item['index'] in prior or item['document_id'] != original['document_id']
                    or previous['version'] == 2 and item['source_ids'] != original['source_ids']
                    or item['reason'] not in ('document_missing', 'sources_changed', 'body_changed')):
                raise ValueError('Invalid retained review withdrawal')
            prior[item['index']] = dict(item, source_ids=original['source_ids'])
    rows, withdrawn = [], []
    for item in identities['rows']:
        if item['index'] in prior:
            withdrawn.append(dict(prior[item['index']]))
            continue
        component = component_lookup(item['document_id'])
        reason = withdrawal_reason(exists=component is not None,
            sources_match=component is not None and component['source_ids_sha256'] ==
                catalog_source_ids_digest(iter(sorted(item['source_ids']))),
            body_matches=component is not None and component['body_key'] == item['body_key'])
        if reason is None:
            rows.append(dict(index=item['index'], document_id=item['document_id'], source_ids=item['source_ids']))
        else:
            withdrawn.append(dict(index=item['index'], document_id=item['document_id'], reason=reason,
                                  source_ids=item['source_ids']))
    return dict(version=2, review_sha256=identities['review_sha256'], catalog_id=catalog_id,
                rows=rows, withdrawn=withdrawn)


def identities_from(catalog, reviews):
    """Record stable identities from a review publication and its exact catalog."""
    if reviews['catalog_id'] != catalog.info['catalog_id']:
        raise ValueError('The reviews belong to a different catalog')
    order = catalog.order.to_pylist()
    rows = []
    for index, row in enumerate(reviews['rows']):
        entry = order[row['group']]
        members = list(catalog.members[entry])
        if catalog.documents['document_id'][entry].as_py() != row['document_id'] or members != row['sources']:
            raise ValueError(f'Review {index} does not match its catalog positions')
        rows.append(dict(index=index, document_id=row['document_id'], body_key=catalog.documents['body_key'][entry].as_py(),
                         source_ids=sorted(catalog.table['source_id'][member].as_py() for member in members)))
    return dict(version=1, review_sha256=reviews['review_sha256'], catalog_id=reviews['catalog_id'], rows=rows)


def pinned_reviews(path, descriptor):
    data = Path(path).read_bytes()
    if len(data) != descriptor['bytes'] or hashlib.sha256(data).hexdigest() != descriptor['sha256']:
        raise ValueError('Review publication bytes differ from pinned descriptor')
    value = json.loads(data)
    if (value.get('version') != 1 or value.get('review_sha256') != descriptor['review_sha256']
            or value.get('catalog_id') != descriptor['catalog_id'] or len(value.get('rows', [])) != descriptor['groups']):
        raise ValueError('Review publication pins differ from descriptor')
    return value
