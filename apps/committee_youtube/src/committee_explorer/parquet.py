"""Six browser tables with typed fields and direct file links.

The source payload is the only JSON column: providers have different raw schemas.
Searches never read that column. Internal model objects are folded into the
meeting, witness or material they describe, not published as navigation steps.
"""
from collections import defaultdict
import json
from pathlib import Path
from urllib.parse import urlsplit

from congress_api.adapters.meetings import category, document_title, event_page, meeting_type

import pyarrow as pa
import pyarrow.parquet as pq

TABLES = {'meeting': 'meetings', 'committee_term': 'committees', 'material': 'materials',
          'appearance': 'witnesses', 'data_issue': 'issues', 'source_record': 'sources'}
ASPECTS = ('recording', 'transcript', 'documents', 'witnesses', 'captions')
# Former collector defaults, never values supplied by the source.
PLACEHOLDER_LABELS = {'Reported edition; revision not established', 'Reported recording; revision not established'}
STRINGS = ('id', 'kind', 'title', 'chamber', 'date', 'type', 'status', 'meeting_id',
           'provider', 'category', 'selection', 'search_text', 'position', 'organization',
           'participation', 'explanation', 'severity', 'subject_kind', 'subject_id', 'scheduled_at', 'meeting_status', 'recording_url')
LISTS = ('committee_ids', 'roles', 'meeting_ids', 'appearance_ids', 'source_ids')
LINK = pa.struct([(k, pa.string()) for k in ('url', 'label', 'role', 'media_type', 'version', 'published_at', 'sha256')])
NOTE = pa.struct([(k, pa.string()) for k in ('label', 'value')])
SCHEMA = pa.schema([(k, pa.string()) for k in STRINGS] + [('congress', pa.int32()), ('issue_count', pa.int32())]
                   + [(k, pa.list_(pa.string())) for k in LISTS]
                   + [('evidence_states', pa.struct([(k, pa.string()) for k in ASPECTS])),
                      ('files', pa.list_(LINK)), ('facts', pa.list_(NOTE))])
SOURCE_SCHEMA = pa.schema([(k, pa.string()) for k in
    ('id', 'kind', 'provider', 'url', 'retrieved_at', 'source_modified_at', 'imported_at', 'input_snapshot_id', 'identifier', 'retained_uri', 'retained_sha256', 'payload')])
QUERY_COLUMNS = [*STRINGS[:12], 'congress', 'issue_count', 'committee_ids', 'roles', 'evidence_states', 'scheduled_at', 'meeting_status', 'recording_url', 'position', 'organization']


def sources_of(record):
    citations = list(record.get('provenance', {}).get('citations', []))
    for evidence in record.get('field_evidence', []):
        citations += evidence.get('selected', {}).get('citations', [])
        for alternative in evidence.get('alternatives', []):
            citations += alternative.get('provenance', {}).get('citations', [])
    return {c['source']['id'] for c in citations}


