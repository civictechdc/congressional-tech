"""Use one accepted native producer proof for the model's input bindings."""
from hashlib import sha256
import json
from pathlib import Path


def read_producer_proof(pin):
    """Read the pinned native result once; DDK verifies its retained evidence."""
    from ddk.adapters.docspec import DEFAULT_CAPTURE_BYTES
    from ddk.docspec_job_evidence import verify_completed_job

    if (not isinstance(pin, dict) or set(pin) != {'path', 'sha256', 'size'}
            or type(pin['size']) is not int or not 0 < pin['size'] <= DEFAULT_CAPTURE_BYTES):
        raise ValueError('Model producer proof requires a pinned native receipt within the DDK metadata limit')
    with Path(pin['path']).open('rb') as stream:
        raw = stream.read(pin['size'] + 1)
    if len(raw) != pin['size'] or sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('Model producer proof differs from its original receipt identity')
    proof = verify_completed_job(json.loads(raw), require_accepted=True)
    require_producer_proof(proof)
    return proof


def read_producer_definition(pin, proof):
    """Resolve the exact adopted definition, including its original input order."""
    from ddk.documents import freeze_json
    from viewer_publication.archive_format import _read_preparation_artifact

    require_producer_proof(proof)
    raw = _read_preparation_artifact(pin)
    if pin['sha256'] != proof.manifest['producer_evidence']['adoption']['definition_sha256']:
        raise ValueError('Producer definition differs from the accepted proof adoption')
    return freeze_json(json.loads(raw))


def require_producer_proof(proof):
    """A model requires accepted producer evidence, not an arbitrary completion."""
    from ddk.docspec_job_evidence import VerifiedJobEvidence

    if (not isinstance(proof, VerifiedJobEvidence) or proof.accepted is None
            or proof.manifest.get('profile') != 'urn:docspec:whole-job-completion:3'
            or proof.manifest.get('producer_evidence', {}).get('role') != 'proof'):
        raise ValueError('Archive model requires its verified accepted native producer proof')


def producer_proof_bindings(proof, definition, inputs, *, dataset, operation):
    """Preserve the proof's exact selectors, schemas and native custody handles.

    This composes existing native references. DocSpec resolves the adoption and
    prerequisite, enforces the adopted model definition and owns input reuse.
    No source metadata or payload is reopened here.
    """
    from ddk.docspec_job_evidence import producer_model_bindings

    require_producer_proof(proof)
    if not isinstance(definition, dict):
        raise ValueError('Model requires the exact adopted producer definition')
    if proof.candidate['dataset'] != dataset or proof.candidate['operation'] == operation:
        raise ValueError('Model producer proof requires a distinct operation under the same native owner')
    bound = producer_model_bindings(proof, prerequisite_inputs=[item['name'] for item in definition['inputs']])
    selected = {item['name']: item for item in inputs if item['kind'] == 'native_table'}
    if (not selected or len(selected) != len(bound['inputs'])
            or any(selected.get(item['name']) != item for item in bound['inputs'])):
        raise ValueError('Model native inputs differ from the complete accepted producer proof')
    return bound['request'], bound['schemas']


def require_model_proof_request(request):
    """Refuse an incomplete model request before native submission or recovery."""
    if (not request.get('producer_adoption') or not request.get('snapshot_inputs')
            or len(request.get('prerequisites', ())) != 1):
        raise ValueError('Archive model request requires its original native producer proof bindings')
