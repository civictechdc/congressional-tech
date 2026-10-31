"""Evidence-bound recovery identity decisions, before retained reconciliation.

Source-native facts are extracted from pinned JSON records, never inferred from
filenames. Publisher metadata is evidence, not proof of historical completeness.
A caller must pin the source and its capture receipt, or name the person who
reviewed retained metadata. A body is independently qualified before acceptance.
"""
from hashlib import sha256
import gzip
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from congress_api.retention.provenance import instant
from congress_shared.campaign import REQUIREMENTS
from congress_shared.custody import bounded_control_read, canonical_json_bytes, verify_local_file

VERSION = 'recovery-identity-v1'
IDENTIFIERS = frozenset('package bill congress session meeting document version date witness title'.split())
STRONG = frozenset('package bill meeting document'.split())
CONTENT = frozenset({'requested_content_in_official_hearing','requested_content_in_official_report',
    'requested_content_in_official_amendment_packet','official_complete_statement_text_available',
    'same_article_publisher_text_available'})
COUNTERPART = frozenset({'official_updated_revision_available','official_introduced_bill_counterpart',
    'official_recorded_votes_available','official_alternate_amendment_available',
    'official_public_statement_counterpart','official_report_counterpart_available','related_final_report_available'})


def relationship_satisfies(requirement, kind):
    if requirement not in REQUIREMENTS:
        raise ValueError('Unsupported recovery requirement')
    return (kind == 'recovered_document' or requirement in {'requested_content','current_official_counterpart'}
            and kind in CONTENT or requirement == 'current_official_counterpart' and kind in COUNTERPART)


