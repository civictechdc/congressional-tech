"""Retain a downloaded GovInfo package without broadening recovery mappings."""
from collections import defaultdict
import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path

from congress_api.models.content import CapturedBody
from congress_api.retention.archive_members import ZipLimits
from congress_api.retention.raw_archive import prepare_capture


def _read_bounded(path, limit):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'GovInfo package input exceeds read limit: {path}')
    return raw


def prepare_packages(recoveries, input_hashes):
    """Expand each acquisition once; retain ZIP, every member and exact receipt.

    Existing retained-body recoveries have no local acquisition to expand. Their
    selected document remains sufficient; this operation never fetches a package.
    """
    groups = defaultdict(list)
    for row in recoveries:
        if row.get('package_id') and row.get('archive_member'):
            if not row.get('request_evidence'):
                raise ValueError('GovInfo package member lacks acquisition receipt')
            groups[Path(row['request_evidence']).resolve()].append(row)
    prepared = []
    for path, rows in groups.items():
        raw_receipt = _read_bounded(path, 1024**2)
        receipt_sha = hashlib.sha256(raw_receipt).hexdigest()
        input_hashes[str(path)] = receipt_sha
        receipt = json.loads(raw_receipt)
        package_id = receipt['package_id']
        url = f'https://www.govinfo.gov/content/pkg/{package_id}.zip'
        response = receipt['record']
        if (receipt.get('outcome') != 'saved' or response.get('complete') is not True
                or response.get('http_status') != 200
                or response.get('url') != url or response.get('requested_url') != url):
            raise ValueError('GovInfo package receipt is incomplete or identifies another source')
        at = datetime.fromisoformat(response['retrieved_at'].replace('Z', '+00:00'))
        if at.tzinfo is None:
            raise ValueError('GovInfo package capture time lacks timezone')
        parent_path = Path(response['local_body_path']).resolve()
        raw = _read_bounded(parent_path, ZipLimits().max_archive_bytes)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != response['content']['sha256'] or digest != response['body_sha256']:
            raise ValueError('GovInfo package ZIP identity mismatch')
        members = {member['name']: member for member in receipt['members']}
        if len(members) != len(receipt['members']) or not members:
            raise ValueError('GovInfo package receipt has duplicate or missing members')
        for row in rows:
            member = members.get(row['archive_member'], {})
            if (row['package_id'] != package_id or member.get('status') != 'completed'
                    or row['recovered_url'] != 'https://www.govinfo.gov/content/pkg/' + row['archive_member']
                    or not row['archive_member'].startswith(package_id + '/')
                    or (row['sha256'], row['bytes']) != (member.get('sha256'), member.get('bytes'))):
                raise ValueError('Selected recovery differs from its GovInfo package member')
        response = dict(response,
            content=CapturedBody.from_bytes(raw, 'application/zip').source_dict(),
            publisher_requested=False,
            # A self-reference satisfies receipt assembly without transferring any
            # committee document's identity to its ZIP or to sibling members.
            source_associations=[dict(original_url=url, basis='retained_package')],
            recovery_package=dict(package_id=package_id, acquisition_receipt_sha256=receipt_sha,
                                  acquisition_receipt_path=str(path),
                                  # Preserve exact receipt bytes inside the import
                                  # receipt, without indexing them as a document.
                                  acquisition_receipt_base64=base64.b64encode(raw_receipt).decode('ascii')))
        record, captures, bodies, _ = prepare_capture(
            response, outcome='saved', links=[], mode='retained_import')
        expanded = record.get('archive_members', [])
        if (record.get('archive_processing', {}).get('status') != 'completed'
                or len(expanded) != len(members)
                or {m['original_name'] for m in expanded} != set(members)
                or any(m['status'] != 'completed' for m in expanded)):
            raise ValueError('GovInfo package extraction is incomplete')
        local = {}
        for capture in captures:
            pointer = capture['pointer']
            if pointer == ['content', 'body']:
                body_path = parent_path
            elif pointer[0] == 'archive_members':
                member = members[capture['original_path']]
                if (member.get('status') != 'completed'
                        or (member['sha256'], member['bytes']) != (capture['sha256'], capture['bytes'])):
                    raise ValueError('GovInfo package member differs from acquisition receipt')
                body_path = Path(member['path']).resolve()
            else:
                raise ValueError('Unexpected GovInfo package capture')
            with body_path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != capture['sha256'] or body_path.stat().st_size != capture['bytes']:
                raise ValueError(f'GovInfo package local body changed: {body_path}')
            local.setdefault(capture['body_key'], str(body_path))
        if set(local) != set(bodies):
            raise ValueError('GovInfo package body inventory is incomplete')
        prepared.append(dict(original_url=url, record=record, captures=captures,
                             local_bodies=local, preserve_download_state=True))
    return prepared
