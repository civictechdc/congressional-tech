"""Bounded browse pages and inverse domain links for static site readers."""
from collections import Counter, defaultdict
from hashlib import sha256
import json

from committee_meeting import SCHEMA_VERSION
from committee_meeting.catalog import _references

KINDS = ('committee_term', 'meeting', 'appearance', 'material', 'data_issue')


def write_queries(catalog, current, write, *, evidence_states=None, include_relations=True):
    records = {(r.kind, r.id): r for r in catalog.records}
    material_subjects = defaultdict(set)
    for record in catalog.records:
        if record.kind == 'material_link':
            material_subjects[record.material.id].add((record.subject.kind, record.subject.id))
    scope_cache = {}
    def scope(record, trail=()):
        key = (record.kind, record.id)
        if key in scope_cache: return scope_cache[key]
        if key in trail: return (None, 'unknown', None, ())
        congress, chamber = getattr(record, 'congress', None), getattr(record, 'chamber', 'unknown')
        meeting = record if record.kind == 'meeting' else None
        target = getattr(record, 'meeting', None)
        if target is None and record.kind in ('data_issue', 'assessment', 'material_link'): target = record.subject
        if target is None and record.kind == 'material_version': target = record.material
        if target is None and record.kind == 'representation': target = record.version
        if target and (parent := records.get((target.kind, target.id))):
            inherited = scope(parent, (*trail, key))
            congress, chamber, meeting_id, committees = inherited
        else:
            meeting_id = meeting.id if meeting else None
            committees = tuple(c.committee.id for c in meeting.committees) if meeting else ()
            if record.kind == 'committee_term': committees = (record.id,)
        if record.kind == 'material':
            linked = [scope(records[target], (*trail, key))
                      for target in sorted(material_subjects[record.id]) if target in records]
            # A shared volume can support several committees without supplying
            # a unique meeting/date. Unknown scopes participate in consensus.
            linked_congresses = {s[0] for s in linked}
            linked_chambers = {s[1] for s in linked}
            linked_meetings = {s[2] for s in linked if s[2] is not None}
            if congress is None and len(linked_congresses) == 1: congress = next(iter(linked_congresses))
            if chamber == 'unknown' and len(linked_chambers) == 1: chamber = next(iter(linked_chambers))
            meeting_id = next(iter(linked_meetings)) if len(linked_meetings) == 1 else None
            committees = tuple(sorted({committee for s in linked for committee in s[3]}))
        result = (congress, chamber, meeting_id, committees)
        scope_cache[key] = result
        return result
    dates, statuses, witness_names, issue_counts = {}, {}, defaultdict(set), Counter()
    relations = defaultdict(lambda: defaultdict(dict))
    def relate(target, record, relation):
        key = target.kind + '/' + target.id
        if target.kind == 'source_record': return
        bucket = sha256(key.encode()).hexdigest()[:2]
        value = {'kind': record.kind, 'id': record.id, 'relation': relation}
        relations[bucket][key][(record.kind, record.id, relation)] = value
    for record in catalog.records:
        if record.kind == 'occurrence' and record.scheduled_start:
            dates.setdefault(record.meeting.id, record.scheduled_start.date.isoformat())
            statuses.setdefault(record.meeting.id, record.status)
        if record.kind == 'appearance': witness_names[record.meeting.id].add(record.name.display)
        if record.kind == 'data_issue' and record.status == 'open': issue_counts[(record.subject.kind, record.subject.id)] += 1
        # Inverse links let views find appearances/materials/issues without
        # scanning the graph. Exclude citation and field-evidence trees.
        for field in type(record).model_fields if include_relations else ():
            if field in ('provenance', 'field_evidence', 'identifiers'): continue
            for target in _references(getattr(record, field)):
                relate(target, record, field)
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
    for record in catalog.records:
        if record.kind not in KINDS: continue
        is_current = (record.kind, record.id) in current
        # Unchecked or omitted source records cannot silently remove an issue
        # from Quality. Its retained subject and evidence remain inspectable.
        if not is_current and record.kind != 'data_issue': continue
        congress, chamber, meeting_id, committees = scope(record)
        title = getattr(record, 'title', None) or getattr(record, 'summary', None) or getattr(record, 'name', None)
        if record.kind == 'appearance': title = record.name.display
        if record.kind == 'committee_term': title = record.name or 'Committee name not recorded'
        details = getattr(record, 'details', None)
        row = {'id': record.id, 'kind': record.kind, 'title': title or '(Untitled source record)',
               'congress': congress, 'chamber': chamber, 'date': dates.get(meeting_id),
               'type': getattr(record, 'meeting_type', None) or getattr(details, 'type', None),
               'status': getattr(record, 'status', None), 'committee_ids': list(committees), 'meeting_id': meeting_id,
               'issue_count': issue_counts[(record.kind, record.id)]}
        for field in ('provider', 'category'):
            value = getattr(record, field, None) or getattr(details, field, None)
            if value: row[field] = value
        if record.kind == 'appearance': row['roles'] = list(record.roles)
        if record.kind == 'data_issue':
            row['subject'] = record.subject.model_dump(mode='json')
            if not is_current: row['selection'] = 'retained_history'
        if record.kind == 'meeting':
            row['status'] = statuses.get(record.id)
            row['evidence_states'] = (evidence_states or {}).get(record.id, {})
            row['search_text'] = ' '.join((row['title'], *sorted(witness_names[record.id])))
        group = (record.kind, congress)
        size = len(json.dumps(row, ensure_ascii=False).encode())
        if pages[group] and (sizes[group] + size > 256 * 1024 or len(pages[group]) >= 1000): flush(group)
        pages[group].append(row); sizes[group] += size; counts[record.kind] += 1
        if congress: congresses.add(congress)
    for group in sorted(pages, key=lambda g:(g[0],g[1] or 0)): flush(group)
    write('indexes/queries.json', {'schema_version': SCHEMA_VERSION, 'default_congress': max(congresses, default=None),
          'kinds': [{'kind': k, 'count': counts[k]} for k in KINDS], 'congresses': sorted(congresses, reverse=True),
          'committee_labels': {r.id: r.name or 'Committee name not recorded' for r in catalog.records if r.kind == 'committee_term'},
          'partitions': partitions}, 'index', 'committee_explorer.queries', len(partitions))
    if not include_relations: return
    buckets = {}
    for bucket, entries in sorted(relations.items()):
        path = f'indexes/relations/{bucket}.json'
        values = {key: list(v.values()) for key,v in sorted(entries.items())}
        write(path, {'schema_version': SCHEMA_VERSION, 'relations': values}, 'index', 'committee_explorer.relation-bucket', len(values))
        buckets[bucket] = path
    write('indexes/relations.json', {'schema_version': SCHEMA_VERSION, 'key_format': '<kind>/<id>',
          'bucket_algorithm': 'sha256-prefix-2', 'buckets': buckets}, 'index', 'committee_explorer.relations', len(buckets))