def pin_path(pin, base):
    """Resolve only explicit lowercase digest pins; None never means unpinned."""
    if (not isinstance(pin,dict) or set(pin)!={'path','sha256'}
            or not isinstance(pin['path'],str) or not pin['path']
            or not isinstance(pin['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',pin['sha256'])):
        raise ValueError('Evidence requires an exact file pin')
    path=Path(pin['path'])
    return path if path.is_absolute() else Path(base)/path


def _unique_fields(pairs):
    value={}
    for key,item in pairs:
        if key in value: raise ValueError('Duplicate evidence field: '+key)
        value[key]=item
    return value


def read_pin(pin, base):
    """Read one bounded control artifact after verifying its exact bytes."""
    path=pin_path(pin,base)
    verified = verify_local_file(path, expected_sha256=pin['sha256'])
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        value = json.loads(bounded_control_read(stream),object_pairs_hook=_unique_fields)
    verified._require_custody(path)
    return value, verified


def receipt_binding(receipt, *, url, digest, size):
    """Require a complete successful capture of these bytes at this literal URL."""
    if (receipt.get('http_status') != 200 or receipt.get('url') != url
            or not isinstance(receipt.get('retrieved_at'),str) or receipt.get('error_type')
            or 'retry-after' in receipt.get('response_headers',{})):
        raise ValueError('Source receipt does not bind the selected URL')
    instant(receipt['retrieved_at'])
    captures = [c for c in receipt.get('captures',[]) if c.get('attempt') == 0
                and c.get('member_path') is None and c.get('context_url') == url
                and c.get('complete') is True and c.get('sha256') == digest and c.get('bytes') == size]
    if len(captures) != 1:
        raise ValueError('Source receipt does not bind complete body bytes')
    return receipt['retrieved_at']


def _pointer(value, pointer):
    if not isinstance(pointer,str) or (pointer and not pointer.startswith('/')):
        raise ValueError('Invalid source JSON pointer')
    for part in pointer.split('/')[1:] if pointer else []:
        key = part.replace('~1','/').replace('~0','~')
        value = value[int(key)] if isinstance(value,list) else value[key]
    return value


def identity_source(spec, base):
    """Extract native identifiers from a selected record in actual evidence bytes."""
    source, custody = read_pin(spec['source'], base)
    source_url = spec['source_url']
    if urlsplit(source_url).scheme not in {'https','http'} or not urlsplit(source_url).hostname:
        raise ValueError('Identity source requires an absolute URL')
    if 'receipt' in spec:
        receipt, _ = read_pin(spec['receipt'],base)
        observed = receipt_binding(receipt,url=source_url,digest=custody.sha256,size=custody.size_bytes)
        authority = {'receipt_sha256':spec['receipt']['sha256']}
    else:
        # Explicit human-reviewed retained metadata is a separate evidence basis.
        if not isinstance(spec.get('reviewed_by'),str) or not spec['reviewed_by'].strip():
            raise ValueError('Metadata needs a source receipt or named reviewer')
        observed = spec['reviewed_at']; instant(observed)
        authority = {'reviewed_by':spec['reviewed_by'],'reviewed_at':observed}
    row = _pointer(source,spec.get('record_pointer',''))
    url = row[spec['url_field']]
    if not isinstance(url,str) or urlsplit(url).scheme not in {'http','https'} or not urlsplit(url).hostname:
        raise ValueError('Metadata record needs a document URL')
    fields = spec['identifier_fields']
    required = spec.get('required_fields',[])
    if (not isinstance(fields,dict) or not fields or not set(fields).issubset(IDENTIFIERS)
            or not isinstance(required,list) or not set(required).issubset(IDENTIFIERS)):
        raise ValueError('Unsupported identity fields')
    facts = {name:row.get(field) for name,field in fields.items()}
    if any(value is not None and (not isinstance(value,(str,int)) or isinstance(value,bool)) for value in facts.values()):
        raise ValueError('Identity values must be source-native scalar text or integers')
    custody._require_custody(custody.path)
    return {'url':url,'identifiers':facts,'required_fields':required,'source_url':source_url,
            'source_sha256':custody.sha256,'observed_at':observed,'authority':authority,
            'relationship_evidence':row.get(spec['relationship_field']) if spec.get('relationship_field') else None}


def decide(target, candidate, *, requirement, relationship, body, qualification, receipt, receipt_sha256):
    """Compare all target facts, binding the decision to qualified captured bytes."""
    from corpus_recovery.qualification import verify_qualification_record
    body._require_custody(body.path)
    verify_qualification_record(qualification, body_sha256=body.sha256,
                                body_bytes=body.size_bytes, require_qualified=True)
    retrieved_at = receipt_binding(receipt,url=candidate['url'],digest=body.sha256,size=body.size_bytes)
    evidence = dict(version=VERSION,target=target,candidate=candidate,requirement=requirement,
        relationship=relationship,body_sha256=body.sha256,body_bytes=body.size_bytes,
        receipt_sha256=receipt_sha256,retrieved_at=retrieved_at,
        qualification_sha256=qualification['qualification_sha256'])
    digest = sha256(canonical_json_bytes(evidence)).hexdigest()
    def result(status,reason):
        return dict(status=status,reason=reason,policy=VERSION,evidence_sha256=digest,evidence=evidence)
    if not relationship_satisfies(requirement,relationship):
        return result('review_required','relationship_does_not_satisfy_requirement')
    left,right = target['identifiers'],candidate['identifiers']
    needed = set(left)|set(target['required_fields'])
    if not needed.intersection(STRONG):
        return result('review_required','no_source_native_identifier')
    revision_fields=set()
    differing={name for name in needed if left.get(name)!=right.get(name)}
    if (requirement=='current_official_counterpart' and relationship=='official_updated_revision_available'
            and differing):
        bridge=candidate.get('relationship_evidence')
        if not isinstance(bridge,dict):
            return result('review_required','missing_revision_relationship_evidence')
        if (bridge.get('kind')!=relationship or bridge.get('target_url')!=target['url']
                or bridge.get('target_identifiers')!=left):
            return result('rejected','conflicting_revision_relationship_evidence')
        # Source evidence must name the old document and preserve a native
        # lineage. A version change alone never establishes a counterpart.
        same=lambda name: bool(left.get(name)) and left.get(name)==right.get(name)
        if not (same('document') or same('bill') and same('congress')):
            return result('review_required','missing_stable_revision_lineage')
        revision_fields={'version','date','title'}
        if same('bill') and same('congress'): revision_fields.add('package')
    for name in sorted(needed):
        # Keep versions, dates and identifiers literal; case folding could merge IDs.
        a,b = left.get(name),right.get(name)
        a,b = (str(v).strip() if v is not None else '' for v in (a,b))
        if not a or not b: return result('review_required','missing_'+name)
        if a != b and name not in revision_fields: return result('rejected','conflicting_'+name)
    return result('accepted','source_identifiers_match')
