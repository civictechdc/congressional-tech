"""Six browser tables with typed fields and direct file links.

The source payload is the only JSON column: providers have different raw schemas.
Searches never read that column. Internal model objects are folded into the
meeting, witness or material they describe, not published as navigation steps.
"""
import json
from collections import defaultdict, deque
from heapq import merge
from itertools import batched
from operator import attrgetter, itemgetter
from pathlib import Path
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from .collector_labels import PLACEHOLDER_LABELS, collector_placeholder_conflict

TABLES = {'meeting': 'meetings', 'committee_term': 'committees', 'material': 'materials',
          'appearance': 'witnesses', 'data_issue': 'issues', 'source_record': 'sources'}
ASPECTS = ('recording', 'transcript', 'documents', 'witnesses', 'captions')
STRINGS = ('id', 'kind', 'title', 'chamber', 'date', 'type', 'status', 'meeting_id',
           'provider', 'category', 'selection', 'search_text', 'position', 'organization',
           'participation', 'explanation', 'severity', 'subject_kind', 'subject_id', 'scheduled_at', 'meeting_status', 'recording_url', 'document_type', 'committee_level', 'parent_committee_id', 'access', 'committee_type', 'source_committee_type', 'committee_code')
LISTS = ('committee_ids', 'roles', 'meeting_ids', 'appearance_ids', 'source_ids', 'source_document_groups', 'committee_types')
LINK = pa.struct([(k, pa.string()) for k in ('url', 'label', 'role', 'media_type', 'version', 'published_at', 'sha256', 'saved_copy_sha256', 'saved_filename')])
NOTE = pa.struct([(k, pa.string()) for k in ('label', 'value')])
SCHEMA = pa.schema([(k, pa.string()) for k in STRINGS] + [('congress', pa.int32()), ('issue_count', pa.int32())]
                   + [(k, pa.list_(pa.string())) for k in LISTS]
                   + [('evidence_states', pa.struct([(k, pa.string()) for k in ASPECTS])),
                      ('files', pa.list_(LINK)), ('facts', pa.list_(NOTE))])
SOURCE_SCHEMA = pa.schema([(k, pa.string()) for k in
    ('id', 'kind', 'provider', 'url', 'retrieved_at', 'source_modified_at', 'imported_at', 'input_snapshot_id', 'identifier', 'retained_uri', 'retained_sha256', 'payload')])
QUERY_COLUMNS = [*STRINGS[:12], 'congress', 'issue_count', 'committee_ids', 'roles', 'evidence_states', 'scheduled_at', 'meeting_status', 'recording_url', 'position', 'organization', 'document_type', 'source_document_groups', 'committee_level', 'access', 'committee_type', 'source_committee_type', 'committee_types', 'committee_code', 'parent_committee_id']


# Shared field types, explicit table shapes. Optional domain fields remain even
# when today's sources do not populate them (for example witness document links).
COMMON_COLUMNS = ('id', 'kind', 'title', 'chamber', 'congress', 'committee_ids',
                  'committee_level', 'committee_types', 'source_ids', 'explanation',
                  'issue_count', 'facts')
TABLE_COLUMNS = {
    'meeting': (*COMMON_COLUMNS, 'date', 'type', 'status', 'meeting_id',
                'search_text', 'scheduled_at', 'access', 'evidence_states'),
    'committee_term': (*COMMON_COLUMNS, 'committee_type', 'source_committee_type',
                       'committee_code', 'parent_committee_id'),
    'appearance': (*COMMON_COLUMNS, 'date', 'meeting_id', 'search_text', 'position',
                   'organization', 'participation', 'roles'),
    'material': (*COMMON_COLUMNS, 'date', 'type', 'meeting_id', 'provider', 'category',
                 'scheduled_at', 'meeting_status', 'recording_url', 'document_type',
                 'meeting_ids', 'appearance_ids', 'source_document_groups', 'files'),
    'data_issue': (*COMMON_COLUMNS, 'date', 'status', 'meeting_id', 'category',
                   'selection', 'severity', 'subject_kind', 'subject_id'),
}
TABLE_SCHEMAS = {kind: pa.schema([SCHEMA.field(name) for name in names])
                 for kind, names in TABLE_COLUMNS.items()}
