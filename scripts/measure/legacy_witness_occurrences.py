"""Account for frozen legacy witness records without merging people or roles.

This is a preservation ledger, not a replacement witness parser or release gate.
Every CSV record keeps its full fields and digest/record-number identity. Matching
requires the original source scope and every populated role field; event/name
matches alone are only leads. Ambiguous records remain ambiguous. No network I/O.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import duckdb

FILES = ('meeting_witnesses.csv', 'house_witnesses_found.csv', 'senate_witnesses_found.csv')
SOURCES = {'docs.house.gov': 'house_xml', 'senate committee page': 'senate_page', 'gpo': 'mods'}
FIELDS = {'position': 'position', 'organization': 'organization', 'panel': 'panel',
          'behalf_of': 'on_behalf_of', 'location': 'location', 'witness_type': 'witness_type',
          'bioguide_id': 'bioguide_id'}


def digest(path):
    with Path(path).open('rb') as stream:
        return sha256(stream.read()).hexdigest()


def text(value):
    # Preserve punctuation, accents, honorifics, and case. This is whitespace only.
    return ' '.join((value or '').split())


def load_legacy(data, pins):
    records = []
    for filename in FILES:
        body = (data / filename).read_bytes()
        actual = sha256(body).hexdigest()
        if actual != pins[filename]:
            raise ValueError(f'Frozen input changed: {filename}')
        for ordinal, row in enumerate(csv.DictReader(io.StringIO(body.decode('utf-8'))), 1):
            family = (row.get('source') if filename == FILES[0] else
                      'docs.house.gov' if filename == FILES[1] else 'senate committee page')
            records.append(dict(record_id=f'{filename}:{actual}:{ordinal}', file=filename, record_number=ordinal,
                                fields=row, source=SOURCES.get(family),
                                origin=row.get('from') or row.get('page')))
    return records


def scope(record):
    source, row = record['source'], record['fields']
    if source == 'house_xml':
        return source, row['event_id']
    if source == 'mods':
        return source, record['origin']
    if source == 'senate_page':
        return source, record['origin']
    return None


def native_scope(row):
    source = row['source']
    value = (str(row['event_id']) if row['event_id'] is not None else None) if source == 'house_xml' else (
        row['package_id'] if source == 'mods' else row['page_url'])
    return source, value


def agrees(record, row):
    legacy = record['fields']
    participation = legacy.get('testified')
    # The additional oath fact has no native boolean representation. Keep it
    # unresolved instead of declaring a complete field match from the boolean.
    if participation and (participation not in ('Yes', 'No') or
                          row.get('testified') is not (participation == 'Yes')):
        return False
    return text(legacy['name']) == text(row['name']) and all(
        not text(legacy.get(old)) or text(legacy[old]) == text(row.get(new))
        for old, new in FIELDS.items())


def disposition(record, candidates):
    """Never choose an arbitrary occurrence or infer a source failure from absence."""
    matches = [row for row in candidates if agrees(record, row)]
    owner = 'ct-kthe' if record['source'] == 'senate_page' else 'ct-x78c'
    if record['source'] is None:
        status = 'legacy_title_or_document_requires_source_read'
    elif not matches:
        status = ('source_fields_differ' if candidates else 'no_selected_same_name_source_occurrence')
    elif len(matches) > 1:
        status = 'ambiguous_source_occurrence'
    elif str(matches[0]['event_id']) != record['fields']['event_id']:
        status = 'retained_without_legacy_event_binding'
    elif matches[0]['superseded_by'] is not None:
        status = 'candidate_historical_field_match'
    else:
        status = 'candidate_active_field_match'
    return dict(status=status, owner=owner, matched_keys=[row['witness_key'] for row in matches],
                candidate_keys=[row['witness_key'] for row in candidates])


class HouseEvidence:
    """Read each selected House source once, retaining literal source document types."""
    def __init__(self, mirror):
        self.mirror = mirror
        self.cache = {}
        self.bytes_read = 0

    def read(self, body_sha):
        if body_sha in self.cache:
            return self.cache[body_sha]
        base = self.mirror / 'bodies/sha256' / body_sha[:2] / body_sha
        path = next((p for p in (base.with_suffix('.gz'), base) if p.is_file()), None)
        if path is None:
            result = dict(state='not_located_in_local_mirror', occurrences={})
        else:
            stored = path.read_bytes()
            raw = gzip.decompress(stored) if path.suffix == '.gz' else stored
            self.bytes_read += len(raw)
            if sha256(raw).hexdigest() != body_sha:
                raise ValueError(f'Corrupt retained source: {body_sha}')
            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                result = dict(state='read_unusable_xml', occurrences={})
            else:
                occurrences = {}
                for panel_no, panel in enumerate(root.findall('.//panel'), 1):
                    for witness_no, witness in enumerate(panel.findall('witness'), 1):
                        locator = f'house_xml:panel[{panel_no}]/witness[{witness_no}]'
                        occurrences[locator] = dict(
                            name_fields={tag: witness.findtext(tag) for tag in
                                         ('honorific', 'firstname', 'middlename', 'lastname', 'suffix')},
                            removed=witness.get('remove-date'),
                            position=witness.findtext('position'), organization=witness.findtext('organization'),
                            on_behalf_of=witness.findtext('behalf-of'),
                            documents=[dict(url=f.get('doc-url'), type=doc.findtext('type'),
                                            format=f.get('doc-type'))
                                       for doc in witness.findall('witness-documents/witness-document')
                                       for f in doc.findall('.//file') if f.get('doc-url')])
                result = dict(state='read', occurrences=occurrences)
        self.cache[body_sha] = result
        return result

    def occurrence(self, row):
        evidence = self.read(row['record_sha'])
        occurrence = evidence['occurrences'].get(row['source_locator'])
        return dict(state=(evidence['state'] if evidence['state'] != 'read' else
                           'read_locator_found' if occurrence else 'read_locator_absent'),
                    literal=occurrence)


def verify_asset(release, manifest, name):
    pin = next(item for item in manifest['files'] if item['name'] == name)
    path = release / name
    if path.stat().st_size != pin['size'] or digest(path) != pin['sha256']:
        raise ValueError(f'Candidate asset differs from manifest: {name}')
    return dict(path=str(path), size=pin['size'], sha256=pin['sha256'])


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    pins = json.loads(args.frozen_ledger.read_text())['input_sha256']
    records = load_legacy(args.data, pins)
    manifest = json.loads((args.release / 'manifest.json').read_text())
    assets = {name: verify_asset(args.release, manifest, name)
              for name in ('witnesses.parquet', 'list.parquet', 'sources.parquet')}
    wanted = {scope(record) for record in records if record['source']}
    by_scope = defaultdict(list)
    with duckdb.connect(config={'threads': 1, 'memory_limit': '256MB'}) as db:
        result = db.execute('SELECT * FROM read_parquet(?) ORDER BY witness_key',
                            [str(args.release / 'witnesses.parquet')])
        columns = [col[0] for col in result.description]
        native_count = 0
        for values in result.fetchall():
            native_count += 1
            row = dict(zip(columns, values))
            if native_scope(row) in wanted:
                row['record_sha'] = row['record_sha'].hex()
                by_scope[native_scope(row)].append(row)
        # Exported source addresses and occurrence-specific witness annotations.
        db.execute('CREATE TEMP TABLE wanted_keys(key VARCHAR)')
        selected = [r for group in by_scope.values() for r in group]
        db.executemany('INSERT INTO wanted_keys VALUES (?)', [(r['witness_key'],) for r in selected])
        documents = defaultdict(list)
        query = '''WITH docs AS (
          SELECT file_row_number AS list_row,filename,hidden,unnest(witness_keys) AS witness_key
          FROM read_parquet(?,file_row_number=true))
          SELECT d.witness_key,d.list_row,d.filename,d.hidden,s.url
          FROM docs d JOIN wanted_keys k ON k.key=d.witness_key
          LEFT JOIN read_parquet(?) s ON s.list_row=d.list_row
          ORDER BY d.witness_key,d.list_row,s.url'''
        for key, list_row, filename, hidden, url in db.execute(query, [
                str(args.release / 'list.parquet'), str(args.release / 'sources.parquet')]).fetchall():
            documents[key].append(dict(list_row=list_row, filename=filename, hidden=hidden, url=url))
    house = HouseEvidence(args.mirror)
    claimed = defaultdict(list)
    outcomes, raw_states = Counter(), Counter()
    ledger = []
    for record in records:
        candidates = by_scope.get(scope(record), [])
        # Only same-source, same-origin, same-name leads are exposed as candidates.
        candidates = [r for r in candidates if text(r['name']) == text(record['fields']['name'])]
        result = disposition(record, candidates)
        result.update(record)
        for key in result['matched_keys']:
            claimed[key].append(record['record_id'])
        outcomes[result['status']] += 1
        ledger.append(result)
    repeated_claims = defaultdict(list)
    for record in ledger:
        if len(record['matched_keys']) == 1:
            repeated_claims[(record['file'], record['matched_keys'][0])].append(record)
    for claims in repeated_claims.values():
        if len(claims) > 1:
            for record in claims:
                outcomes[record['status']] -= 1
                record.update(status='repeated_input_occurrence_requires_review', owner='ct-x78c')
                outcomes[record['status']] += 1
    occurrences = []
    for row in selected:
        raw = (house.occurrence(row) if row['source'] == 'house_xml' else
               dict(state='not_read_in_this_audit', literal=None))
        raw_states[raw['state']] += 1
        docs = documents[row['witness_key']]
        source_links = (raw['literal'] or {}).get('documents', [])
        linked = {d['url'] for d in docs if not d['hidden']}
        missing = [doc for doc in source_links if doc['url'] not in linked]
        literal = raw['literal']
        source_urls = {doc['url'] for doc in source_links}
        document_rows = {doc['list_row'] for doc in docs if not doc['hidden']}
        supported_rows = {doc['list_row'] for doc in docs if doc['url'] in source_urls}
        # A document may carry several source URLs (including a shared edition).
        # One matching source URL supports that row; unrelated rows need review.
        extra_document_rows = sorted(document_rows - supported_rows) if literal else None
        differences = ([field for field in ('position', 'organization', 'on_behalf_of')
                        if text(literal[field]) != text(row[field])] if literal else [])
        if literal and literal['removed'] and row['superseded_by'] is None:
            differences.append('removed_source_marked_active')
        occurrences.append(dict(**row, legacy_record_ids=claimed[row['witness_key']],
                                raw=raw, raw_field_differences=differences,
                                published_documents=docs, source_links_not_exactly_linked=missing,
                                published_document_rows_without_source_link=extra_document_rows))
    occurrence_by_key = {row['witness_key']: row for row in occurrences}
    for record in ledger:
        record['raw_evidence'] = {key: occurrence_by_key[key]['raw']['state'] for key in record['matched_keys']}
        record['source_links_not_exactly_linked'] = {
            key: occurrence_by_key[key]['source_links_not_exactly_linked'] for key in record['matched_keys']
            if occurrence_by_key[key]['source_links_not_exactly_linked']}
        record['link_review_owner'] = 'ct-x78c' if record['source_links_not_exactly_linked'] else None
        record['raw_field_differences'] = {
            key: occurrence_by_key[key]['raw_field_differences'] for key in record['matched_keys']
            if occurrence_by_key[key]['raw_field_differences']}
        record['document_rows_requiring_source_review'] = {
            key: occurrence_by_key[key]['published_document_rows_without_source_link'] for key in record['matched_keys']
            if occurrence_by_key[key]['published_document_rows_without_source_link']}
        if record['document_rows_requiring_source_review']:
            record['link_review_owner'] = 'ct-x78c'
    selected_locators = {(row['record_sha'], row['source_locator']) for row in selected if row['source'] == 'house_xml'}
    raw_not_selected = [dict(record_sha=body_sha, source_locator=locator, removed=literal['removed'])
                        for body_sha, evidence in house.cache.items()
                        for locator, literal in evidence['occurrences'].items()
                        if (body_sha, locator) not in selected_locators]
    write_json(args.output / 'raw-house-not-selected.json', raw_not_selected)
    # Many input records may reference an occurrence, but repeated thin rows are
    # never declared duplicates. Only single-candidate cross-file references are
    # counted once; all original records remain in the ledger.
    unique_claims = defaultdict(list)
    for record in ledger:
        if len(record['matched_keys']) == 1:
            unique_claims[record['matched_keys'][0]].append(record['record_id'])
    with (args.output / 'records.jsonl').open('w') as stream:
        for row in ledger:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    with (args.output / 'occurrences.jsonl').open('w') as stream:
        for row in occurrences:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    summary = dict(release_id=manifest['release_id'], candidate_assets=assets,
                   manifest_sha256=digest(args.release / 'manifest.json'), measurement_sha256=digest(__file__),
                   frozen_ledger_sha256=digest(args.frozen_ledger),
                   legacy_inputs={name: pins[name] for name in FILES},
                   input_records=len(records), dispositions=dict(outcomes),
                   distinct_uniquely_referenced_native_occurrences=len(unique_claims),
                   multiple_input_references=sum(len(ids) > 1 for ids in unique_claims.values()),
                   proven_duplicate_input_records=0,
                   native_rows=native_count, source_scoped_native_occurrences=len(selected),
                   source_scoped_without_legacy_reference=sum(not r['legacy_record_ids'] for r in occurrences),
                   raw_states=dict(raw_states),
                   raw_house_bodies_read=sum(r['state'] != 'not_located_in_local_mirror' for r in house.cache.values()),
                   raw_house_decoded_bytes=house.bytes_read,
                   raw_house_occurrences_not_in_selected_scope=len(raw_not_selected),
                   records_with_source_links_not_exactly_linked=sum(bool(r['source_links_not_exactly_linked']) for r in ledger),
                   source_occurrences_with_raw_field_differences=sum(bool(r['raw_field_differences']) for r in occurrences),
                   source_occurrences_with_document_rows_requiring_review=sum(bool(r['published_document_rows_without_source_link']) for r in occurrences),
                   unavailable_source_claims=0,
                   limits=['Matching uses exact source scope, name and populated legacy role fields; no name aliases.',
                           'Candidate field matches are not source-verified migration verdicts. Raw name correspondence remains unadjudicated.',
                           'Raw House XML is read once per selected digest; role/representation and removal differences are flagged. Other sources remain unread.',
                           'A missing mirror body does not establish upstream source unavailability.',
                           'Repeated input records remain separate; a shared occurrence is not a duplicate verdict.',
                           'Exact source URL differences are reported, without assuming an HTTP/HTTPS alias.',
                           'This candidate ledger does not establish live site/MCP agreement or approve retirement.'])
    assert len(ledger) == sum(outcomes.values())
    assert len({r['record_id'] for r in ledger}) == len(records)
    write_json(args.output / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('data', 'release', 'mirror', 'frozen-ledger', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2))


if __name__ == '__main__':
    main()