def write_tables(records, sources, query_rows, stage, descriptor):
    """Accept iterables so a retained JSON publication can migrate without reassembly."""
    source_rows, native_documents, native_meetings = [], {}, {}
    for source in sources:
        if source['provider'] == 'congress.gov' and isinstance(source.get('payload'), dict):
            native_meetings[source['id']] = {k: source['payload'].get(k) for k in ('type', 'title')}
            for group in ('meetingDocuments', 'witnessDocuments'):
                for i, document in enumerate(source['payload'].get(group) or []):
                    native_documents[(source['id'], f'/{group}/{i}')] = document
        row = {key: source.get(key) for key in SOURCE_SCHEMA.names}
        row['source_modified_at'] = (source.get('source_modified_at') or {}).get('date')
        row['identifier'] = json.dumps(source.get('identifier'), ensure_ascii=False)
        row['retained_uri'] = (source.get('retained') or {}).get('uri')
        row['retained_sha256'] = (source.get('retained') or {}).get('sha256')
        row['payload'] = json.dumps(source.get('payload'), ensure_ascii=False, separators=(',', ':'))
        source_rows.append(row)
    rows = {kind: {} for kind in TABLES if kind != 'source_record'}
    for row in query_rows:
        rows[row['kind']][row['id']] = {**row, 'files': [], 'facts': [], 'meeting_ids': [],
                                      'appearance_ids': [], 'source_ids': []}
    versions, formats, links, occurrences, subjects = {}, defaultdict(list), [], defaultdict(list), {}
    context_records, meeting_subjects, conflict_facts, owners = {}, [], {}, {}
    for record in records:
        kind, id = record['kind'], record['id']
        # Keep the actual disagreement when the internal subject is folded away.
        for field in record.get('field_evidence', []):
            if not field.get('alternatives'): continue
            value = record
            for key in field['path'].lstrip('/').split('/'):
                key = key.replace('~1', '/').replace('~0', '~')
                value = value[int(key)] if isinstance(value, list) else value.get(key) if isinstance(value, dict) else None
            def display(value):
                return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            facts = [{'label': 'Selected value', 'value': display(value)}]
            facts += [{'label': f'Alternative {i + 1}', 'value': display(alt['value'])} for i, alt in enumerate(field['alternatives'])]
            if field.get('selection_reason'): facts.append({'label': 'Selection reason', 'value': field['selection_reason']})
            conflict_facts[(kind, id, field['path'])] = facts
        if kind not in rows:
            owner = record.get('material') or record.get('version') or record.get('meeting') or (record.get('subject') if kind == 'assessment' else None)
            if owner: owners[(kind, id)] = (owner['kind'], owner['id'])
        # Every meeting-owned subject uses its explicit meeting reference.
        if record.get('meeting'):
            subjects[id] = record['meeting']['id']
        if kind in ('legislative_item', 'amendment', 'vote', 'amendment_group', 'person'):
            context_records[id] = record
        if kind == 'meeting_subject':
            meeting_subjects.append(record)
        if kind in rows and id in rows[kind]:
            row = rows[kind][id]
            provenance = record.get('provenance', {})
            row['source_ids'] = sorted(sources_of(record))
            row['explanation'] = provenance.get('explanation')
            if kind == 'meeting':
                for source_id in row['source_ids']:
                    if source_id not in native_meetings: continue
                    native = native_meetings[source_id]
                    row['type'], field = meeting_type(native)
                    if native.get('type'): row['facts'].append({'label': 'Source type', 'value': native['type']})
                    if field == '/title': row['facts'].append({'label': 'Type based on', 'value': 'The source title explicitly says business meeting.'})
                    break
            if kind == 'material':
                dates = record.get('proceeding_dates') or []
                if not row.get('date') and dates:
                    row['date'] = min(d['date'] for d in dates)
                for citation in provenance.get('citations', []):
                    document = native_documents.get((citation['source']['id'], citation.get('selector')))
                    if document:
                        row['title'] = document_title(document) or row['title']
                        row['category'] = category(document)
                        break
                if not row.get('title') or row['title'] == '(Untitled source record)':
                    row['title'] = (row.get('category') if row.get('category') not in (None, 'unknown') else row.get('type') or 'Document').replace('_', ' ').capitalize()
            if kind == 'appearance':
                affiliation = record.get('affiliation') or {}
                row.update(position=affiliation.get('position'), organization=affiliation.get('organization_name'),
                           participation=record.get('participation'))
                row['search_text'] = ' '.join(str(v) for v in (row['title'], row['position'], row['organization']) if v)
                for key in ('on_behalf_of', 'location'):
                    if affiliation.get(key): row['facts'].append({'label': key.replace('_', ' '), 'value': affiliation[key]})
            elif kind == 'data_issue':
                row.update(severity=record.get('impact'), explanation=record.get('explanation'), subject_kind=record['subject']['kind'], subject_id=record['subject']['id'])
                for key in ('expected', 'detected_at', 'last_checked_at', 'field_path'):
                    value = record.get(key)
                    if isinstance(value, dict): value = value.get('date')
                    if value: row['facts'].append({'label': key.replace('_', ' '), 'value': value})
                if record.get('resolution'):
                    row['facts'].append({'label': 'Resolution', 'value': record['resolution']['explanation']})
            elif kind == 'material':
                for k in ('medium', 'coverage', 'production'):
                    value = record.get('details', {}).get(k)
                    if value and value != 'unknown': row['facts'].append({'label': k, 'value': value})
        elif kind == 'material_version':
            versions[id] = (record['material']['id'], record.get('label'), record.get('published_at'), sources_of(record))
        elif kind == 'representation':
            formats[record['version']['id']].append(record)
        elif kind == 'material_link':
            links.append((record['material']['id'], record['subject']['kind'], record['subject']['id'], sources_of(record)))
        elif kind == 'occurrence':
            occurrences[record['meeting']['id']].append(record)
    for id, entries in formats.items():
        if id not in versions: continue
        material_id, label, published, version_sources = versions[id]
        row = rows['material'].get(material_id)
        if row is None: continue
        if row.get('type') == 'recording' and not row.get('date') and published:
            row['date'] = published['date']
        # The routine placeholder is an implementation detail, not an edition label.
        if label and label.rstrip('.') in PLACEHOLDER_LABELS: label = None
        for record in entries:
            row['source_ids'].extend(version_sources | sources_of(record))
            for location in record.get('locations', []):
                row['files'].append({'url': location['url'], 'label': record.get('format_label') or record.get('media_type') or location['role'],
                                     'role': location['role'], 'media_type': record.get('media_type'), 'version': label,
                                     'published_at': (published or {}).get('date'), 'sha256': record.get('sha256')})
    amendment_groups = defaultdict(list)
    for record in context_records.values():
        if record['kind'] == 'amendment_group':
            for member in record['members']: amendment_groups[member['id']].append(record['label'])
    attached_actions = set()
    for material_id, kind, id, source_ids in links:
        row = rows['material'].get(material_id)
        if row is None: continue
        meeting_id = id if kind == 'meeting' else subjects.get(id)
        if meeting_id: row['meeting_ids'].append(meeting_id)
        if kind == 'appearance': row['appearance_ids'].append(id)
        row['source_ids'].extend(source_ids)
        if kind in ('amendment', 'vote') and id in context_records:
            attached_actions.add(id)
            action = context_records[id]
            for key in ('number', 'question', 'description', 'disposition', 'outcome', 'method'):
                value = action.get(key)
                if value and value != 'unknown' and value != row['title']:
                    row['facts'].append({'label': f'{kind.capitalize()} {key}', 'value': value})
            target = context_records.get((action.get('target') or action.get('subject') or {}).get('id'), {})
            title = target.get('designation') or target.get('description') or target.get('label')
            if title: row['facts'].append({'label': 'Regarding', 'value': title})
            for sponsor in action.get('sponsors', []):
                person = context_records.get((sponsor.get('person') or {}).get('id'), {})
                name = sponsor.get('name') or person.get('name')
                if name: row['facts'].append({'label': 'Sponsor', 'value': name})
                else:
                    for identifier in person.get('identifiers', []):
                        if identifier['scheme'] == 'bioguide': row['facts'].append({'label': 'Sponsor Bioguide ID', 'value': identifier['value']})
            for label in amendment_groups[id]: row['facts'].append({'label': 'En bloc group', 'value': label})
            for label, value in (action.get('tally') or {}).items():
                if value is not None: row['facts'].append({'label': label.replace('_', ' '), 'value': str(value)})
    for record in meeting_subjects:
        row = rows['meeting'].get(record['meeting']['id'])
        item = context_records.get(record['item']['id'])
        if row is not None and item:
            row['facts'].append({'label': 'Related ' + item['item_type'], 'value': item['designation']})
            row['source_ids'].extend(sources_of(record) | sources_of(item))
    for id, action in context_records.items():
        if action['kind'] not in ('amendment', 'vote') or id in attached_actions: continue
        row = rows['meeting'].get(action['meeting']['id'])
        if row is not None:
            label = f"{action['kind'].capitalize()} {action.get('number') or ''}".strip()
            row['facts'].append({'label': label, 'value': (action.get('description') or action.get('question') or 'Listed action') + ' (no attached file)'})
            row['source_ids'].extend(sources_of(action))
    for id, entries in occurrences.items():
        row = rows['meeting'].get(id)
        if row is None: continue
        for record in sorted(entries, key=lambda r: (r.get('scheduled_start') or {}).get('date', '9999')):
            row['source_ids'].extend(sources_of(record))
            start = record.get('scheduled_start') or {}
            if start and not row.get('scheduled_at'):
                row['scheduled_at'] = start.get('original') or start.get('date')
            location = record.get('location') or {}
            for key, value in location.items():
                if isinstance(value, str) and value: row['facts'].append({'label': key.replace('_', ' '), 'value': value})
            if record.get('access') not in (None, 'unknown'):
                row['facts'].append({'label': 'Access', 'value': record['access']})
    for row in rows['material'].values():
        if len(set(row['meeting_ids'])) == 1: row['meeting_id'] = row['meeting_ids'][0]
        meetings = [rows['meeting'][id] for id in row['meeting_ids'] if id in rows['meeting']]
        if meetings:
            active = [r for r in meetings if r.get('status') not in ('canceled', 'postponed', 'not_held')]
            first = min(active or meetings, key=lambda r: r.get('scheduled_at') or r.get('date') or '9999')
            row['scheduled_at'] = first.get('scheduled_at')
            row['meeting_status'] = first.get('status')
        if row['type'] == 'recording':
            def preference(file):
                url = urlsplit(file['url'])
                return (0 if url.hostname in ('www.senate.gov', 'senate.gov') and url.path.startswith('/isvp') else
                        1 if url.hostname in ('www.youtube.com', 'youtube.com', 'youtu.be') else 2, file['url'])
            candidates = sorted((f for f in row['files'] if not event_page(f['url'])), key=preference)
            row['recording_url'] = candidates[0]['url'] if candidates else None
    for entries in rows.values():
        for row in entries.values(): row['issue_count'] = 0
    for issue in rows['data_issue'].values():
        field = next((f['value'] for f in issue['facts'] if f['label'] == 'field path'), None)
        subject = (issue['subject_kind'], issue['subject_id'])
        disagreement = conflict_facts.get((*subject, field), [])
        issue['facts'].extend(disagreement)
        compared = [f['value'].rstrip('.') for f in disagreement if f['label'] == 'Selected value' or f['label'].startswith('Alternative ')]
        if issue.get('status') == 'open' and subject[0] == 'material_version' and field == '/label' and compared and set(compared) <= PLACEHOLDER_LABELS:
            issue['status'] = 'dismissed'
            issue['title'] = 'Collector placeholder labels differed'
            issue['explanation'] = 'Collectors assigned different internal edition labels. This is not evidence of a disagreement in source content.'
            issue['facts'].append({'label': 'Display correction', 'value': 'Automatically dismissed by the Parquet exporter; original values retained below.'})
        visited = set()
        while subject in owners and subject not in visited:
            visited.add(subject)
            subject = owners[subject]
        owner = rows.get(subject[0], {}).get(subject[1])
        if owner is not None:
            issue['subject_kind'], issue['subject_id'] = subject
            if issue.get('status') == 'open': owner['issue_count'] += 1
    for kind, entries in rows.items():
        values = sorted(entries.values(), key=lambda r: (r.get('congress') or 0, r['id']))
        for row in values:
            for key in LISTS: row[key] = sorted(set(row.get(key) or []))
            row['facts'] = [dict(label=k, value=v) for k, v in dict.fromkeys((f['label'], f['value']) for f in row['facts'])]
        path = TABLES[kind] + '.parquet'
        pq.write_table(pa.Table.from_pylist(values, schema=SCHEMA), Path(stage) / path,
                       compression='snappy', row_group_size=2048, write_statistics=True)
        if (Path(stage) / path).stat().st_size >= 100_000_000:
            raise ValueError(f'{path} exceeds GitHub file limit; partition this table before publishing')
        descriptor(path, 'details', 'committee_explorer.parquet.' + kind, len(values), media_type='application/vnd.apache.parquet')
    source_rows.sort(key=lambda r: r['id'])
    def write_sources(path, values):
        pq.write_table(pa.Table.from_pylist(values, schema=SOURCE_SCHEMA), Path(stage) / path,
                       compression='snappy', row_group_size=512, write_statistics=True)
    write_sources('sources.parquet', source_rows)
    if (Path(stage) / 'sources.parquet').stat().st_size < 100_000_000:
        descriptor('sources.parquet', 'sources', 'committee_explorer.parquet.source_record', len(source_rows), media_type='application/vnd.apache.parquet')
    else:
        total_bytes = (Path(stage) / 'sources.parquet').stat().st_size
        chunk_rows = max(1, int(len(source_rows) * 85_000_000 / total_bytes))
        (Path(stage) / 'sources.parquet').unlink()
        # Split only when required by GitHub's per-file limit.
        for i, start in enumerate(range(0, len(source_rows), chunk_rows)):
            values = source_rows[start:start + chunk_rows]
            path = f'sources-{i + 1}.parquet'
            write_sources(path, values)
            if (Path(stage) / path).stat().st_size >= 100_000_000:
                raise ValueError('Source table exceeds GitHub file limit')
            descriptor(path, 'sources', 'committee_explorer.parquet.source_record', len(values), media_type='application/vnd.apache.parquet')


