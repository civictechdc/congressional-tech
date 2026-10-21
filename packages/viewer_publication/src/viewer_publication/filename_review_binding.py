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
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

DEFAULT_DESCRIPTOR_NAME = 'document-review-publication.json'
_UNSET = object()


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


def load_identities(path, *, descriptor=_UNSET):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'Required review identity file is missing: {path}')
    if descriptor is _UNSET:
        descriptor = path.with_name(DEFAULT_DESCRIPTOR_NAME)
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
        if entry is None:
            reason = 'document_missing'
        elif sorted(source_ids[row].as_py() for row in catalog.members[entry]) != sorted(item['source_ids']):
            reason = 'sources_changed'
        elif body_keys[entry].as_py() != item['body_key']:
            reason = 'body_changed'
        else:
            rows.append(dict(index=item['index'], group=position[entry], sources=list(catalog.members[entry])))
            continue
        withdrawn.append(dict(index=item['index'], document_id=item['document_id'], reason=reason))
    return dict(version=1, review_sha256=identities['review_sha256'], catalog_id=catalog.info['catalog_id'],
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


def main():
    parser = argparse.ArgumentParser(description='Record stable review identities from a verified review publication.')
    parser.add_argument('reviews', type=Path, help='reviews.json of the pinned review publication')
    parser.add_argument('filenames', type=Path, help='document-filenames.parquet of the exact catalog the reviews name')
    parser.add_argument('--output', type=Path, default=Path('apps/site/document-review-identities.json'))
    parser.add_argument('--descriptor', type=Path)
    parser.add_argument('--viewer', type=Path, default=Path('docs/youtube-coverage/research/scripts/view_document_filenames.py'))
    args = parser.parse_args()
    descriptor_path = args.descriptor or args.output.with_name(DEFAULT_DESCRIPTOR_NAME)
    spec = importlib.util.spec_from_file_location('filename_viewer', args.viewer)
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    descriptor = json.loads(descriptor_path.read_text())
    reviews = pinned_reviews(args.reviews, descriptor)
    with viewer.Catalog(args.filenames, search_indexes=False) as catalog:
        identities = validate_identities(identities_from(catalog, reviews), descriptor)
        binding = bind(catalog, identities)
    if binding['withdrawn'] or len(binding['rows']) != len(identities['rows']):
        raise ValueError('The recorded identities do not bind back to their own catalog')
    args.output.write_text(json.dumps(identities, indent=1, sort_keys=True) + '\n')
    print(f"{len(identities['rows'])} review identities written to {args.output}")


if __name__ == '__main__':
    main()
