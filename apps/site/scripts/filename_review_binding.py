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
import importlib.util
import json
from pathlib import Path

IDENTITIES = Path(__file__).resolve().parents[1] / 'document-review-identities.json'


def load_identities(path=IDENTITIES):
    path = Path(path)
    if not path.is_file():
        return None
    identities = json.loads(path.read_text())
    if identities.get('version') != 1 or not identities.get('review_sha256'):
        raise ValueError('Unsupported review identity file')
    return identities


def bind(catalog, identities):
    """Positions for reviews whose document, members and body are unchanged.

    O(D + S + R) for D documents, S source rows and R reviewed sources: one
    document_id index, then constant work per reviewed member.
    """
    position = {entry: index for index, entry in enumerate(catalog.order.to_pylist())}
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


def main():
    parser = argparse.ArgumentParser(description='Record stable review identities from a verified review publication.')
    parser.add_argument('reviews', type=Path, help='reviews.json of the pinned review publication')
    parser.add_argument('filenames', type=Path, help='document-filenames.parquet of the exact catalog the reviews name')
    parser.add_argument('--output', type=Path, default=IDENTITIES)
    args = parser.parse_args()
    viewer_path = Path(__file__).resolve().parents[3] / 'docs/youtube-coverage/research/scripts/view_document_filenames.py'
    spec = importlib.util.spec_from_file_location('filename_viewer', viewer_path)
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    catalog = viewer.Catalog(args.filenames)
    identities = identities_from(catalog, json.loads(args.reviews.read_text()))
    binding = bind(catalog, identities)
    if binding['withdrawn'] or len(binding['rows']) != len(identities['rows']):
        raise ValueError('The recorded identities do not bind back to their own catalog')
    args.output.write_text(json.dumps(identities, indent=1, sort_keys=True) + '\n')
    print(f"{len(identities['rows'])} review identities written to {args.output}")


if __name__ == '__main__':
    main()
