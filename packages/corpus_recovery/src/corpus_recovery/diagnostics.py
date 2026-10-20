"""Describe retained catalog evidence without opening it or granting resume authority."""
from pathlib import Path


def catalog_build_observation(root, phases):
    root = Path(root).absolute()
    incremental = (root / 'catalog-update').exists()
    build = root / ('catalog-update' if incremental else 'build')
    if not build.exists() and not build.is_symlink():
        return None
    order = ('catalog', 'mappings', 'prepared', 'publication')
    last = None
    for phase in order:
        if phase not in phases:
            break
        last = phase
    accepted = 'catalog' in phases
    return dict(
        state='catalog_acceptance_recorded' if accepted else 'incomplete_catalog_requires_reconciliation',
        retained_build_path=str(build),
        last_recorded_accepted_phase=last,
        integrity_rechecked=False, remote_reconciliation='not_performed',
        resume_authorized=False, publication_complete=False,
        next_read_only_checks=[
            dict(path=str(root / 'continuation.json'),
                 check='Compare binding.pins and pins.json with the current code, configuration, batch and completed import; changed pins must remain a refusal.'),
            dict(path=str(build if incremental else build / 'working.sqlite'),
                 check=('Inspect retained request, candidate results and native receipts; preserve originals and diagnose the last failed incremental operation.'
                        if incremental else 'Inspect retained SQLite, working.sqlite-wal and working.sqlite-shm together on a separate copy; preserve the originals and diagnose the last failed catalog operation.')),
            dict(path=str(root / 'source/indexes/catalog.json'),
                 check=('Verify the saved native selector, selected_identity, exact scope proof and imported-body coverage; missing or incomplete outputs remain unaccepted.'
                        if incremental else 'If present, verify the saved catalog pair byte counts, SHA256, catalog_id and imported-body coverage with validate_catalog_pair; missing or incomplete outputs remain unaccepted.')),
            dict(path=str(root / 'continuation.json'),
                 check='Read each recorded remote write in full and compare bytes and original conditions; HEAD or phase metadata alone cannot resolve an uncertain write.'),
        ],
    )
