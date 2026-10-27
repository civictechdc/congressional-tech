"""One catalog policy; Basin performs compaction and snapshot expiration."""
import json
from pathlib import Path
import re

import requests

POLICY=Path(__file__).resolve().parents[5]/'model/basin-maintenance.json'


class MaintenanceError(RuntimeError):
    """Configuration was refused or its effective state is unconfirmed."""


def _request(session,method,url,**kwargs):
    try:
        response=session.request(method,url,timeout=30,allow_redirects=False,**kwargs)
        if not 200<=response.status_code<300:
            raise MaintenanceError('Basin maintenance request refused')
        value=response.json()
    except (requests.RequestException,ValueError):
        raise MaintenanceError('Basin maintenance request failed; effective state is unconfirmed') from None
    if not isinstance(value,dict) or value.get('success') is not True or not isinstance(value.get('result'),dict):
        raise MaintenanceError('Basin maintenance response did not confirm success')
    return value['result']


def _current(session,url):
    value=_request(session,'GET',url)
    if value.get('credential_status')!='present':
        raise MaintenanceError('Basin maintenance service credential is absent')
    policy=value.get('maintenance_config')
    if not isinstance(policy,dict):
        raise MaintenanceError('Basin maintenance configuration is missing')
    return policy


def _matches(current,desired):
    return all(isinstance(current.get(section),dict)
        and all(current[section].get(key)==value for key,value in fields.items())
        for section,fields in desired.items())


def configure(account_id,bucket,*,execute=False,session=None):
    """Plan without I/O; explicitly apply through an injected authenticated client.

    Uses O(1) small metadata requests per catalog. An uncertain write is never
    retried here; a later invocation reads current state before choosing work.
    Live enablement requires the owner's M1 verdict and service setup.
    """
    if (not isinstance(account_id,str) or re.fullmatch('[a-fA-F0-9]{32}',account_id) is None
            or not isinstance(bucket,str) or re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',bucket) is None):
        raise ValueError('Explicit Cloudflare account ID and bucket name are required')
    desired=json.loads(POLICY.read_text())
    url=f'https://api.cloudflare.com/client/v4/accounts/{account_id}/basin-catalog/{bucket}/maintenance-configs'
    report=dict(status='planned',endpoint=url,policy=desired)
    if not execute:return report
    if session is None:raise ValueError('Apply requires an explicit authenticated client')
    if _matches(_current(session,url),desired):
        return dict(report,status='unchanged')
    _request(session,'POST',url,json=desired)
    if not _matches(_current(session,url),desired):
        raise MaintenanceError('Basin maintenance readback differs from the requested policy')
    return dict(report,status='updated')