def write_catalog(catalog, current, stage, descriptor, write, evidence_states):
    from .query import write_queries
    query_rows, info = [], {}
    def collect(path, value, role, schema_name, count, **kwargs):
        if schema_name == 'committee_explorer.query-rows': query_rows.extend(value['rows'])
        elif schema_name == 'committee_explorer.queries': info.update(value)
    write_queries(catalog, current, collect, evidence_states=evidence_states, include_relations=False)
    write_tables((r.model_dump(mode='json') for r in catalog.records),
                 (s.model_dump(mode='json') for s in catalog.sources), query_rows, stage, descriptor)
    info.pop('partitions', None)
    info.update(storage='parquet', query_columns=QUERY_COLUMNS)
    write('queries.json', info, 'index', 'committee_explorer.queries', len(info['kinds']))


def migrate(input_dir, output_dir):
    """Convert an existing release once, without acquisition or rebuilding records."""
    import gzip
    import shutil
    import tempfile
    from .browser import verify
    from .export import encode, file_sha, sha
    from committee_meeting.publication import ExportPartition
    _, root, manifest = verify(input_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.parquet-', dir=output))
    partitions = []
    def read(part):
        body = (root / part.path).read_bytes()
        return json.loads(gzip.decompress(body) if body.startswith(b'\x1f\x8b') else body)
    def values(schema, field):
        for part in manifest.partitions:
            if part.schema_name == schema: yield from read(part)[field]
    def descriptor(path, role, schema_name, count, media_type='application/json'):
        dest = stage / path
        partitions.append(ExportPartition(path=path, role=role, schema_name=schema_name, schema_version=manifest.schema_version,
            record_count=count, byte_size=dest.stat().st_size, sha256=file_sha(dest), media_type=media_type))
    try:
        write_tables(values('committee_explorer.records', 'records'), values('committee_explorer.sources', 'sources'),
                     values('committee_explorer.query-rows', 'rows'), stage, descriptor)
        info = read(next(p for p in manifest.partitions if p.schema_name == 'committee_explorer.queries'))
        info.pop('partitions', None)
        info.update(storage='parquet', query_columns=QUERY_COLUMNS)
        (stage / 'queries.json').write_bytes(encode(info))
        descriptor('queries.json', 'index', 'committee_explorer.queries', len(info['kinds']))
        publication_id = sha(encode([p.sha256 for p in partitions]))[:24]
        updated = manifest.model_copy(update={'partitions': tuple(partitions), 'publication_id': publication_id})
        raw = encode(updated.model_dump(mode='json'))
        (stage / 'manifest.json').write_bytes(raw)
        release = output / 'releases' / publication_id
        release.parent.mkdir(exist_ok=True)
        if release.exists(): shutil.rmtree(stage)
        else: stage.rename(release)
        pointer = {'schema_version': manifest.schema_version, 'publication_id': publication_id,
                   'manifest_path': f'releases/{publication_id}/manifest.json', 'manifest_sha256': sha(raw)}
        temporary = output / '.CURRENT.json.tmp'
        temporary.write_bytes(encode(pointer))
        temporary.replace(output / 'CURRENT.json')
        verify(output)
        return updated
    finally:
        if stage.exists(): shutil.rmtree(stage)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Convert a retained Explorer release directly to Parquet.')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = migrate(args.input, args.output)
    print(f'{result.publication_id}: {len(result.partitions)} files, {sum(p.byte_size for p in result.partitions):,} bytes')
