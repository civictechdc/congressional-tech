"""Build the small synthetic, model-validated dataset used by the design preview."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'packages/committee_meeting/src'), str(ROOT / 'packages/committee_meeting/examples')]
from committee_meeting import Catalog
from worked_catalog import worked_catalog, reference

data = worked_catalog().model_dump(mode='json', exclude_none=True)
records = data['records']
evidence = records[0]['provenance']


def row(id):
    return next(r for r in records if r['id'] == id)


def add(kind, id, **fields):
    records.append(dict(kind=kind, id=id, provenance=evidence, **fields))


row('committee-a')['label'] = row('term-a')['name'] = 'Committee on Infrastructure'
row('committee-b')['label'] = row('term-b')['name'] = 'Committee on Science and Technology'
row('hearing')['title'] = 'Keeping public infrastructure resilient'
row('markup')['title'] = 'Clean energy research and development'
row('witness-a')['affiliation'] = {'organization_name': 'Public Infrastructure Institute', 'position': 'Research director'}
row('witness-b')['affiliation'] = {'organization_name': 'Regional Planning Council', 'position': 'Policy director'}
row('print')['congress'] = 119
row('print')['chamber'] = 'house'
row('print')['proceeding_dates'] = [{'date': '2026-09-01'}, {'date': '2026-09-02'}]
row('print-hearing')['coverage'] = 'full'
row('print-markup')['coverage'] = 'partial'
row('archive-video').update(congress=119, chamber='senate', proceeding_dates=[{'date': '2026-09-08'}])
row('day-1')['access'] = row('day-2')['access'] = 'open'
add('occurrence', 'markup-day', meeting=reference('meeting', 'markup'), status='held', access='open', actual_start={'date': '2026-09-03'})
add('committee', 'committee-s', label='Committee on Public Administration')
add('committee_term', 'term-s', committee=reference('committee', 'committee-s'), congress=119,
    name='Committee on Public Administration', chamber='senate')
for id, title, chamber, day, status in [
    ('oversight', 'Oversight of federal data systems', 'senate', '2026-09-08', 'held'),
    ('budget', 'Fiscal year 2027 transportation budget', 'house', '2026-09-14', 'canceled'),
    ('water', 'Water systems and regional preparedness', 'house', '2026-09-29', 'scheduled'),
    ('permits', 'Modernizing public permitting', 'senate', '2026-09-18', 'postponed'),
]:
    add('meeting', id, title=title, congress=119, chamber=chamber, meeting_type='hearing',
        committees=[dict(committee=reference('committee_term', 'term-s' if chamber == 'senate' else 'term-a'),
                         role='host', provenance=evidence)])
    add('occurrence', id+'-day', meeting=reference('meeting', id), status=status, access='open',
        **{('actual_start' if status == 'held' else 'scheduled_start'): {'date': day}})

add('assessment', 'oversight-text-check', subject=reference('meeting', 'oversight'), aspect='transcript',
    status='not_found', scope='Publisher attachment list', provider='Synthetic committee source',
    observed_at={'date': '2026-09-26'}, evaluated_at='2026-09-27T12:00:00Z')
add('assessment', 'hearing-witness-check', subject=reference('meeting', 'hearing'), aspect='witnesses',
    status='unknown', scope='Attendance verification', evaluated_at='2026-09-27T12:00:00Z')
row('hearing')['field_evidence'] = [{
    'path': '/title', 'selected': evidence,
    'alternatives': [{'value': 'Regional infrastructure preparedness', 'provenance': evidence}],
    'selection_reason': 'Publisher title displayed; disagreement remains unresolved in this example.',
}]

for id, subject, category, summary, explanation, extra in [
    ('title-conflict', reference('meeting', 'hearing'), 'conflicting', 'Source titles disagree',
     'Two source observations use different titles. The display title is selected; neither source is declared incorrect.', {'field_path': '/title'}),
    ('attendance-check', reference('meeting', 'hearing'), 'unverified', 'Attendance has not been verified',
     'The witness list names two people. It does not establish that either appeared or testified.', {}),
    ('missing-transcript', reference('meeting', 'oversight'), 'missing', 'Listed transcript attachment not found',
     'In this synthetic case, a publisher notice lists a transcript but its attachment list contains no file at the dated check.',
     {'expected': 'The synthetic publisher notice explicitly lists a transcript.', 'last_checked_at': {'date': '2026-09-26'}}),
    ('unlinked-video', reference('material', 'archive-video'), 'unlinked', 'Recording has no confirmed meeting match',
     'The date suggests a candidate, but there is not enough evidence to associate the recording with that proceeding.', {}),
    ('stale-markup', reference('meeting', 'markup'), 'stale', 'Amendment attachments need a fresh check',
     'The last successful observation predates a publisher update. Current attachments may differ.', {'last_checked_at': {'date': '2026-09-04'}}),
]:
    add('data_issue', id, subject=subject, category=category, summary=summary, explanation=explanation,
        detected_at='2026-09-27T12:00:00Z', **extra)
add('data_issue', 'corrected-time', subject=reference('occurrence', 'day-1'), category='incorrect',
    field_path='/actual_start', status='resolved', summary='Scheduled time had been shown as the actual start',
    explanation='The time was removed; only the supported date is retained in this synthetic record.',
    detected_at='2026-09-25T12:00:00Z', resolution={
        'decided_at': '2026-09-26T12:00:00Z', 'explanation': 'Restored a date-only value. Actual start time remains unknown.', 'provenance': evidence})

catalog = Catalog.model_validate(data)
target = Path(__file__).with_suffix('.json')
target.write_text(catalog.model_dump_json(indent=2, exclude_none=True) + '\n')
print(json.dumps({'path': str(target), 'schema': catalog.schema_version, 'records': len(catalog.records), 'synthetic': True}))
