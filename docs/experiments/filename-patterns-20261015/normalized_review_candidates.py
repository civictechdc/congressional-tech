"""Record filename-claim normalization before explicitly rebinding local reviews."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import shutil

from congress_api.retention.document_review_receipts import load_reviews, read_ledger
from catalog_filename_replay import implementation_manifest, implementation_identity, normalized
from catalog_review_evidence import verified
from congress_api.retention.document_index import restore_filename_kind, validate_document_indexes
from current_review_candidates import select_candidates
from current_review_path_replay import changes, compact_pair, audit_scenario
from packet_review_replay import keyed
from pilot_reconcile import file_digest


def validate_transition(old_sources, old_documents, sources, documents):
    """Allow exactly the existing restoration and member union, and no other edit."""
    expected_sources = deepcopy(old_sources)
    claims = defaultdict(set)
    for row in expected_sources:
        restored = deepcopy(row)
        restore_filename_kind(restored)
        row['filename_document_kind'] = restored.get('filename_document_kind')
        claims[row['document_id']].update(row['filename_document_kind'] or [])
    expected_documents = deepcopy(old_documents)
    for row in expected_documents:
        row['filename_document_kind'] = sorted(claims[row['document_id']]) or None
    for expected, actual, identity in [(expected_sources,sources,'source_id'),
                                        (expected_documents,documents,'document_id')]:
        if any(changes(expected,actual,identity).values()):
            raise ValueError('Transition differs from existing filename-claim restoration')
    return dict(source_changes=changes(old_sources,sources,'source_id'),
                document_changes=changes(old_documents,documents,'document_id'))


def bound_summary(checkpoint, bindings):
    bindings[str(checkpoint)] = file_digest(checkpoint)
    cp = json.loads(Path(checkpoint).read_text())
    path = verified(cp['summary_path'],cp['summary_sha256'],bindings)
    summary = json.loads(path.read_text())
    for name,digest in summary['bindings'].items(): verified(name,digest,bindings)
    for name,digest in summary['outputs'].items(): verified(path.parent/name,digest,bindings)
    return path.parent, summary


def run(current_checkpoint, path_checkpoint, receipt_checkpoint, output):
    output = Path(output)
    if output.exists(): raise FileExistsError(output)
    implementation = implementation_manifest()
    bindings = {}
    directory,current = bound_summary(current_checkpoint,bindings)
    replay,paths = bound_summary(path_checkpoint,bindings)
    if paths['bindings'].get(str(current_checkpoint)) != file_digest(current_checkpoint):
        raise ValueError('Path replay does not bind the selected current checkpoint')
    if current['bindings'].get(str(receipt_checkpoint)) != file_digest(receipt_checkpoint):
        raise ValueError('Receipt checkpoint is outside current evidence')
    for folder,names in [(directory,['document-filenames.parquet','documents.parquet','proposals.json','candidates.jsonl']),
                          (replay/'disk',['document-filenames.parquet','documents.parquet'])]:
        if any(str(folder/name) not in bindings for name in names):
            raise ValueError('Required normalization input is not hash-bound')
    old_sources,old_documents = compact_pair(directory)
    sources,documents = compact_pair(replay/'disk')
    transition = validate_transition(old_sources,old_documents,sources,documents)
    validate_document_indexes(replay/'disk/document-filenames.parquet',replay/'disk/documents.parquet')
    old_candidates = read_ledger_candidates(directory/'candidates.jsonl')
    if set(old_candidates) != set(keyed(old_documents,'document_id')):
        raise ValueError('Old candidate coverage differs from baseline')
    if not audit_scenario(old_sources,old_documents,old_sources,old_documents,old_candidates)['candidates_identical']:
        raise ValueError('Old candidates do not match saved baseline')
    receipt = json.loads(Path(receipt_checkpoint).read_text())
    reviews = load_reviews(receipt['receipt_path'],receipt['receipt_sha256'],bindings)
    originals,ledgers = {},{}
    for key,review in reviews.items():
        receipt_path = review['receipt']
        if receipt_path not in ledgers:
            record = json.loads(Path(receipt_path).read_text())
            ledgers[receipt_path] = read_ledger(verified(record['input_ledger'],record['input_ledger_sha256'],bindings))
        originals[key] = ledgers[receipt_path][key]
    rows = json.loads((directory/'proposals.json').read_text())['records']
    proposals = keyed(rows,'document_id')
    candidates = select_candidates(proposals,originals,keyed(documents,'document_id'),keyed(sources,'source_id'),reviews)
    transitions = {}
    for key,candidate in candidates.items():
        old = old_candidates[key]
        expected = deepcopy(old)
        expected['baseline_group_sha256'] = candidate['baseline_group_sha256']
        expected['review']['group_sha256'] = candidate['review']['group_sha256']
        expected['document']['filename_document_kind'] = candidate['document'].get('filename_document_kind')
        if normalized(expected) != normalized(candidate):
            raise ValueError('Rebinding changed review content or selected interpretation')
        transitions[key] = dict(before=old['baseline_group_sha256'],after=candidate['baseline_group_sha256'])
    transition['group_bindings'] = transitions
    for path,digest in bindings.items(): verified(path,digest,{})
    if implementation_identity(implementation_manifest()) != implementation_identity(implementation):
        raise ValueError('Implementation changed during normalization binding')
    output.mkdir(parents=True)
    for name in ['document-filenames.parquet','documents.parquet']:
        shutil.copyfile(replay/'disk'/name,output/name)
        verified(output/name,file_digest(replay/'disk'/name),{})
    shutil.copyfile(directory/'proposals.json',output/'proposals.json')
    (output/'candidates.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in candidates.values()))
    for name,value in [('transition.json',transition),('implementation.json',implementation)]:
        (output/name).write_text(json.dumps(value,indent=2)+'\n')
    for path,digest in bindings.items(): verified(path,digest,{})
    result = dict(current_groups=len(documents),source_rows=len(sources),
        case_status=dict(Counter(r['status'] for r in candidates.values())),
        changed_bindings=sum(r['before']!=r['after'] for r in transitions.values()),
        bindings=bindings,outputs={p.name:file_digest(p) for p in output.iterdir() if p.is_file()},
        review_rebinding=True,only_transition='filename_document_kind restored by existing logic',
        prior_review_content_preserved=True,production_selected=False,independent_reference=False,release_approved=False)
    summary = output/'summary.json';summary.write_text(json.dumps(result,indent=2)+'\n')
    (output/'checkpoint.json').write_text(json.dumps(dict(summary_path=str(summary),summary_sha256=file_digest(summary)),indent=2)+'\n')
    return result


def read_ledger_candidates(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    result = {row['document']['document_id']:row for row in rows}
    if len(result)!=len(rows): raise ValueError('Duplicate candidate identity')
    return result


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['current-checkpoint','path-checkpoint','receipt-checkpoint','output']:
        parser.add_argument('--'+name,type=Path,required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k not in ['bindings','outputs']},indent=2))
