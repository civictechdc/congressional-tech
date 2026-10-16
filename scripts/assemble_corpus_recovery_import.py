"""Assemble retained recovery receipts without network access or state mutation.

The caller supplies fresh download state and verified remote body metadata.
Cloud checks, locking, conditional writes, and readback remain caller duties.
"""
from copy import deepcopy
from collections.abc import Mapping
from itertools import chain
import json


class PreservedStates(Mapping):
    """Copy only requested rows; keep the supplied baseline out of Python copies.

    Existing rows are copied on first access, so editing a returned state cannot
    mutate the caller's baseline. New URLs are appended in first-seen order.
    """
    def __init__(self, baseline):
        self.baseline = baseline
        self.accessed = {}
        self.added = {}

    def __getitem__(self, url):
        if url in self.added:
            return self.added[url]
        if url not in self.accessed:
            self.accessed[url] = deepcopy(self.baseline[url])
        return self.accessed[url]

    def __iter__(self):
        return chain(self.baseline, self.added)

    def __len__(self):
        return len(self.baseline) + len(self.added)

    def setdefault(self, url, value):
        if url not in self.baseline and url not in self.added:
            self.added[url] = value
        return self[url]


def assemble(prepared, existing_states, verified_bodies, source_file):
    states = PreservedStates(existing_states)
    receipts = []
    for item in prepared:
        if item.get('preserve_download_state') is not True:
            raise ValueError('Recovery must preserve download state')
        record = deepcopy(item['record'])
        url = record['url']
        if not any(a.get('original_url') == item['original_url']
                   for a in record.get('source_associations', [])):
            raise ValueError('Missing original source association')
        if not item['captures']:
            raise ValueError('Recovery has no captures')
        state = states.setdefault(url, dict(
            url=url, family='documents', outcome='pending', body_key=None,
            sha256=None, media_type=None, fidelity=None, retrieved_at=None,
            checked_at=None, next_attempt_at=None, http_status=None,
            attempts=0, links_scanned=False))
        captures = []
        for original in item['captures']:
            cap = deepcopy(original)
            info = verified_bodies[cap['body_key']]
            for field in ('body_key', 'sha256', 'bytes'):
                if cap[field] != info[field]:
                    raise ValueError(f'Verified body mismatch: {field}')
            if not info.get('stored_sha256') or not isinstance(info.get('stored_bytes'), int):
                raise ValueError('Missing verified stored-body metadata')
            if cap['context_url'] != url:
                raise ValueError('Capture source differs from receipt source')
            node = record
            for part in cap['pointer'][:-1]:
                node = node[part]
            if cap['pointer'][-1] != 'body' or node['sha256'] != cap['sha256']:
                raise ValueError('Capture pointer does not identify the retained body')
            if cap['pointer'][0] == 'archive_members':
                member = record['archive_members'][cap['pointer'][1]]
                if (member['original_name'] != cap.get('original_path')
                        or member['parent_archive_body_key'] != item['captures'][0]['body_key']):
                    raise ValueError('ZIP member parent or filename mismatch')
            cap.update(stored_sha256=info['stored_sha256'], stored_bytes=info['stored_bytes'],
                       family='documents')
            captures.append(cap)
        receipts.append(dict(source_file=source_file, source_line=None, record=record,
                             captures=captures, preserve_download_state=True,
                             download_state=deepcopy(state)))
    return receipts, states


def index_rows(receipts, receipt_key):
    """Index every retained capture; historical availability is not retry state."""
    rows = []
    for line, receipt in enumerate(receipts, 1):
        for cap in receipt['captures']:
            rows.append(dict(
                cap, capture_date=receipt['record']['retrieved_at'][:10],
                source_file=receipt['source_file'], source_line=receipt.get('source_line'),
                receipt_key=receipt_key, receipt_line=line, reference_kind='capture',
                pointer_json=json.dumps(cap['pointer']), resolution='saved'))
    return rows
