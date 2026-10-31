"""Read a pinned campaign descriptor without loading its metadata tables.

Consumers must call ``require_custody`` after using the tables, before committing
any effect based on them. A fresh process must load and verify the descriptor again.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from congress_shared.custody import bounded_control_read, verify_local_file

REQUIREMENTS = frozenset({'historical_exact', 'requested_content', 'current_official_counterpart'})
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')


@dataclass(frozen=True)
class Campaign:
    campaign_id: str
    requirement: str
    tables: dict
    target_table: str
    candidate_table: str
    descriptor_sha256: str

    def require_custody(self):
        """Refuse use after any verified local metadata table has changed."""
        for identity in self.tables.values():
            identity.require(identity.path)

    def table_path(self, name):
        if name not in self.tables:
            raise ValueError(f'Unknown campaign table: {name}')
        self.tables[name]._require_custody(self.tables[name].path)
        return self.tables[name].path


def load_campaign(path):
    """Verify exact metadata bytes before exposing campaign table paths.

    Paths are resolved relative to the descriptor. SHA-256 pins are mandatory;
    a changed pin requires a new descriptor and a new campaign decision.
    """
    path = Path(path)
    # Digest the same control-document bytes that are parsed.
    with path.open('rb') as stream:
        raw = bounded_control_read(stream)
    from hashlib import sha256
    descriptor_sha256 = sha256(raw).hexdigest()
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {
        'version', 'campaign_id', 'requirement', 'tables', 'target_table', 'candidate_table'
    } or type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Invalid campaign descriptor')
    if not isinstance(value['campaign_id'], str) or not value['campaign_id'].strip():
        raise ValueError('Campaign identity is required')
    if not isinstance(value['requirement'], str) or value['requirement'] not in REQUIREMENTS:
        raise ValueError('Unsupported target requirement')
    tables = value['tables']
    if not isinstance(tables, dict) or not tables:
        raise ValueError('Pinned campaign tables are required')
    if (not isinstance(value['target_table'], str) or not isinstance(value['candidate_table'], str)
            or value['target_table'] not in tables or value['candidate_table'] not in tables
            or value['target_table'] == value['candidate_table']):
        raise ValueError('Distinct target and candidate tables are required')
    result = {}
    for name, pin in tables.items():
        if (not isinstance(name, str) or not name or not isinstance(pin, dict)
                or set(pin) != {'path', 'sha256'} or not isinstance(pin['path'], str)
                or not pin['path'] or not isinstance(pin['sha256'], str)
                or not _SHA256.fullmatch(pin['sha256'])):
            raise ValueError('Invalid campaign table pin')
        table_path = Path(pin['path'])
        if not table_path.is_absolute():
            table_path = path.parent / table_path
        result[name] = verify_local_file(table_path, expected_sha256=pin['sha256'])
    return Campaign(value['campaign_id'], value['requirement'], result,
                    value['target_table'], value['candidate_table'], descriptor_sha256)
