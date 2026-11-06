#!/usr/bin/env python3
"""Prepare reviewed URL identity evidence from one retained ecoi catalog page.

This is an offline preparation step. It performs no acquisition, campaign,
acceptance or import and does not replace the candidate PDF's capture receipt.
"""
import argparse
from datetime import date
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urljoin

from congress_api.retention.provenance import instant
from corpus_recovery.acceptance import identity_source


class CatalogPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.metadata = {}
        self.links = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name', '').startswith('dc.'):
            self.metadata.setdefault(attrs['name'], []).append(attrs.get('content'))
        if tag == 'a' and attrs.get('href'):
            self.links.add(attrs['href'])


def extract_record(raw, *, catalog_url, target_url, candidate_url):
    """Require the catalog's explicit native ID and both literal document URLs."""
    if len(raw) > 1024 * 1024:
        raise ValueError('Catalog page exceeds the 1 MiB preparation limit')
    page = CatalogPage()
    page.feed(raw.decode('utf-8'))

    def one(name):
        values = page.metadata.get(name, [])
        if len(values) != 1 or not isinstance(values[0], str) or not values[0].strip():
            raise ValueError('Catalog needs one explicit ' + name)
        return values[0].strip()

    identifier = one('dc.identifier')
    if not re.fullmatch(r'[0-9]+', identifier) or catalog_url != f'https://www.ecoi.net/en/document/{identifier}.html':
        raise ValueError('Catalog identifier does not match its source URL')
    if one('dc.source') != target_url:
        raise ValueError('Catalog does not name the literal original URL')
    if not candidate_url.startswith(f'https://www.ecoi.net/en/file/local/{identifier}/'):
        raise ValueError('Candidate is outside this catalog record')
    links = {urljoin(catalog_url, link) for link in page.links}
    if not {target_url, candidate_url}.issubset(links):
        raise ValueError('Catalog does not explicitly link both document URLs')
    published = one('dc.date')
    if date.fromisoformat(published).isoformat() != published:
        raise ValueError('Catalog date must be a literal complete ISO date')
    return dict(document=identifier, title=one('dc.title'), date=published,
                original_url=target_url, candidate_url=candidate_url)


def prepare(catalog_path, *, catalog_url, target_url, candidate_url,
            reviewed_by, reviewed_at, output):
    instant(reviewed_at)
    if not reviewed_by.strip():
        raise ValueError('A named reviewer is required')
    catalog_path = Path(catalog_path).resolve()
    # Bound the read itself, not just the parsed result.
    with catalog_path.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    record = extract_record(raw, catalog_url=catalog_url, target_url=target_url,
                            candidate_url=candidate_url)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    metadata_path = output / 'identity-metadata.json'
    metadata = dict(
        authority='ecoi.net catalog; identifier is not issued by USAID',
        evidence_basis='one catalog record explicitly links the original and mirror URLs',
        raw_source=dict(path=str(catalog_path), sha256=sha256(raw).hexdigest()),
        source_url=catalog_url, extraction='dc.identifier, dc.source, dc.title, dc.date and explicit anchor hrefs',
        record=record)
    metadata_raw = (json.dumps(metadata, indent=2, ensure_ascii=False) + '\n').encode()
    with metadata_path.open('xb') as stream:
        stream.write(metadata_raw)
    source = dict(source=dict(path=str(metadata_path.resolve()), sha256=sha256(metadata_raw).hexdigest()),
                  source_url=catalog_url, reviewed_by=reviewed_by, reviewed_at=reviewed_at,
                  record_pointer='/record', identifier_fields={name:name for name in ('document', 'date', 'title')},
                  required_fields=['document', 'date', 'title'])
    specs = dict(target=dict(source, url_field='original_url'),
                 candidate=dict(source, url_field='candidate_url'))
    facts = {name:identity_source(spec, output) for name, spec in specs.items()}
    result = dict(
        source_identity_status='supported_by_reviewed_catalog_record',
        acceptance_status='review_required',
        reason='candidate_capture_receipt_missing',
        import_status='not_performed',
        attribution_limit='Use source_catalog_document_identifier: this ID belongs to the ecoi.net catalog, not the original publisher.',
        identity_sources=specs, extracted_facts=facts)
    with (output / 'identity-review.json').open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--catalog-url', required=True)
    parser.add_argument('--target-url', required=True)
    parser.add_argument('--candidate-url', required=True)
    parser.add_argument('--reviewed-by', required=True)
    parser.add_argument('--reviewed-at', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.catalog, catalog_url=args.catalog_url, target_url=args.target_url,
                     candidate_url=args.candidate_url, reviewed_by=args.reviewed_by,
                     reviewed_at=args.reviewed_at, output=args.output)
    print(json.dumps({key:result[key] for key in ('source_identity_status', 'acceptance_status', 'import_status')}))


if __name__ == '__main__':
    main()
