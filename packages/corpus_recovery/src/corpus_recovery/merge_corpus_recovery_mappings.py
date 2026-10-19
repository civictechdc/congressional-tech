"""Merge only this recovery pass's additions into a freshly read mapping.

This module performs no network calls. The publisher must validate rows with
the maintained viewer validator and conditionally write against the ETag of
the fresh mapping, then read it back before advancing the viewer pointer.
"""
from copy import deepcopy


def merge_mappings(baseline, prepared, fresh):
    def index(document):
        if document.get('version') != 1:
            raise ValueError('Unsupported recovery mapping version')
        result = {}
        for row in document['recoveries']:
            url = row['original_url']
            if url in result:
                raise ValueError('Duplicate recovery URL: ' + url)
            result[url] = row
        return result

    before, desired, current = map(index, (baseline, prepared, fresh))
    # This pass adds recoveries; it does not edit or remove previous decisions.
    for url, row in before.items():
        if desired.get(url) != row:
            raise ValueError('Prepared mapping changes a baseline recovery: ' + url)
    additions = {url: row for url, row in desired.items() if url not in before}
    for url, row in additions.items():
        if url in current and current[url] != row:
            raise ValueError('Fresh mapping conflicts with new recovery: ' + url)
    result = deepcopy(fresh)
    # Fresh edits and deletions of old mappings remain authoritative.
    result['recoveries'] = [deepcopy(row) for _, row in
                            sorted((current | additions).items())]
    return result
