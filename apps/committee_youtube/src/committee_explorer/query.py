"""Scoped query rows and index metadata for Committee Explorer Parquet tables."""
from collections import Counter, defaultdict
import json
import sys

from committee_meeting import SCHEMA_VERSION

KINDS = ('committee_term', 'meeting', 'appearance', 'material', 'data_issue')


def write_queries(catalog, current, write, *, evidence_states=None, paginate=True):
    records = catalog.records.as_mapping() if hasattr(catalog.records, 'as_mapping') else {(r.kind, r.id): r for r in catalog.records}
    material_subjects = {}
    scope_info = {}
    scope_cache = {}
    committee_terms = {}
    appearance_meetings = {}
    occurrence_meetings = {}
    dates, statuses, witness_names, issue_counts = {}, {}, defaultdict(set), Counter()
    committee_labels = {}

    def _add_material_subject(mat_id, subj_kind, subj_id):
        pair = (sys.intern(subj_kind), subj_id)
        existing = material_subjects.get(mat_id)
        if existing is None:
            material_subjects[mat_id] = pair
        elif isinstance(existing, tuple):
            if existing != pair:
                material_subjects[mat_id] = [existing, pair]
        elif pair not in existing:
            existing.append(pair)

    def _record_info(record):
        target = getattr(record, 'meeting', None)
        if target is None and record.kind in ('data_issue', 'assessment', 'material_link'):
            target = record.subject
        if target is None and record.kind == 'material_version':
            target = record.material
        if target is None and record.kind == 'representation':
            target = record.version
        target_key = (target.kind, target.id) if target else None
        committees = (
            tuple(c.committee.id for c in record.committees)
            if record.kind == 'meeting'
            else (record.id,)
            if record.kind == 'committee_term'
            else ()
        )
        return (
            getattr(record, 'congress', None),
            getattr(record, 'chamber', 'unknown'),
            record.id if record.kind == 'meeting' else None,
            committees,
            target_key,
        )

    if hasattr(catalog.records, 'iter_kind'):
        for record in catalog.records.iter_kind('committee_term'):
            committee_terms[record.id] = record
            committee_labels[record.id] = record.name or 'Committee name not recorded'
            scope_cache[('committee_term', record.id)] = (
                record.congress,
                record.chamber,
                None,
                (record.id,),
            )
        for record in catalog.records.iter_kind('meeting'):
            scope_cache[('meeting', record.id)] = (
                record.congress,
                record.chamber,
                record.id,
                tuple(c.committee.id for c in record.committees),
            )
            if record.scheduled_start:
                dates.setdefault(record.id, sys.intern(record.scheduled_start.date.isoformat()))
                if record.status != 'unknown':
                    statuses.setdefault(record.id, sys.intern(record.status))
        for record in catalog.records.iter_kind('occurrence'):
            occurrence_meetings[record.id] = record.meeting.id
            if record.scheduled_start:
                dates.setdefault(record.meeting.id, sys.intern(record.scheduled_start.date.isoformat()))
                statuses.setdefault(record.meeting.id, sys.intern(record.status))
        for record in catalog.records.iter_kind('appearance'):
            appearance_meetings[record.id] = record.meeting.id
            witness_names[record.meeting.id].add(record.name.display)
        for record in catalog.records.iter_kind('material_link'):
            _add_material_subject(record.material.id, record.subject.kind, record.subject.id)
        if paginate:
            for record in catalog.records.iter_kind('data_issue'):
                if record.status == 'open':
                    issue_counts[(record.subject.kind, record.subject.id)] += 1
    else:
        for record in catalog.records:
            key = (record.kind, record.id)
            scope_info[key] = _record_info(record)
            if record.kind == 'material_link':
                _add_material_subject(record.material.id, record.subject.kind, record.subject.id)
            elif record.kind == 'occurrence' and record.scheduled_start:
                dates.setdefault(record.meeting.id, sys.intern(record.scheduled_start.date.isoformat()))
                statuses.setdefault(record.meeting.id, sys.intern(record.status))
            elif record.kind == 'meeting' and record.scheduled_start:
                dates.setdefault(record.id, sys.intern(record.scheduled_start.date.isoformat()))
                if record.status != 'unknown':
                    statuses.setdefault(record.id, sys.intern(record.status))
            elif record.kind == 'appearance':
                witness_names[record.meeting.id].add(record.name.display)
            elif record.kind == 'data_issue' and record.status == 'open':
                issue_counts[(record.subject.kind, record.subject.id)] += 1
            elif record.kind == 'committee_term':
                committee_terms[record.id] = record
                committee_labels[record.id] = record.name or 'Committee name not recorded'

    def scope_for_key(key, trail=(), record_obj=None):
        if key in scope_cache:
            return scope_cache[key]
        if key in trail:
            return (None, 'unknown', None, ())
        if key[0] == 'appearance' and key[1] in appearance_meetings:
            m_key = ('meeting', appearance_meetings[key[1]])
            return scope_for_key(m_key, (*trail, key)) if m_key in records else (None, 'unknown', None, ())
        if key[0] == 'occurrence' and key[1] in occurrence_meetings:
            m_key = ('meeting', occurrence_meetings[key[1]])
            return scope_for_key(m_key, (*trail, key)) if m_key in records else (None, 'unknown', None, ())
        if key[0] == 'material':
            if record_obj is None and key not in records:
                return (None, 'unknown', None, ())
            subjects_for_mat = material_subjects.get(key[1])
            if not subjects_for_mat:
                return (None, 'unknown', None, ())
            subject_iter = (subjects_for_mat,) if isinstance(subjects_for_mat, tuple) else sorted(subjects_for_mat)
            linked = [
                scope_for_key(t, (*trail, key))
                for t in subject_iter
                if t in records
            ]
            linked_congresses = {s[0] for s in linked}
            linked_chambers = {s[1] for s in linked}
            linked_meetings = {s[2] for s in linked if s[2] is not None}
            congress = next(iter(linked_congresses)) if len(linked_congresses) == 1 else None
            chamber = next(iter(linked_chambers)) if len(linked_chambers) == 1 else 'unknown'
            meeting_id = next(iter(linked_meetings)) if len(linked_meetings) == 1 else None
            committees = tuple(sorted({committee for s in linked for committee in s[3]}))
            result = (congress, chamber, meeting_id, committees)
            scope_cache[key] = result
            return result
        info = scope_info.get(key)
        if info is None:
            rec = record_obj if record_obj is not None else records.get(key)
            if rec is None:
                return (None, 'unknown', None, ())
            info = _record_info(rec)
        congress, chamber, meeting_id, committees, target_key = info
        if target_key and target_key in records:
            congress, chamber, meeting_id, committees = scope_for_key(target_key, (*trail, key))
        result = (congress, chamber, meeting_id, committees)
        scope_cache[key] = result
        return result

    def scope(record):
        return scope_for_key((record.kind, record.id), record_obj=record)

    def committee_level(record):
        if not record: return 'unknown'
        if record.committee_level not in (None, 'unknown'): return record.committee_level
        if record.parent or record.committee_type == 'subcommittee': return 'subcommittee'
        return 'full' if record.committee_type != 'unknown' else 'unknown'
    def committee_type(id, seen=()):
        record = committee_terms.get(id)
        if not record or id in seen: return 'unknown'
        if record.committee_type not in ('unknown', 'subcommittee'): return record.committee_type
        return committee_type(record.parent.id, (*seen, id)) if record.parent else 'unknown'
    partitions, counts, congresses = [], Counter(), set()
    pages, sizes, numbers = defaultdict(list), defaultdict(int), Counter()
    def flush(group):
        if not pages[group]: return
        kind, congress = group
        path = f'queries/{kind}/{congress or "unknown"}/{numbers[group]:04d}.json'
        rows = pages.pop(group)
        write(path, {'schema_version': SCHEMA_VERSION, 'rows': rows}, 'search', 'committee_explorer.query-rows', len(rows), congress=congress)
        partitions.append({'kind': kind, 'congress': congress, 'path': path, 'record_count': len(rows)})
        sizes[group] = 0
        numbers[group] += 1
    query_records = (
        (r for kind in sorted(KINDS) for r in catalog.records.iter_kind(kind))
        if hasattr(catalog.records, 'iter_kind')
        else (r for r in catalog.records if r.kind in KINDS)
    )
    for record in query_records:
        is_current = (record.kind, record.id) in current
        # Unchecked or omitted source records cannot silently remove an issue
        # from Quality. Its retained subject and evidence remain inspectable.
        if not is_current and record.kind != 'data_issue': continue
        congress, chamber, meeting_id, committees = scope(record)
        title = getattr(record, 'title', None) or getattr(record, 'summary', None) or getattr(record, 'name', None)
        if record.kind == 'appearance': title = record.name.display
        if record.kind == 'committee_term': title = record.name or 'Committee name not recorded'
        details = getattr(record, 'details', None)
        if paginate:
            row = {'id': record.id, 'kind': record.kind, 'title': title or '(Untitled source record)',
                   'congress': congress, 'chamber': chamber, 'date': dates.get(meeting_id),
                   'type': getattr(record, 'meeting_type', None) or getattr(details, 'type', None),
                   'status': getattr(record, 'status', None), 'committee_ids': list(committees), 'meeting_id': meeting_id,
                   'issue_count': issue_counts[(record.kind, record.id)]}
            for field in ('provider', 'category'):
                value = getattr(record, field, None) or getattr(details, field, None)
                if value: row[field] = value
            row['committee_types'] = sorted({committee_type(id) for id in committees}) or ['unknown']
            levels = {committee_level(committee_terms.get(id)) for id in committees}
            row['committee_level'] = 'subcommittee' if 'subcommittee' in levels else 'full' if levels == {'full'} else 'unknown'
            if record.kind == 'appearance': row['roles'] = list(record.roles)
            if record.kind == 'committee_term':
                row['committee_code'] = record.committee_code or next((i.value for i in record.identifiers if i.scheme == 'congress.gov:committee'), None)
                row['parent_committee_id'] = record.parent.id if record.parent else None
                row['committee_type'] = record.committee_type
                row['source_committee_type'] = record.source_committee_type
            if record.kind == 'data_issue':
                row['subject'] = record.subject.model_dump(mode='json')
                if not is_current: row['selection'] = 'retained_history'
            if record.kind == 'meeting':
                row['status'] = statuses.get(record.id)
                row['evidence_states'] = (evidence_states or {}).get(record.id, {})
                row['search_text'] = ' '.join((row['title'], *sorted(witness_names.pop(record.id, ()))))
        else:
            row = {
                'id': record.id,
                'kind': record.kind,
                'title': title or '(Untitled source record)',
                'chamber': chamber,
            }
            if congress is not None:
                row['congress'] = congress
            date_val = dates.get(meeting_id)
            if date_val is not None:
                row['date'] = date_val
            type_val = getattr(record, 'meeting_type', None) or getattr(details, 'type', None)
            if type_val is not None:
                row['type'] = type_val
            status_val = statuses.get(record.id) if record.kind == 'meeting' else getattr(record, 'status', None)
            if status_val is not None:
                row['status'] = status_val
            if committees:
                row['committee_ids'] = committees
            if meeting_id is not None:
                row['meeting_id'] = meeting_id
            for field in ('provider', 'category'):
                value = getattr(record, field, None) or getattr(details, field, None)
                if value:
                    row[field] = value
            if record.kind == 'appearance' and record.roles:
                row['roles'] = record.roles
            elif record.kind == 'committee_term':
                code = record.committee_code or next((i.value for i in record.identifiers if i.scheme == 'congress.gov:committee'), None)
                if code:
                    row['committee_code'] = code
                if record.parent:
                    row['parent_committee_id'] = record.parent.id
                row['committee_type'] = record.committee_type
                if record.source_committee_type:
                    row['source_committee_type'] = record.source_committee_type
            elif record.kind == 'data_issue':
                row['subject_kind'] = record.subject.kind
                row['subject_id'] = record.subject.id
                if not is_current:
                    row['selection'] = 'retained_history'
            elif record.kind == 'meeting':
                row['evidence_states'] = (evidence_states or {}).get(record.id, {})
                row['search_text'] = ' '.join((row['title'], *sorted(witness_names.pop(record.id, ()))))
        group = (record.kind, congress)
        if paginate:
            size = len(json.dumps(row, ensure_ascii=False).encode())
            if pages[group] and (sizes[group] + size > 256 * 1024 or len(pages[group]) >= 1000): flush(group)
            sizes[group] += size
        elif len(pages[group]) >= 1000:
            flush(group)
        pages[group].append(row); counts[record.kind] += 1
        if congress: congresses.add(congress)
    material_subjects.clear()
    appearance_meetings.clear()
    occurrence_meetings.clear()
    scope_cache.clear()
    scope_info.clear()
    witness_names.clear()
    dates.clear()
    statuses.clear()
    issue_counts.clear()
    committee_terms.clear()
    for group in sorted(pages, key=lambda g:(g[0],g[1] or 0)): flush(group)
    write('indexes/queries.json', {'schema_version': SCHEMA_VERSION, 'default_congress': max(congresses, default=None),
          'kinds': [{'kind': k, 'count': counts[k]} for k in KINDS], 'congresses': sorted(congresses, reverse=True),
          'committee_labels': committee_labels,
          'partitions': partitions}, 'index', 'committee_explorer.queries', len(partitions))

