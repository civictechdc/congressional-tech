"""Corpus semantics: the C2/C6/C7 invariants the JSON Schema cannot express.

Generalizes the packet's illustrative checker (docs/checks/validate.py) into
the reusable owner: credential redaction, the identity decision graph,
foreign-key kind checks, run input coverage and acyclicity, text hashes,
code-point spans, capture/version access compatibility, interval validity,
supersede-chain acyclicity, story membership, and release structure. Every
failure raises ContractError with a stable rule name and offending record id.
"""
import hashlib
from urllib.parse import urlsplit

from news_lake.contract.errors import ContractError
from news_lake.contract.records import KIND_TABLES, validate_shape
from news_lake.context import parse_instant

# Record field -> required kind of the referenced record.
FOREIGN_KEYS = {
    'outlet_id': 'outlet',
    'capture_id': 'capture',
    'item_id': 'item',
    'run_id': 'run',
    'version_id': 'version',
    'current_version_id': 'version',
    'superseded_by': 'item',
    'entity_id': 'entity',
    'target_entity_id': 'entity',
    'left_id': 'entity',
    'right_id': 'entity',
    'prior_decision_id': 'identity_decision',
    'story_id': 'story',
}

EXPECTED_RELEASE_TABLES = set(KIND_TABLES.values()) - {'news.releases'}
INT64_MAX = 9223372036854775807
CREDENTIAL_FIELDS = frozenset({
    'request_url', 'feed_url', 'url', 'canonical_url', 'payload_uri', 'checkpoint_ref',
})


def _has_userinfo(value):
    if not isinstance(value, str) or '://' not in value:
        return False
    return '@' in urlsplit(value).netloc


def _check_credentials(record):
    for field in CREDENTIAL_FIELDS:
        if field in record and _has_userinfo(record[field]):
            raise ContractError(
                'unredacted_credentials', f'{field} contains userinfo credentials', record_id=record['id']
            )
    for value in record.get('url_aliases', ()):
        if _has_userinfo(value):
            raise ContractError(
                'unredacted_credentials', 'url_aliases contains userinfo credentials', record_id=record['id']
            )
    if record.get('kind') == 'release':
        for checkpoint in record.get('checkpoints', ()):
            if _has_userinfo(checkpoint.get('checkpoint_ref')):
                raise ContractError(
                    'unredacted_credentials', 'checkpoint_ref contains userinfo credentials',
                    record_id=record['id'],
                )


def _check_run_input_cycles(by_id):
    """C7: run -> version -> run input references must stay acyclic."""
    run_ids = {rid for rid, record in by_id.items() if record['kind'] == 'run'}
    edges = {rid: set() for rid in run_ids}
    for rid in run_ids:
        run = by_id[rid]
        for ref in run['inputs']:
            if ref['kind'] != 'version':
                continue
            version = by_id.get(ref['id'])
            if version is None or version['kind'] != 'version':
                continue
            producer = version.get('run_id')
            if producer in run_ids:
                edges[rid].add(producer)

    visiting, visited = set(), set()

    def visit(node):
        if node in visiting:
            raise ContractError('input_cycle', 'run input references are cyclic', record_id=node)
        if node in visited:
            return
        visiting.add(node)
        for target in edges[node]:
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for rid in sorted(run_ids):
        visit(rid)


def _check_decisions(records):
    """C6: the decision graph is part of corpus conformance, not only linking."""
    from news_lake.identity.decisions import apply_decisions

    apply_decisions(records)