# GitHub's per-file limit, also enforced by publication-budget.py. A source file
# closes before its next row group could take it past the target.
FILE_LIMIT = 100_000_000
SOURCE_FILE_TARGET = 85_000_000
SOURCE_ROW_GROUP = 512


def sources_of(record):
    citations = list(record.get('provenance', {}).get('citations', []))
    citations += (record.get('resolution') or {}).get('provenance', {}).get('citations', [])
    for evidence in record.get('field_evidence', []):
        citations += evidence.get('selected', {}).get('citations', [])
        for alternative in evidence.get('alternatives', []):
            citations += alternative.get('provenance', {}).get('citations', [])
    return {c['source']['id'] for c in citations}


def _write_table(rows, schema, path, *, row_group_size):
    """Convert one row group at a time instead of duplicating the full table."""
    with pq.ParquetWriter(path, schema, compression='snappy', write_statistics=True) as writer:
        # An empty table still needs the same empty row group as write_table.
        for start in range(0, max(1, len(rows)), row_group_size):
            table = pa.Table.from_pylist(rows[start:start + row_group_size], schema=schema)
            writer.write_table(table, row_group_size=row_group_size)


def _source_row(source):
    row = {key: source.get(key) for key in SOURCE_SCHEMA.names}
    row['source_modified_at'] = (source.get('source_modified_at') or {}).get('date')
    row['identifier'] = json.dumps(source.get('identifier'), ensure_ascii=False)
    row['retained_uri'] = (source.get('retained') or {}).get('uri')
    row['retained_sha256'] = (source.get('retained') or {}).get('sha256')
    row['payload'] = json.dumps(source.get('payload'), ensure_ascii=False, separators=(',', ':'))
    return row


def _write_sources(rows, stage):
    """Stream ID-ordered rows into files below the size target; hold one row group.

    One file keeps the name sources.parquet; more are sources-1, -2, ... in ID
    order. Returns (path, row count) pairs.
    """
    batches = (pa.Table.from_pylist(list(batch), schema=SOURCE_SCHEMA) for batch in batched(rows, SOURCE_ROW_GROUP))
    pending = next(batches, None)
    if pending is None:  # An empty table still needs the same empty row group as write_table.
        pending = pa.Table.from_pylist([], schema=SOURCE_SCHEMA)
    files = []
    while pending is not None:
        path, count = Path(stage) / f'sources-{len(files) + 1}.parquet', 0
        with pa.OSFile(str(path), 'wb') as sink, \
                pq.ParquetWriter(sink, SOURCE_SCHEMA, compression='snappy', write_statistics=True) as writer:
            # Close the file before a row group whose in-memory size would take
            # it past the target; written row groups are smaller in practice.
            while pending is not None and (not count or sink.tell() + pending.nbytes <= SOURCE_FILE_TARGET):
                writer.write_table(pending, row_group_size=SOURCE_ROW_GROUP)
                count += pending.num_rows
                pending = next(batches, None)
        files.append((path, count))
    if len(files) == 1:
        files = [(files[0][0].rename(Path(stage) / 'sources.parquet'), files[0][1])]
    for path, _ in files:
        if path.stat().st_size >= FILE_LIMIT:
            raise ValueError('Source table exceeds GitHub file limit')
    return [(path.name, count) for path, count in files]


def _event_page(url):
    """Same host and /event/ rule as congress_api.adapters.meetings.event_page."""
    parsed = urlsplit(url or '')
    return parsed.hostname in ('congress.gov', 'www.congress.gov') and parsed.path.startswith('/event/')


from congress_api.matching.committees import HIERARCHY_SOURCE, hierarchy_from_code


