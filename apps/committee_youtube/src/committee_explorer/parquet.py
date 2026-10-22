"""Six browser tables with typed fields and direct file links.

The source payload is the only JSON column: providers have different raw schemas.
Searches never read that column. Internal model objects are folded into the
meeting, witness or material they describe, not published as navigation steps.
"""
import gc
import json
from collections import Counter, defaultdict, deque
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
    import sys

    citations = list(record.get('provenance', {}).get('citations', []))
    citations += (record.get('resolution') or {}).get('provenance', {}).get('citations', [])
    for evidence in record.get('field_evidence', []):
        citations += evidence.get('selected', {}).get('citations', [])
        for alternative in evidence.get('alternatives', []):
            citations += alternative.get('provenance', {}).get('citations', [])
    return {sys.intern(c['source']['id']) for c in citations}


_FILE_KEYS = ('url', 'label', 'role', 'media_type', 'version', 'published_at', 'sha256', 'saved_copy_sha256', 'saved_filename')


def _write_table(rows, schema, path, *, row_group_size, prepare_row=None, clear_rows=True):
    """Convert one row group at a time instead of duplicating the full table."""
    has_files = 'files' in schema.names
    has_facts = 'facts' in schema.names
    with pq.ParquetWriter(path, schema, compression='snappy', write_statistics=True) as writer:
        # An empty table still needs the same empty row group as write_table.
        for start in range(0, max(1, len(rows)), row_group_size):
            raw_chunk = rows[start:start + row_group_size]
            chunk = [prepare_row(r) for r in raw_chunk] if prepare_row is not None else raw_chunk
            for r in chunk:
                if has_files:
                    flist = r.get('files')
                    if flist and isinstance(flist[0], tuple):
                        r['files'] = [dict(zip(_FILE_KEYS, f)) if isinstance(f, tuple) else f for f in flist]
                    elif not flist:
                        r['files'] = []
                if has_facts:
                    fact_list = r.get('facts')
                    if fact_list:
                        r['facts'] = [
                            {'label': k, 'value': v}
                            for k, v in dict.fromkeys(
                                (f[0], f[1]) if isinstance(f, tuple) else (f['label'], f['value'])
                                for f in fact_list
                            )
                        ]
                    else:
                        r['facts'] = []
            table = pa.Table.from_pylist(chunk, schema=schema)
            writer.write_table(table, row_group_size=row_group_size)
            del table
            if clear_rows:
                for r in chunk:
                    if isinstance(r, dict):
                        r.clear()
                if rows:
                    rows[start:start + row_group_size] = [None] * len(raw_chunk)


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
    def _batch_tables():
        sub_rows = []
        sub_bytes = 0
        for row_dict in rows:
            r_bytes = sum(len(v) if isinstance(v, str) else 32 for v in row_dict.values())
            if sub_rows and (len(sub_rows) >= SOURCE_ROW_GROUP or sub_bytes + r_bytes > 3_500_000):
                yield pa.Table.from_pylist(sub_rows, schema=SOURCE_SCHEMA)
                sub_rows = []
                sub_bytes = 0
            sub_rows.append(row_dict)
            sub_bytes += r_bytes
        if sub_rows:
            yield pa.Table.from_pylist(sub_rows, schema=SOURCE_SCHEMA)

    batches = _batch_tables()
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
                writer.write_table(pending, row_group_size=max(1, pending.num_rows))
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
    appearance_omitted = set(SCHEMA.names) - set(TABLE_SCHEMAS['appearance'].names)
    issue_omitted = (set(SCHEMA.names) - set(TABLE_SCHEMAS['data_issue'].names)) - {'subject'}
    for row in query_rows:
        rkind = row['kind']
        if rkind == 'appearance':
            populated = sorted(name for name in appearance_omitted if row.get(name) not in (None, '', [], {}))
            if populated:
                raise ValueError(f"appearance {row['id']} has populated fields outside its table schema: {populated}")
            rows['appearance'][row['id']] = (
                row['id'],
                row.get('title'),
                row.get('congress'),
                row.get('chamber'),
                row.get('date'),
                row.get('meeting_id'),
                tuple(row.get('committee_ids') or ()),
                tuple(row.get('roles') or ()),
                None,
                None,
                None,
                None,
                None,
                (),
                (),
            )
            continue
        if rkind == 'data_issue':
            populated = sorted(name for name in issue_omitted if row.get(name) not in (None, '', [], {}))
            if populated:
                raise ValueError(f"data_issue {row['id']} has populated fields outside its table schema: {populated}")
            subj = row.get('subject')
            subj_kind = row.get('subject_kind') or (subj.get('kind') if isinstance(subj, dict) else None)
            subj_id = row.get('subject_id') or (subj.get('id') if isinstance(subj, dict) else None)
            rows['data_issue'][row['id']] = [
                row['id'],
                row.get('title'),
                row.get('congress'),
                row.get('chamber'),
                row.get('date'),
                row.get('status'),
                row.get('meeting_id'),
                row.get('category'),
                row.get('selection'),
                tuple(row.get('committee_ids') or ()),
                subj_kind,
                subj_id,
                None,
                None,
                (),
                (),
            ]
            continue
        row = {k: v for k, v in row.items() if v is not None and k not in ('issue_count', 'committee_types')}
        if rkind != 'committee_term':
            row.pop('committee_level', None)
        rows[rkind][row['id']] = row
    all_issues_have_subject = bool(rows['data_issue']) and all(
        r[10] is not None and r[11] is not None for r in rows['data_issue'].values()
    )
    track_all_owners = not all_issues_have_subject
    needed_owners = (
        None
        if track_all_owners
        else {
            (r[10], r[11])
            for r in rows['data_issue'].values()
            if r[10] not in rows
        }
    )
    versions, formats, links, occurrences, subjects = {}, defaultdict(list), [], defaultdict(list), {}
    context_records, meeting_subjects, conflict_facts, owners = {}, [], {}, {}
    amendment_groups = defaultdict(list)
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
            facts = [('Selected value', display(value))]
            facts += [(f'Alternative {i + 1}', display(alt['value'])) for i, alt in enumerate(field['alternatives'])]
            if field.get('selection_reason'): facts.append(('Selection reason', field['selection_reason']))
            conflict_facts[(kind, id, field['path'])] = facts
        if kind not in rows:
            if track_all_owners or (kind, id) in needed_owners:
                owner = record.get('material') or record.get('version') or record.get('meeting') or (record.get('subject') if kind == 'assessment' else None)
                if owner:
                    owner_pair = (owner['kind'], owner['id'])
                    owners[(kind, id)] = owner_pair
                    if owner_pair[0] == 'material_version' and owner_pair[1] in versions:
                        owners[owner_pair] = ('material', versions[owner_pair[1]][0])
                    elif needed_owners is not None and owner_pair[0] not in rows:
                        needed_owners.add(owner_pair)
        # Every meeting-owned subject uses its explicit meeting reference.
        if (kind != 'appearance' or id not in rows['appearance']) and record.get('meeting'):
            subjects[id] = record['meeting']['id']
        if kind == 'legislative_item':
            context_records[id] = {
                'kind': 'legislative_item',
                'item_type': record.get('item_type'),
                'designation': record.get('designation'),
                'description': record.get('description'),
                'label': record.get('label'),
            }
        elif kind == 'person':
            context_records[id] = {
                'kind': 'person',
                'name': record.get('name'),
                'identifiers': record.get('identifiers', ()),
            }
        elif kind == 'amendment_group':
            for member in record.get('members', ()):
                amendment_groups[member['id']].append(record['label'])
        elif kind in ('amendment', 'vote'):
            context_records[id] = record
        elif kind == 'meeting_subject':
            item = context_records.get(record['item']['id'])
            if item is not None:
                row = rows['meeting'].get(record['meeting']['id'])
                if row is not None:
                    row.setdefault('facts', []).append(('Related ' + item['item_type'], item['designation']))
                    row.setdefault('source_ids', []).extend(sources_of(record))
            else:
                meeting_subjects.append(record)
        if kind in rows and id in rows[kind]:
            row = rows[kind][id]
            provenance = record.get('provenance', {})
            if kind == 'appearance':
                affiliation = record.get('affiliation') or {}
                pos = affiliation.get('position')
                org = affiliation.get('organization_name')
                part = record.get('participation')
                s_text = ' '.join(str(v) for v in (row[1], pos, org) if v)
                f_list = []
                for key in ('on_behalf_of', 'location'):
                    if affiliation.get(key):
                        f_list.append((key.replace('_', ' '), affiliation[key]))
                rows['appearance'][id] = (
                    row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7],
                    pos, org, part, s_text, provenance.get('explanation'),
                    tuple(f_list), tuple(sorted(sources_of(record))),
                )
            elif kind == 'data_issue':
                row[12] = record.get('impact')
                row[13] = record.get('explanation')
                row[10] = record['subject']['kind']
                row[11] = record['subject']['id']
                f_list = []
                for key in ('expected', 'detected_at', 'last_checked_at', 'field_path'):
                    value = record.get(key)
                    if isinstance(value, dict): value = value.get('date')
                    if value: f_list.append((key.replace('_', ' '), value))
                if record.get('resolution'):
                    f_list.append(('Resolution', record['resolution']['explanation']))
                row[14] = tuple(f_list)
                row[15] = tuple(sorted(sources_of(record)))
            else:
                sids = sources_of(record)
                if sids:
                    prev_sids = row.get('source_ids')
                    row['source_ids'] = [*prev_sids, *sids] if prev_sids else sorted(sids)
                if provenance.get('explanation') is not None:
                    row['explanation'] = provenance['explanation']
            if kind == 'committee_term':
                parent = (record.get('parent') or {}).get('id')
                committee_type = record.get('committee_type')
                row['committee_type'] = committee_type or 'unknown'
                row['source_committee_type'] = record.get('source_committee_type')
                row['parent_committee_id'] = parent
                for key, label in (('start', 'Active from'), ('end', 'Active through')):
                    value = (record.get('active') or {}).get(key)
                    if value: row.setdefault('facts', []).append((label, value))
                if record.get('website'):
                    row.setdefault('facts', []).append(('Official website or archive', record['website']))
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
                            row.setdefault('facts', []).append(('Committee hierarchy', 'The source identifies a parent committee.'))
                        elif row['committee_level'] == level:
                            row.setdefault('facts', []).append(('Committee hierarchy', f'Congress.gov systemCode {code}: final two digits 00 identify a full committee; other digits identify a subcommittee.'))
                            row.setdefault('facts', []).append(('Hierarchy definition', HIERARCHY_SOURCE))
                elif parent:
                    row.setdefault('facts', []).append(('Committee hierarchy', 'The source identifies a parent committee.'))
            if kind == 'meeting':
                row['access'] = record.get('access') if record.get('access') not in (None, 'unknown') else 'unknown'
                start = record.get('scheduled_start') or {}
                if start:
                    row['scheduled_at'] = start.get('original') or start.get('date')
                assembled_type = record.get('meeting_type')
                if assembled_type not in (None, 'unknown', 'meeting'):
                    row['type'] = assembled_type
                if record.get('source_type'):
                    row.setdefault('facts', []).append(('Source type', record['source_type']))
                for field in record.get('field_evidence') or []:
                    if field.get('path') == '/meeting_type' and field.get('selection_reason'):
                        row.setdefault('facts', []).append(('Type based on', field['selection_reason']))
            if kind == 'material':
                dates = record.get('proceeding_dates') or []
                if not row.get('date') and dates:
                    row['date'] = min(d['date'] for d in dates)
                if record.get('document_type'): row['document_type'] = record['document_type']
                if record.get('source_document_groups'): row['source_document_groups'] = tuple(record['source_document_groups'])
                files_list = []
                for file in record.get('files') or ():
                    if not file.get('url'): continue
                    version = file.get('version_label')
                    if version and version.rstrip('.') in PLACEHOLDER_LABELS: version = None
                    published_at = file.get('published_at') or {}
                    if row.get('type') == 'recording' and not row.get('date') and published_at.get('date'):
                        row['date'] = published_at['date']
                    files_list.append((file['url'], file.get('format_label') or file.get('media_type') or file.get('role'),
                                       file.get('role'), file.get('media_type'), version,
                                       published_at.get('date'), file.get('sha256'),
                                       file.get('saved_copy_sha256'), file.get('saved_filename')))
                if files_list:
                    row['files'] = tuple(files_list)
                if not row.get('title') or row['title'] == '(Untitled source record)':
                    row['title'] = (row.get('category') if row.get('category') not in (None, 'unknown') else row.get('type') or 'Document').replace('_', ' ').capitalize()
                for k in ('medium', 'coverage', 'production'):
                    value = record.get('details', {}).get(k)
                    if value and value != 'unknown': row.setdefault('facts', []).append((k, value))
        elif kind == 'material_version':
            versions[id] = [record['material']['id'], record.get('label'), record.get('published_at'), tuple(sources_of(record))]
        elif kind == 'representation':
            vid = record['version']['id']
            v_entry = versions.get(vid)
            if v_entry is not None and v_entry[0] in rows['material']:
                material_id, label, published, version_sources = v_entry
                row = rows['material'][material_id]
                if row.get('type') == 'recording' and not row.get('date') and published:
                    row['date'] = published['date']
                if label and label.rstrip('.') in PLACEHOLDER_LABELS:
                    label = None
                sids_list = row.setdefault('source_ids', [])
                if version_sources:
                    sids_list.extend(version_sources)
                    v_entry[3] = ()
                sids_list.extend(sources_of(record))
                if not isinstance(row.get('files'), tuple):
                    for location in record.get('locations', []):
                        row.setdefault('files', []).append((location['url'], record.get('format_label') or record.get('media_type') or location['role'],
                                                            location['role'], record.get('media_type'), label,
                                                            (published or {}).get('date'), record.get('sha256'),
                                                            record.get('saved_copy_sha256'), record.get('saved_filename')))
            else:
                file_info = {key: record[key] for key in ('locations', 'format_label', 'media_type', 'sha256', 'saved_copy_sha256', 'saved_filename') if key in record}
                file_info['source_ids'] = sources_of(record)
                formats[vid].append(file_info)
        elif kind == 'material_link':
            if versions and not formats:
                versions.clear()
            mat_id = record['material']['id']
            subj_kind = record['subject']['kind']
            subj_id = record['subject']['id']
            link_sources = tuple(sources_of(record))
            mat_row = rows['material'].get(mat_id)
            if mat_row is not None and (
                subj_kind in ('meeting', 'committee_term')
                or (subj_kind == 'appearance' and subj_id in rows['appearance'])
            ):
                meeting_id = (
                    subj_id if subj_kind == 'meeting'
                    else (rows['appearance'][subj_id][5] if isinstance(rows['appearance'][subj_id], tuple) else rows['appearance'][subj_id].get('meeting_id')) if subj_kind == 'appearance'
                    else None
                )
                if meeting_id: mat_row.setdefault('meeting_ids', []).append(meeting_id)
                if subj_kind == 'committee_term': mat_row['committee_ids'] = (*(mat_row.get('committee_ids') or ()), subj_id)
                if subj_kind == 'appearance': mat_row.setdefault('appearance_ids', []).append(subj_id)
                if link_sources: mat_row.setdefault('source_ids', []).extend(link_sources)
            else:
                links.append((mat_id, subj_kind, subj_id, link_sources))
        elif kind == 'occurrence':
            start = record.get('scheduled_start') or {}
            loc_facts = tuple(
                (key.replace('_', ' '), val)
                for key, val in (record.get('location') or {}).items()
                if isinstance(val, str) and val
            )
            access_reasons = tuple(
                f['selection_reason']
                for f in (record.get('field_evidence') or ())
                if f.get('path') == '/access' and f.get('selection_reason')
            )
            occurrences[record['meeting']['id']].append((
                start.get('date', '9999'),
                start.get('original') or start.get('date'),
                loc_facts,
                record.get('access'),
                access_reasons,
                tuple(sources_of(record)),
            ))
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
        embedded = isinstance(row.get('files'), tuple)
        sids_list = row.setdefault('source_ids', [])
        for record in entries:
            sids_list.extend(version_sources)
            sids_list.extend(record['source_ids'])
            if embedded: continue
            for location in record.get('locations', []):
                row.setdefault('files', []).append((location['url'], record.get('format_label') or record.get('media_type') or location['role'],
                                                    location['role'], record.get('media_type'), label,
                                                    (published or {}).get('date'), record.get('sha256'),
                                                    record.get('saved_copy_sha256'), record.get('saved_filename')))
    del versions, formats, needed_owners
    attached_actions = set()
    for material_id, kind, id, source_ids in links:
        row = rows['material'].get(material_id)
        if row is None: continue
        meeting_id = (
            id if kind == 'meeting'
            else (rows['appearance'][id][5] if isinstance(rows['appearance'][id], tuple) else rows['appearance'][id].get('meeting_id')) if kind == 'appearance' and id in rows['appearance']
            else subjects.get(id)
        )
        if meeting_id: row.setdefault('meeting_ids', []).append(meeting_id)
        if kind == 'committee_term': row['committee_ids'] = (*(row.get('committee_ids') or ()), id)
        if kind == 'appearance': row.setdefault('appearance_ids', []).append(id)
        if source_ids: row.setdefault('source_ids', []).extend(source_ids)
        if kind in ('amendment', 'vote') and id in context_records:
            attached_actions.add(id)
            action = context_records[id]
            for key in ('number', 'question', 'description', 'disposition', 'outcome', 'method'):
                value = action.get(key)
                if value and value != 'unknown' and value != row['title']:
                    row.setdefault('facts', []).append((f'{kind.capitalize()} {key}', value))
            target = context_records.get((action.get('target') or action.get('subject') or {}).get('id'), {})
            title = target.get('designation') or target.get('description') or target.get('label')
            if title: row.setdefault('facts', []).append(('Regarding', title))
            for sponsor in action.get('sponsors', []):
                person = context_records.get((sponsor.get('person') or {}).get('id'), {})
                name = sponsor.get('name') or person.get('name')
                if name: row.setdefault('facts', []).append(('Sponsor', name))
                else:
                    for identifier in person.get('identifiers', []):
                        if identifier['scheme'] == 'bioguide': row.setdefault('facts', []).append(('Sponsor Bioguide ID', identifier['value']))
            for label in amendment_groups[id]: row.setdefault('facts', []).append(('En bloc group', label))
            for label, value in (action.get('tally') or {}).items():
                if value is not None: row.setdefault('facts', []).append((label.replace('_', ' '), str(value)))
    for record in meeting_subjects:
        row = rows['meeting'].get(record['meeting']['id'])
        item = context_records.get(record['item']['id'])
        if row is not None and item:
            row.setdefault('facts', []).append(('Related ' + item['item_type'], item['designation']))
            # The agenda association cites this meeting's source. A shared bill
            # also has citations from other meetings; those do not describe this one.
            row.setdefault('source_ids', []).extend(sources_of(record))
    for id, action in context_records.items():
        if action['kind'] not in ('amendment', 'vote') or id in attached_actions: continue
        row = rows['meeting'].get(action['meeting']['id'])
        if row is not None:
            label = f"{action['kind'].capitalize()} {action.get('number') or ''}".strip()
            row.setdefault('facts', []).append((label, (action.get('description') or action.get('question') or 'Listed action') + ' (no attached file)'))
            row.setdefault('source_ids', []).extend(sources_of(action))
    del links, context_records, meeting_subjects, subjects, amendment_groups, attached_actions
    for id, entries in occurrences.items():
        row = rows['meeting'].get(id)
        if row is None: continue
        for _, sched_at, loc_facts, occ_access, access_reasons, occ_sources in sorted(entries, key=itemgetter(0)):
            if occ_sources:
                row.setdefault('source_ids', []).extend(occ_sources)
            if sched_at and not row.get('scheduled_at'):
                row['scheduled_at'] = sched_at
            if loc_facts:
                row.setdefault('facts', []).extend(loc_facts)
            if row.get('access') in (None, 'unknown') and occ_access not in (None, 'unknown'):
                row['access'] = occ_access
            if row.get('access') not in (None, 'unknown'):
                for reason in access_reasons:
                    if not any((fact[0] if isinstance(fact, tuple) else fact['label']) == 'Access based on' for fact in (row.get('facts') or ())):
                        row.setdefault('facts', []).append(('Access based on', reason))
    del occurrences
    for row in rows['material'].values():
        m_ids = row.get('meeting_ids')
        if m_ids:
            if len(set(m_ids)) == 1:
                row['meeting_id'] = m_ids[0]
            meetings = [rows['meeting'][id] for id in m_ids if id in rows['meeting']]
            if meetings:
                active = [r for r in meetings if r.get('status') not in ('canceled', 'postponed', 'not_held')]
                first = min(active or meetings, key=lambda r: r.get('scheduled_at') or r.get('date') or '9999')
                if first.get('scheduled_at') is not None:
                    row['scheduled_at'] = first['scheduled_at']
                if first.get('status') is not None:
                    row['meeting_status'] = first['status']
        if row.get('type') == 'recording':
            def _f_url(file):
                return file[0] if isinstance(file, tuple) else file['url']
            def preference(file):
                f_url = _f_url(file)
                url = urlsplit(f_url)
                return (0 if url.hostname in ('www.senate.gov', 'senate.gov') and url.path.startswith('/isvp') else
                        1 if url.hostname in ('www.youtube.com', 'youtube.com', 'youtu.be') else 2, f_url)
            candidates = sorted((f for f in (row.get('files') or ()) if not _event_page(_f_url(f))), key=preference)
            if candidates:
                row['recording_url'] = _f_url(candidates[0])
    issue_counts = Counter()
    for issue in rows['data_issue'].values():
        facts = issue[14]
        field = next((f[1] for f in facts if f[0] == 'field path'), None)
        subject = (issue[10], issue[11])
        disagreement = conflict_facts.get((*subject, field), ())
        if disagreement:
            facts = (*facts, *disagreement)
        compared = [f[1] for f in disagreement if f[0] == 'Selected value' or f[0].startswith('Alternative ')]
        if issue[5] == 'open' and subject[0] == 'material_version' and field == '/label' and collector_placeholder_conflict(compared):
            issue[5] = 'dismissed'
            issue[1] = 'Collector placeholder labels differed'
            issue[13] = 'Collectors assigned different internal edition labels. This is not evidence of a disagreement in source content.'
            facts = (*facts, ('Display correction', 'Automatically dismissed by the Parquet exporter; original values retained below.'))
        issue[14] = facts
        visited = set()
        while subject in owners and subject not in visited:
            visited.add(subject)
            subject = owners[subject]
        if subject[0] in rows and subject[1] in rows[subject[0]]:
            issue[10], issue[11] = subject
            if issue[5] == 'open':
                issue_counts[subject] += 1
    del conflict_facts, owners
    gc.collect()
    committee_rows = rows['committee_term']
    for id, parent_code in committee_parents.items():
        row = committee_rows[id]
        if not row.get('parent_committee_id'): row['parent_committee_id'] = committee_codes.get(parent_code)
    def effective_committee_type(id, seen=()):
        if id in seen: return 'unknown'
        committee = committee_rows.get(id, {})
        native_type = committee.get('committee_type')
        if native_type not in (None, 'unknown', 'subcommittee'):
            return native_type
        if committee.get('committee_level') == 'subcommittee':
            return effective_committee_type(committee.get('parent_committee_id'), (*seen, id))
        return 'unknown'
    written_details = {}
    write_order = ('material', 'data_issue', 'appearance', 'meeting', 'committee_term')
    for kind in [k for k in write_order if k in rows] + [k for k in list(rows.keys()) if k not in write_order]:
        entries = rows.pop(kind)
        kind_lists = tuple(k for k in LISTS if k in TABLE_COLUMNS[kind] and k != 'committee_types')
        if kind == 'appearance':
            values = sorted(entries.values(), key=lambda t: (t[2] or 0, t[0]))
            entries.clear()
            def _prep_appearance(t):
                cids = t[6]
                levels = {committee_rows.get(cid, {}).get('committee_level', 'unknown') for cid in cids}
                return {
                    'id': t[0], 'kind': 'appearance', 'title': t[1], 'congress': t[2],
                    'chamber': t[3], 'date': t[4], 'meeting_id': t[5],
                    'committee_ids': sorted(set(cids)), 'roles': sorted(set(t[7])),
                    'position': t[8], 'organization': t[9], 'participation': t[10],
                    'search_text': t[11], 'explanation': t[12], 'facts': t[13],
                    'source_ids': sorted(set(t[14])), 'issue_count': issue_counts[('appearance', t[0])],
                    'committee_types': sorted({effective_committee_type(cid) for cid in cids}) or ['unknown'],
                    'committee_level': 'subcommittee' if 'subcommittee' in levels else 'full' if levels == {'full'} else 'unknown',
                }
            prepare_fn = _prep_appearance
        elif kind == 'data_issue':
            values = sorted(entries.values(), key=lambda t: (t[2] or 0, t[0]))
            entries.clear()
            def _prep_issue(t):
                cids = t[9]
                levels = {committee_rows.get(cid, {}).get('committee_level', 'unknown') for cid in cids}
                return {
                    'id': t[0], 'kind': 'data_issue', 'title': t[1], 'congress': t[2],
                    'chamber': t[3], 'date': t[4], 'status': t[5], 'meeting_id': t[6],
                    'category': t[7], 'selection': t[8], 'committee_ids': sorted(set(cids)),
                    'subject_kind': t[10], 'subject_id': t[11], 'severity': t[12],
                    'explanation': t[13], 'facts': t[14], 'source_ids': sorted(set(t[15])),
                    'issue_count': issue_counts[('data_issue', t[0])],
                    'committee_types': sorted({effective_committee_type(cid) for cid in cids}) or ['unknown'],
                    'committee_level': 'subcommittee' if 'subcommittee' in levels else 'full' if levels == {'full'} else 'unknown',
                }
            prepare_fn = _prep_issue
        else:
            values = sorted(entries.values(), key=lambda r: (r.get('congress') or 0, r['id']))
            if kind != 'committee_term':
                entries.clear()
            omitted = set(SCHEMA.names) - set(TABLE_SCHEMAS[kind].names)
            for row in values:
                populated = sorted(name for name in omitted if row.get(name) not in (None, '', (), [], {}))
                if populated:
                    raise ValueError(f"{kind} {row['id']} has populated fields outside its table schema: {populated}")
            def _prep_dict(row, _kind=kind, _klists=kind_lists):
                cids = row.get('committee_ids') or ()
                row['issue_count'] = issue_counts[(_kind, row['id'])]
                row['committee_types'] = sorted({effective_committee_type(cid) for cid in cids}) or ['unknown']
                if _kind != 'committee_term':
                    levels = {committee_rows.get(cid, {}).get('committee_level', 'unknown') for cid in cids}
                    row['committee_level'] = 'subcommittee' if 'subcommittee' in levels else 'full' if levels == {'full'} else 'unknown'
                for key in _klists:
                    row[key] = sorted(set(row.get(key) or ()))
                return row
            prepare_fn = _prep_dict
        path = TABLES[kind] + '.parquet'
        row_count = len(values)
        _write_table(values, TABLE_SCHEMAS[kind], Path(stage) / path, row_group_size=2048, prepare_row=prepare_fn, clear_rows=(kind != 'committee_term'))
        if (Path(stage) / path).stat().st_size >= FILE_LIMIT:
            raise ValueError(f'{path} exceeds GitHub file limit; partition this table before publishing')
        written_details[kind] = (path, row_count)
        del values
        gc.collect()
    del committee_rows
    for kind in TABLES:
        if kind in written_details:
            path, row_count = written_details[kind]
            descriptor(path, 'details', 'committee_explorer.parquet.' + kind, row_count, media_type='application/vnd.apache.parquet')
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
    def consume_query_rows():
        # Run write_queries only after write_tables has finished streaming sources.parquet,
        # so 910k query row dicts are not held in RAM during _write_sources.
        write_queries(catalog, current, collect, evidence_states=evidence_states, paginate=False)
        while query_rows:
            yield query_rows.popleft()
    # Assembly already orders sources by ID; SpilledSourceSequence streams them in
    # ascending ID order without materializing a sorted list in RAM.
    if hasattr(catalog.sources, 'iter_json_dicts'):
        ordered_source_dicts = catalog.sources.iter_json_dicts()
    elif getattr(catalog.sources, 'is_id_sorted', False):
        ordered_source_dicts = (s.model_dump(mode='json') for s in catalog.sources)
    else:
        ordered_source_dicts = (s.model_dump(mode='json') for s in sorted(catalog.sources, key=attrgetter('id')))
    retained_source_dicts = (
        s if isinstance(s, dict) else s.model_dump(mode='json')
        for s in retained_sources
    )
    source_dicts = merge(ordered_source_dicts, retained_source_dicts, key=itemgetter('id'))
    record_dicts = (
        catalog.records.iter_json_dicts()
        if hasattr(catalog.records, 'iter_json_dicts')
        else (r.model_dump(mode='json') for r in catalog.records)
    )
    write_tables(record_dicts,
                 source_dicts, consume_query_rows(), stage, descriptor)
    info.pop('partitions', None)
    info.update(storage='parquet', query_columns=QUERY_COLUMNS)
    write('queries.json', info, 'index', 'committee_explorer.queries', len(info['kinds']))

