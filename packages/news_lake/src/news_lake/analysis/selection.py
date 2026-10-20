"""C8 owner: processor selections for a release.

select_runs(records, selections): for each (input, processor), select the
LATEST successful run by (finished_at, id) whose (processor,
processor_version, config_hash) triple matches the release-pinned selection.
A later zero-output successful run REPLACES an earlier one's outputs — the
selection is over runs, so "what the release believes" is whatever that run
produced, including nothing. Inputs touched only by non-matching or
unsuccessful runs stay visibly pending; they are returned, never dropped.
Pending extraction inputs must be capturable (a succeeded, non-metadata-only
capture) and pending clustering inputs must carry text, so records no
processor could consume are not reported as work waiting to happen.
current_version_id is NOT derived here: items explicitly select their text
(C8); this selector governs run-level processors such as mention linking and
clustering.
"""
from news_lake.context import parse_instant


# Processors whose default input kind is 'capture' rather than 'version'.
CAPTURE_PROCESSORS = frozenset({'extract'})
# Version processors that operate on extracted body text and therefore cannot
# consume metadata-only (text-less) versions.
TEXT_REQUIRED_VERSION_PROCESSORS = frozenset({
    'cluster',
    'cluster-identical-text',
    'classify',
    'classify-keywords',
})


def _eligible_pending(processor, kind, identifier, captures, versions):
    """Whether this processor could actually consume this pending input."""
    if processor in CAPTURE_PROCESSORS and kind == 'capture':
        capture = captures.get(identifier)
        if capture is None:  # unreferenced record: no evidence it is ineligible
            return True
        return capture.get('status') == 'succeeded' and capture.get('access') != 'metadata_only'
    if processor in TEXT_REQUIRED_VERSION_PROCESSORS and kind == 'version':
        version = versions.get(identifier)
        if version is None:
            return True
        return 'text' in version
    return True


def select_runs(records, selections):
    """Returns {'assignments': {(processor, kind, id): run_id},
    'pending': [(processor, kind, id), ...]}."""
    pinned = {
        (selection['processor'], selection['processor_version'], selection['config_hash'])
        for selection in selections
    }
    runs = [record for record in records if record.get('kind') == 'run']
    captures = {record['id']: record for record in records if record.get('kind') == 'capture'}
    versions = {record['id']: record for record in records if record.get('kind') == 'version'}
    candidates = {}  # processor -> every input key any run of that processor touched
    input_kinds = {}  # processor -> input kinds consumed by that processor
    for run in runs:
        for ref in run['inputs']:
            candidates.setdefault(run['processor'], set()).add((ref['kind'], ref['id']))
            input_kinds.setdefault(run['processor'], set()).add(ref['kind'])
    for processor, _, _ in pinned:
        kinds = input_kinds.get(processor) or ({'capture'} if processor in CAPTURE_PROCESSORS else {'version'})
        for record in records:
            if record.get('kind') in kinds:
                candidates.setdefault(processor, set()).add((record['kind'], record['id']))

    best = {}
    for run in runs:
        if run['status'] != 'succeeded':
            continue
        if (run['processor'], run['processor_version'], run['config_hash']) not in pinned:
            continue
        rank = (parse_instant(run['finished_at']), run['id'])
        for ref in run['inputs']:
            key = (run['processor'], ref['kind'], ref['id'])
            if key not in best or rank > best[key][0]:
                best[key] = (rank, run['id'])

    assignments = {key: run_id for key, (rank, run_id) in best.items()}
    pending = sorted(
        (processor, kind, identifier)
        for processor, keys in candidates.items()
        for (kind, identifier) in keys
        if (processor, kind, identifier) not in assignments
        and _eligible_pending(processor, kind, identifier, captures, versions)
    )
    return {'assignments': assignments, 'pending': pending}