def write_tables(records, sources, query_rows, stage, descriptor):
    """Write the six browser Parquet tables from streamed records, sources, and query rows.

    Sources must arrive in ascending ID order.
    """
    def source_rows():
        previous = None
        for source in sources:
            if previous is not None and source['id'] <= previous:
                raise ValueError(f"Sources must be unique and in ascending ID order: {source['id']} follows {previous}")
            previous = source['id']
            yield _source_row(source)
    source_files = _write_sources(source_rows(), stage)
    rows = {kind: {} for kind in TABLES if kind != 'source_record'}
    for row in query_rows:
        rows[row['kind']][row['id']] = {**row, 'files': [], 'facts': [], 'meeting_ids': [],
                                      'appearance_ids': [], 'source_ids': []}
    versions, formats, links, occurrences, subjects = {}, defaultdict(list), [], defaultdict(list), {}
    context_records, meeting_subjects, conflict_facts, owners = {}, [], {}, {}
    committee_codes, committee_parents = {}, {}
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
            if kind == 'committee_term':
                parent = (record.get('parent') or {}).get('id')
                committee_type = record.get('committee_type')
                row['committee_type'] = committee_type or 'unknown'
                row['source_committee_type'] = record.get('source_committee_type')
                row['parent_committee_id'] = parent
                for key, label in (('start', 'Active from'), ('end', 'Active through')):
                    value = (record.get('active') or {}).get(key)
                    if value: row['facts'].append({'label': label, 'value': value})
                if record.get('website'):
                    row['facts'].append({'label': 'Official website or archive', 'value': record['website']})
                stored_level = record.get('committee_level')
                if stored_level not in (None, 'unknown'):
                    row['committee_level'] = stored_level
                else:
                    row['committee_level'] = ('subcommittee' if parent or committee_type == 'subcommittee' else
                                              'full' if committee_type not in (None, 'unknown') else 'unknown')
                code = record.get('committee_code') or next((i['value'] for i in record.get('identifiers', []) if i['scheme'] == 'congress.gov:committee'), None)
                row['committee_code'] = code
                if stored_level in (None, 'unknown') and code:
                    level, parent_code = hierarchy_from_code(code)
                    if level != 'unknown':
                        committee_codes[(row.get('congress'), code.lower())] = id
                        if row['committee_level'] == 'unknown': row['committee_level'] = level
                        if parent_code: committee_parents[id] = (row.get('congress'), parent_code.lower())
                        if parent:
                            row['facts'].append({'label': 'Committee hierarchy', 'value': 'The source identifies a parent committee.'})
                        elif row['committee_level'] == level:
                            row['facts'].append({'label': 'Committee hierarchy', 'value': f'Congress.gov systemCode {code}: final two digits 00 identify a full committee; other digits identify a subcommittee.'})
                            row['facts'].append({'label': 'Hierarchy definition', 'value': HIERARCHY_SOURCE})
                elif parent:
                    row['facts'].append({'label': 'Committee hierarchy', 'value': 'The source identifies a parent committee.'})
            if kind == 'meeting':
                row['access'] = record.get('access') if record.get('access') not in (None, 'unknown') else 'unknown'
                start = record.get('scheduled_start') or {}
                if start:
                    row['scheduled_at'] = start.get('original') or start.get('date')
                assembled_type = record.get('meeting_type')
                if assembled_type not in (None, 'unknown', 'meeting'):
                    row['type'] = assembled_type
                if record.get('source_type'):
                    row['facts'].append({'label': 'Source type', 'value': record['source_type']})
                for field in record.get('field_evidence') or []:
                    if field.get('path') == '/meeting_type' and field.get('selection_reason'):
                        row['facts'].append({'label': 'Type based on', 'value': field['selection_reason']})
            if kind == 'material':
                dates = record.get('proceeding_dates') or []
                if not row.get('date') and dates:
                    row['date'] = min(d['date'] for d in dates)
                if record.get('document_type'): row['document_type'] = record['document_type']
                if record.get('source_document_groups'): row['source_document_groups'] = list(record['source_document_groups'])
                for file in record.get('files') or []:
                    if not file.get('url'): continue
                    version = file.get('version_label')
                    if version and version.rstrip('.') in PLACEHOLDER_LABELS: version = None
                    published_at = file.get('published_at') or {}
                    if row.get('type') == 'recording' and not row.get('date') and published_at.get('date'):
                        row['date'] = published_at['date']
                    row['files'].append({'url': file['url'], 'label': file.get('format_label') or file.get('media_type') or file.get('role'),
                                         'role': file.get('role'), 'media_type': file.get('media_type'), 'version': version,
                                         'published_at': published_at.get('date'), 'sha256': file.get('sha256'),
                                         'saved_copy_sha256': file.get('saved_copy_sha256'), 'saved_filename': file.get('saved_filename')})
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
            # Field disagreements and ownership were handled above. Retain
            # only the file fields and citation IDs needed to build links.
            file_info = {key: record[key] for key in ('locations', 'format_label', 'media_type', 'sha256', 'saved_copy_sha256', 'saved_filename') if key in record}
            file_info['source_ids'] = sources_of(record)
            formats[record['version']['id']].append(file_info)
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
        # Assembled materials already carry these files, including saved copies.
        embedded = bool(row['files'])
        for record in entries:
            row['source_ids'].extend(version_sources | record['source_ids'])
            if embedded: continue
            for location in record.get('locations', []):
                row['files'].append({'url': location['url'], 'label': record.get('format_label') or record.get('media_type') or location['role'],
                                     'role': location['role'], 'media_type': record.get('media_type'), 'version': label,
                                     'published_at': (published or {}).get('date'), 'sha256': record.get('sha256'),
                                     'saved_copy_sha256': record.get('saved_copy_sha256'), 'saved_filename': record.get('saved_filename')})
    del versions, formats
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
        if kind == 'committee_term': row['committee_ids'] = [*(row.get('committee_ids') or []), id]
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
            # The agenda association cites this meeting's source. A shared bill
            # also has citations from other meetings; those do not describe this one.
            row['source_ids'].extend(sources_of(record))
    for id, action in context_records.items():
        if action['kind'] not in ('amendment', 'vote') or id in attached_actions: continue
        row = rows['meeting'].get(action['meeting']['id'])
        if row is not None:
            label = f"{action['kind'].capitalize()} {action.get('number') or ''}".strip()
            row['facts'].append({'label': label, 'value': (action.get('description') or action.get('question') or 'Listed action') + ' (no attached file)'})
            row['source_ids'].extend(sources_of(action))
    del links, context_records, meeting_subjects, subjects, amendment_groups, attached_actions
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
            if row['access'] == 'unknown' and record.get('access') not in (None, 'unknown'):
                row['access'] = record['access']
            for field in record.get('field_evidence') or []:
                if field.get('path') == '/access' and field.get('selection_reason') and row.get('access') not in (None, 'unknown'):
                    if not any(fact['label'] == 'Access based on' for fact in row['facts']):
                        row['facts'].append({'label': 'Access based on', 'value': field['selection_reason']})
    del occurrences
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
            candidates = sorted((f for f in row['files'] if not _event_page(f['url'])), key=preference)
            row['recording_url'] = candidates[0]['url'] if candidates else None
    for entries in rows.values():
        for row in entries.values(): row['issue_count'] = 0
    for issue in rows['data_issue'].values():
        field = next((f['value'] for f in issue['facts'] if f['label'] == 'field path'), None)
        subject = (issue['subject_kind'], issue['subject_id'])
        disagreement = conflict_facts.get((*subject, field), [])
        issue['facts'].extend(disagreement)
        compared = [f['value'] for f in disagreement if f['label'] == 'Selected value' or f['label'].startswith('Alternative ')]
        if issue.get('status') == 'open' and subject[0] == 'material_version' and field == '/label' and collector_placeholder_conflict(compared):
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
    del conflict_facts, owners
    for id, parent_code in committee_parents.items():
        row = rows['committee_term'][id]
        if not row['parent_committee_id']: row['parent_committee_id'] = committee_codes.get(parent_code)
    def effective_committee_type(id, seen=()):
        if id in seen: return 'unknown'
        committee = rows['committee_term'].get(id, {})
        native_type = committee.get('committee_type')
        if native_type not in (None, 'unknown', 'subcommittee'):
            return native_type
        if committee.get('committee_level') == 'subcommittee':
            return effective_committee_type(committee.get('parent_committee_id'), (*seen, id))
        return 'unknown'
    for kind, entries in rows.items():
        values = sorted(entries.values(), key=lambda r: (r.get('congress') or 0, r['id']))
        for row in values:
            row['committee_types'] = sorted({effective_committee_type(id) for id in row.get('committee_ids') or []}) or ['unknown']
            if kind != 'committee_term':
                levels = {rows['committee_term'].get(id, {}).get('committee_level', 'unknown') for id in row.get('committee_ids') or []}
                row['committee_level'] = 'subcommittee' if 'subcommittee' in levels else 'full' if levels == {'full'} else 'unknown'
            for key in LISTS: row[key] = sorted(set(row.get(key) or []))
            row['facts'] = [dict(label=k, value=v) for k, v in dict.fromkeys((f['label'], f['value']) for f in row['facts'])]
        omitted = set(SCHEMA.names) - set(TABLE_SCHEMAS[kind].names)
        for row in values:
            populated = sorted(name for name in omitted if row.get(name) not in (None, '', [], {}))
            if populated:
                raise ValueError(f"{kind} {row['id']} has populated fields outside its table schema: {populated}")
        path = TABLES[kind] + '.parquet'
        _write_table(values, TABLE_SCHEMAS[kind], Path(stage) / path, row_group_size=2048)
        if (Path(stage) / path).stat().st_size >= FILE_LIMIT:
            raise ValueError(f'{path} exceeds GitHub file limit; partition this table before publishing')
        descriptor(path, 'details', 'committee_explorer.parquet.' + kind, len(values), media_type='application/vnd.apache.parquet')
    # Source files were written first; the manifest still lists them last.
    for path, count in source_files:
        descriptor(path, 'sources', 'committee_explorer.parquet.source_record', count, media_type='application/vnd.apache.parquet')


