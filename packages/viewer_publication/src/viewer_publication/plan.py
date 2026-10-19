"""One accepted viewer plan; inventory issuance owns its in-process custody."""
from dataclasses import dataclass, replace
from pathlib import Path
import json

from congress_api.retention.viewer_inventory import InventoryValidation, issue_inventory


@dataclass(frozen=True)
class AcceptedViewerPlan:
    root: Path
    manifest: dict
    protected: dict
    source_pins: dict
    release_plan: dict
    conditions: dict
    mode: str
    recovery: dict
    files: dict
    validation: InventoryValidation

    def context(self):
        return dict(root=str(self.root), manifest=self.manifest, protected=self.protected,
                    source_pins=self.source_pins, release_plan=self.release_plan,
                    conditions=self.conditions, mode=self.mode, recovery=self.recovery,
                    files={name: str(path) for name, path in self.files.items()})

    def require(self, root, manifest):
        if Path(root).resolve() != self.root or manifest != self.manifest:
            raise ValueError('Accepted viewer plan belongs to different prepared output')
        self.validation.require(self.validation.root, context=self.context())
        return self


def accept_viewer_plan(publisher, root, manifest, *, validation, context, protected,
                       source_pins, release_plan, conditions, mode='full'):
    """Wrap existing file/status acceptance; never infer artifact or resume authority.

    Cloud callers still verify their preparation receipt and GitHub artifact.
    Local callers still own pins, lock, phase acceptance and original conditions.
    Reissuing the existing file proofs binds these plan values without hashing
    unchanged files again. Callers admit supported output sizes before issuing
    inventory proof; serialized dictionaries cannot issue an inventory.
    """
    root = Path(root).resolve()
    if not isinstance(validation, InventoryValidation):
        raise ValueError('Accepted viewer plan requires an issued inventory')
    validation.require(validation.root, context=context)
    validation.file(root / 'manifest.json')
    if json.loads((root / 'manifest.json').read_bytes()) != manifest:
        raise ValueError('Accepted viewer manifest differs from its verified file')
    if mode not in ('full', 'recovery'):
        raise ValueError('Unsupported accepted viewer mode')
    if (manifest['source_manifest'] != protected['source'][0]
            or set(conditions) != {'selected_etag', 'previous_etag'}
            or not conditions['selected_etag']
            or conditions['selected_etag'] != protected['source'][1]
            or conditions['previous_etag'] != protected['viewer'][1]):
        raise ValueError('Accepted viewer plan source or original conditions changed')
    files = publisher.prepared_files(root, manifest, validation=validation) if mode == 'full' else {}
    recovery = publisher.load_prepared_recovery(root, manifest, protected['accepted'], validation=validation)
    plan = AcceptedViewerPlan(root, manifest, protected, source_pins, release_plan, conditions,
                              mode, recovery, files, validation)
    proof = issue_inventory(validation.root, validation.identities, context=plan.context())
    return replace(plan, validation=proof)
