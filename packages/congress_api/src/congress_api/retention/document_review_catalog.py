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


def write_candidates(sources, documents, proposals, proposals_sha256, receipt, receipt_sha256, output):
    """Admit verified evidence and publish only a separate local candidate bundle."""
    output = Path(output)
    if output.exists(): raise FileExistsError(output)
    policy = implementation()
    bindings = {str(path):file_digest(path) for path in [sources,documents]}
    proposal_rows = json.loads(verified(proposals,proposals_sha256,bindings).read_text())['records']
    proposed = {row['document_id']:row for row in proposal_rows}
    if not proposed or len(proposed) != len(proposal_rows): raise ValueError('Empty or duplicate proposal identities')
    reviews = load_reviews(receipt,receipt_sha256,bindings)
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
            record = json.loads(Path(review['receipt']).read_text())
            originals[review['receipt']] = read_ledger(verified(record['input_ledger'],record['input_ledger_sha256'],bindings))
        compiled = compile_review(proposed[key],originals[review['receipt']][key],docs[key],members[key],review)
        candidate = apply_review_candidate(docs[key],members[key],compiled)
        if candidate['status'] not in {'candidate_applied','annotation_only_unsupported_forms'}:
            raise ValueError('Fresh review binding did not apply')
        if apply_review_candidate(docs[key],members[key])['document'] != docs[key]:
            raise ValueError('Withdrawal changed baseline')
        candidates.append(candidate)
    for path,digest in bindings.items(): verified(path,digest,{})
    if implementation() != policy: raise ValueError('Review implementation changed during admission')
    output.mkdir(parents=True)
    candidate_path = output/'candidates.jsonl'
    with candidate_path.open('x') as stream:
        for candidate in candidates: stream.write(json.dumps(candidate,ensure_ascii=False)+'\n')
    # A completed summary is the completion marker; partial output is not reusable.
    for path,digest in bindings.items(): verified(path,digest,{})
    summary = dict(bundle_version=2,
        baseline={name:dict(path=str(path),sha256=bindings[str(path)]) for name,path in [('sources',sources),('documents',documents)]},
        reviewed_groups=len(candidates),source_rows=len(source_rows),
        reviewed_pages=sum(r['observation']['pages'] for r in reviews.values()),
        case_status=dict(Counter(c['status'] for c in candidates)),bindings=bindings,implementation=policy,
        outputs={'candidates.jsonl':file_digest(candidate_path)},baseline_files_unchanged=True,
        withdrawal_restores_baseline=True,production_selected=False,independent_reference=False,release_approved=False)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['sources','documents','proposals','receipt','output']:
        parser.add_argument('--'+name,type=Path,required=True)
    for name in ['proposals-sha256','receipt-sha256']: parser.add_argument('--'+name,required=True)
    result = write_candidates(**vars(parser.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k not in ['bindings','outputs']},indent=2))
