"""Retired managed-maintenance entry point; local policy only, no provider I/O."""
import json
from pathlib import Path
import re

POLICY=Path(__file__).resolve().parents[5]/'model/basin-maintenance.json'


class MaintenanceError(RuntimeError):
    """Managed maintenance activation was refused by local project policy."""


def configure(account_id,bucket,*,execute=False,session=None):
    """Report the local disabled policy, without observing remote configuration.

    The public spelling remains for old callers. Execution refuses before any
    client access: application-owned generation rebuilds replace managed
    compaction and expiration (ARCH 8.6). No HTTP or credential dependency is
    needed. This O(1) metadata report makes no claim about remote service state.
    """
    if (not isinstance(account_id,str) or re.fullmatch('[a-fA-F0-9]{32}',account_id) is None
            or not isinstance(bucket,str) or re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',bucket) is None):
        raise ValueError('Explicit Cloudflare account ID and bucket name are required')
    if execute:
        raise MaintenanceError('Managed Basin maintenance is disabled by local project policy; '
            'use the application-owned generation rebuild helper '
            'congress_api.lake.maintenance.rebuild_generation')
    return dict(status='disabled_by_local_policy',remote_state='not_observed',
        endpoint=f'https://api.cloudflare.com/client/v4/accounts/{account_id}/basin-catalog/{bucket}/maintenance-configs',
        policy=json.loads(POLICY.read_text()),
        replacement='congress_api.lake.maintenance.rebuild_generation')