def write_catalog(catalog, current, stage, descriptor, write, evidence_states, retained_sources=()):
    """``retained_sources``: sources only issue history holds, streamed in ascending ID order."""
    from .query import write_queries
    query_rows, info = deque(), {}
    def collect(path, value, role, schema_name, count, **kwargs):
        if schema_name == 'committee_explorer.query-rows': query_rows.extend(value['rows'])
        elif schema_name == 'committee_explorer.queries': info.update(value)
    write_queries(catalog, current, collect, evidence_states=evidence_states)
    def consume_query_rows():
        # The table builder copies each row before enrichment. Release its
        # original immediately instead of keeping both sets until publication.
        while query_rows:
            yield query_rows.popleft()
    # Assembly already orders sources by ID, so this sorts references in linear
    # time; apply_decisions appends its decision sources. Retained sources join
    # in the same pass, one decoded row at a time.
    sources = merge(sorted(catalog.sources, key=attrgetter('id')), retained_sources, key=attrgetter('id'))
    write_tables((r.model_dump(mode='json') for r in catalog.records),
                 (s.model_dump(mode='json') for s in sources), consume_query_rows(), stage, descriptor)
    info.pop('partitions', None)
    info.update(storage='parquet', query_columns=QUERY_COLUMNS)
    write('queries.json', info, 'index', 'committee_explorer.queries', len(info['kinds']))

