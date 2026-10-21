"""Write optional reviewed candidates separately from an unchanged catalog pair."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pypdf

from . import document_index, document_evidence, document_reviews, document_review_receipts
from .document_index import validate_document_indexes
from .document_review_receipts import file_digest, verified, read_ledger, load_reviews, compile_review
from .document_reviews import apply_review_candidate
from .native_features import (
    attach_occurrence_receipts,
    map_locators_to_occurrences,
    read_occurrence_receipts,
)


def attach_review_provenance_receipts(native, source_pin, *, candidates, members_by_doc=None,
                                      operation='review-provenance', definition=None,
                                      locator_column='source_id', deletions=()):
    """Attach verified review provenance receipts to ``source_pin`` without rewriting source files.

    Receipt locators/URLs remain application metadata and do not retain external
    objects. Supports ordered duplicate receipts and explicit ``None`` nulls.
    """
    loc_map = map_locators_to_occurrences(native, source_pin, locator_column=locator_column)
    receipts = []
    for candidate in candidates:
        doc_id = candidate['document']['document_id']
        review = candidate.get('review')
        payload = (
            json.dumps(
                dict(
                    document_id=doc_id,
                    status=candidate['status'],
                    receipt=review['receipt'],
                    receipt_sha256=review['receipt_sha256'],
                    group_sha256=review['group_sha256'],
                    body_key=review['body_key'],
                    body_sha256=review['body_sha256'],
                ),
                ensure_ascii=False,
                sort_keys=True,
                separators=(',', ':'),
            )
            if review is not None
            else None
        )
        if locator_column == 'document_id':
            targets = [doc_id]
        elif members_by_doc is not None and doc_id in members_by_doc:
            targets = sorted(row['source_id'] for row in members_by_doc[doc_id])
        else:
            targets = sorted(candidate.get('source_ids') or [doc_id])
        for target in targets:
            receipts.append((target, payload))
    dataset = source_pin['dataset']['dataset']
    base_def = definition or source_pin['dataset']['definition']
    return attach_occurrence_receipts(
        native,
        dataset=dataset,
        operation=operation,
        base_pin=source_pin,
        definition=base_def,
        locator_to_occurrences=loc_map,
        receipts=receipts,
        deletions=deletions,
    )


def read_review_provenance_receipts(native, pin, *, locator_column='source_id'):
    """Read attached review provenance receipts bound to exact ``source`` and ``evidence`` versions."""
    loc_map = map_locators_to_occurrences(native, pin, locator_column=locator_column)
    inv_map = {occ: loc for loc, occs in loc_map.items() for occ in occs}
    evidence_pin = pin.get('dataset', {}).get('evidence')
    rows = read_occurrence_receipts(
        native,
        pin,
        occurrence_to_locator=inv_map,
        expected_source_pin=pin['dataset']['groups']['source'],
        expected_evidence_pin=evidence_pin,
    )
    for row in rows:
        if isinstance(row.get('evidence'), str) and row['evidence'].startswith('{'):
            row['parsed'] = json.loads(row['evidence'])
        else:
            row['parsed'] = row.get('evidence')
    return rows


def remap_review_provenance_receipts(native, before_pin, after_pin, *, identities, catalog_id,
                                     component_lookup, previous_binding=None,
                                     operation='review-provenance-remap', definition=None,
                                     locator_column='source_id'):
    """Remap review receipts across source updates by stable identity, preserving withdrawal reasons.

    Never infers review authority from native ``(source_file, source_row)`` row
    positions: withdrawn documents drop their occurrence receipts while their
    recorded withdrawal reasons (``document_missing``, ``sources_changed``,
    ``body_changed``) are preserved in the returned binding.
    """
    from viewer_publication.filename_review_binding import bind_selected
    from .native_features import remap_occurrence_receipts

    binding = bind_selected(
        catalog_id, identities, component_lookup, previous=previous_binding
    )
    withdrawn_locators = set()
    for item in binding['withdrawn']:
        if locator_column == 'document_id':
            withdrawn_locators.add(item['document_id'])
        else:
            withdrawn_locators.update(item.get('source_ids') or ())
    dataset = after_pin['dataset']['dataset']
    base_def = definition or after_pin['dataset']['definition']
    pin = remap_occurrence_receipts(
        native,
        dataset=dataset,
        operation=operation,
        before_pin=before_pin,
        after_pin=after_pin,
        definition=base_def,
        locator_column=locator_column,
        deleted_locators=withdrawn_locators,
    )
    return dict(pin=pin, binding=binding)


def implementation():
    return dict(source_sha256={str(Path(path)):file_digest(path) for path in [__file__,
        document_index.__file__,document_evidence.__file__,document_reviews.__file__,document_review_receipts.__file__]},
        house_naming_fingerprint=document_index.parser_fingerprint(),pyarrow_version=pa.__version__,pypdf_version=pypdf.__version__)


def selected_groups(path, ids, identity):
    """Read complete selected rows in bounded batches after a document-ID scan."""
    file = pq.ParquetFile(path)
    wanted = pa.array(sorted(ids),type=pa.string())
    groups = [i for i in range(file.num_row_groups)
        if pc.any(pc.is_in(file.read_row_group(i,columns=['document_id'])['document_id'],value_set=wanted)).as_py()]
    result = {}
    for batch in file.iter_batches(row_groups=groups,batch_size=32,use_threads=False):
        for row in batch.filter(pc.is_in(batch['document_id'],value_set=wanted)).to_pylist():
            key = row[identity]
            if not key or key in result: raise ValueError('Missing or duplicate selected identity')
            result[key] = row
    return result


def write_candidates(sources, documents, proposals, proposals_sha256, receipt, receipt_sha256, output, resolve=Path,
                     *, native=None, source_pin=None, receipt_operation='review-provenance'):
    """Admit verified evidence and publish only a separate local candidate bundle.

    resolve maps review locators to bytes (default: the locator as a path). The
    catalog pair is always read directly; summary bindings keep locator text.
    """
    output = Path(output)
    if output.exists(): raise FileExistsError(output)
    policy = implementation()
    bindings = {str(path):file_digest(path) for path in [sources,documents]}
    pair = {str(Path(path)) for path in [sources,documents]}
    locate = lambda path: Path(path) if str(Path(path)) in pair else resolve(path)
    proposal_rows = json.loads(verified(proposals,proposals_sha256,bindings,locate).read_text())['records']
    proposed = {row['document_id']:row for row in proposal_rows}
    if not proposed or len(proposed) != len(proposal_rows): raise ValueError('Empty or duplicate proposal identities')
    reviews = load_reviews(receipt,receipt_sha256,bindings,locate)
    if set(reviews) != set(proposed): raise ValueError('Proposals and receipt chain must cover exactly the same groups')
    validate_document_indexes(sources,documents)
    source_rows = selected_groups(sources,set(proposed),'source_id')
    docs = selected_groups(documents,set(proposed),'document_id')
    members = defaultdict(list)
    for row in source_rows.values(): members[row['document_id']].append(row)
    if set(members) != set(proposed) or set(docs) != set(proposed): raise ValueError('Incomplete current group coverage')
    originals = {}
    candidates = []
    for key in sorted(proposed):
        review = reviews[key]
        if review['receipt'] not in originals:
            record = json.loads(verified(review['receipt'],review['receipt_sha256'],bindings,locate).read_text())
            originals[review['receipt']] = read_ledger(verified(record['input_ledger'],record['input_ledger_sha256'],bindings,locate))
        compiled = compile_review(proposed[key],originals[review['receipt']][key],docs[key],members[key],review)
        candidate = apply_review_candidate(docs[key],members[key],compiled)
        if candidate['status'] not in {'candidate_applied','annotation_only_unsupported_forms'}:
            raise ValueError('Fresh review binding did not apply')
        if apply_review_candidate(docs[key],members[key])['document'] != docs[key]:
            raise ValueError('Withdrawal changed baseline')
        candidates.append(candidate)
    for path,digest in bindings.items(): verified(path,digest,{},locate)
    if implementation() != policy: raise ValueError('Review implementation changed during admission')
    native_receipts = None
    if native is not None and source_pin is not None:
        attached_pin = attach_review_provenance_receipts(
            native,
            source_pin,
            candidates=candidates,
            members_by_doc=members,
            operation=receipt_operation,
        )
        attached_rows = read_review_provenance_receipts(native, attached_pin)
        native_receipts = dict(
            dataset=attached_pin['dataset']['dataset'],
            version=attached_pin['id'],
            source_version=attached_pin['dataset']['groups']['source'],
            evidence_version=attached_pin['dataset']['evidence'],
            attached_rows=len(attached_rows),
            pin=attached_pin,
        )
    output.mkdir(parents=True)
    candidate_path = output/'candidates.jsonl'
    with candidate_path.open('x') as stream:
        for candidate in candidates: stream.write(json.dumps(candidate,ensure_ascii=False)+'\n')
    # A completed summary is the completion marker; partial output is not reusable.
    for path,digest in bindings.items(): verified(path,digest,{},locate)
    summary = dict(bundle_version=2,
        baseline={name:dict(path=str(path),sha256=bindings[str(path)]) for name,path in [('sources',sources),('documents',documents)]},
        reviewed_groups=len(candidates),source_rows=len(source_rows),
        reviewed_pages=sum(r['observation']['pages'] for r in reviews.values()),
        case_status=dict(Counter(c['status'] for c in candidates)),bindings=bindings,implementation=policy,
        outputs={'candidates.jsonl':file_digest(candidate_path)},baseline_files_unchanged=True,
        withdrawal_restores_baseline=True,production_selected=False,independent_reference=False,release_approved=False,
        **({'native_receipts': native_receipts} if native_receipts is not None else {}))
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['sources','documents','proposals','receipt','output']:
        parser.add_argument('--'+name,type=Path,required=True)
    for name in ['proposals-sha256','receipt-sha256']: parser.add_argument('--'+name,required=True)
    result = write_candidates(**vars(parser.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k not in ['bindings','outputs']},indent=2))