def check_corpus(records, validated_ids=(), allow_extra_by_kind=None):
    """Validate a candidate snapshot: shape per record plus cross-record rules.

    ``validated_ids`` names records whose per-record shape and text-hash checks
    were already validated against the same immutable snapshot. Cross-record C7
    rules and decision-graph semantics always run.

    ``allow_extra_by_kind`` maps a record kind to the top-level fields supplied
    by its evolved storage schema, so a release can validate records that carry
    compatible optional columns without weakening the contract for anyone else.
    """
    validated = set(validated_ids or ())
    allowed_by_kind = allow_extra_by_kind or {}
    by_id = {}
    for record in records:
        kind = record.get('kind') if isinstance(record, dict) else None
        if record.get('id') not in validated:
            validate_shape(record, allowed_extra=allowed_by_kind.get(kind, ()))
        _check_credentials(record)
        if record['id'] in by_id:
            raise ContractError('duplicate_record_id', 'id appears twice in the candidate snapshot', record_id=record['id'])
        by_id[record['id']] = record

    def get(identifier, kind, record):
        target = by_id.get(identifier)
        if target is None:
            raise ContractError('missing_reference', f'{kind} {identifier} is not present', record_id=record['id'])
        if target['kind'] != kind:
            raise ContractError(
                'wrong_reference_kind', f'expected a {kind}, found {target["kind"]}', record_id=record['id']
            )
        return target

    def output_run(record, input_kind, input_id):
        run = get(record['run_id'], 'run', record)
        if run['status'] != 'succeeded':
            raise ContractError('output_run_not_successful', f'run status is {run["status"]}', record_id=record['id'])
        if {'kind': input_kind, 'id': input_id} not in run['inputs']:
            raise ContractError(
                'output_input_absent', f'input {input_kind} {input_id} is absent from the run inputs', record_id=record['id']
            )

    memberships = set()
    for record in records:
        kind, rid = record['kind'], record['id']
        for field, ref_kind in FOREIGN_KEYS.items():
            if field in record:
                get(record[field], ref_kind, record)

        if kind == 'item':
            if 'current_version_id' in record:
                version = get(record['current_version_id'], 'version', record)
                if version['item_id'] != rid:
                    raise ContractError('current_version_mismatch', 'current version belongs to another item', record_id=rid)
            visited = set()
            node = record
            while 'superseded_by' in node:
                if node['id'] in visited:
                    raise ContractError('cyclic_supersede', 'superseded_by chain is cyclic', record_id=rid)
                visited.add(node['id'])
                node = get(node['superseded_by'], 'item', record)

        elif kind == 'entity':
            for field in ('tenures', 'affiliations'):
                for interval in record.get(field, []):
                    if 'from' in interval and 'to' in interval and not interval['from'] < interval['to']:
                        raise ContractError('invalid_interval', f'{field} has from >= to', record_id=rid)
            for identifier in record.get('evidence_capture_ids', []):
                get(identifier, 'capture', record)

        elif kind == 'identity_decision':
            if 'left_id' in record and record['left_id'] == record['right_id']:
                raise ContractError('reflexive_identity_decision', 'left_id equals right_id', record_id=rid)
            for identifier in record.get('evidence_capture_ids', []):
                get(identifier, 'capture', record)

        elif kind == 'run':
            for input_ref in record['inputs']:
                get(input_ref['id'], input_ref['kind'], record)
            if parse_instant(record['started_at']) > parse_instant(record['finished_at']):
                raise ContractError('run_finish_before_start', 'finished_at precedes started_at', record_id=rid)

        elif kind == 'version':
            output_run(record, 'capture', record['capture_id'])
            capture = get(record['capture_id'], 'capture', record)
            if 'text' in record or record.get('access') in ('restricted', 'redistributable'):
                if capture['status'] != 'succeeded':
                    raise ContractError(
                        'output_capture_not_successful',
                        f'text was extracted from a {capture["status"]} capture',
                        record_id=rid,
                    )
                if capture['access'] == 'metadata_only':
                    raise ContractError(
                        'text_from_metadata_only_capture',
                        'text was extracted from a metadata-only capture',
                        record_id=rid,
                    )
            if 'text' in record and rid not in validated:
                actual = hashlib.sha256(record['text'].encode('utf-8')).hexdigest()
                if actual != record['text_hash']:
                    raise ContractError('text_hash_mismatch', 'text_hash is not sha256 of the stored text', record_id=rid)

        elif kind == 'mention' or kind == 'classification':
            output_run(record, 'version', record['version_id'])
            if kind == 'mention':
                version = get(record['version_id'], 'version', record)
                if not (rid in validated and record['version_id'] in validated and 'occurrences' not in record):
                    for span in record['occurrences']:
                        if span['field'] not in version:
                            raise ContractError('span_absent_field', f'{span["field"]} is absent from the version', record_id=rid)
                        text = version[span['field']]
                        if not 0 <= span['start'] < span['end'] <= len(text):
                            raise ContractError('span_out_of_bounds', f'span {span["start"]}:{span["end"]} exceeds the text', record_id=rid)
                        if text[span['start']:span['end']] != record['surface']:
                            raise ContractError('surface_mismatch', 'offsets do not select the surface form', record_id=rid)

        elif kind == 'story':
            if get(record['run_id'], 'run', record)['status'] != 'succeeded':
                raise ContractError('story_run_not_successful', 'story references a non-successful run', record_id=rid)

        elif kind == 'story_member':
            output_run(record, 'version', record['version_id'])
            story = get(record['story_id'], 'story', record)
            if story['run_id'] != record['run_id']:
                raise ContractError('story_member_run_mismatch', 'story and member name different runs', record_id=rid)
            key = (record['run_id'], record['version_id'])
            if key in memberships:
                raise ContractError('multiple_memberships', 'version belongs to more than one story in this run', record_id=rid)
            memberships.add(key)

        elif kind == 'release':
            names = [entry['table'] for entry in record['snapshots']]
            if len(names) != len(set(names)) or set(names) != EXPECTED_RELEASE_TABLES:
                raise ContractError('release_table_set', 'snapshot table set is incomplete or duplicated', record_id=rid)
            for entry in record['snapshots']:
                if 'snapshot_id' in entry and not 0 < int(entry['snapshot_id']) <= INT64_MAX:
                    raise ContractError('snapshot_id_range', 'snapshot id exceeds signed 64-bit range', record_id=rid)
            processors = [entry['processor'] for entry in record['selections']]
            if len(processors) != len(set(processors)):
                raise ContractError('multiple_selections', 'more than one selection for a processor', record_id=rid)
            connectors = [entry['connector_key'] for entry in record['checkpoints']]
            if len(connectors) != len(set(connectors)):
                raise ContractError(
                    'duplicate_checkpoint_key', 'more than one checkpoint for a connector', record_id=rid
                )

    _check_decisions(records)
    _check_run_input_cycles(by_id)
    return records
