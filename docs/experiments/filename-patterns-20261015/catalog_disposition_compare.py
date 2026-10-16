"""Compare reviewed packet forms with a bound saved catalog, without changing kinds."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from catalog_content_review import load_reviews, read_ledger
from catalog_review_evidence import row_digest, verified
from pilot_reconcile import file_digest


COLUMNS = ['document_id', 'source_id', 'filename', 'source_url', 'body_key',
           'document_kind', 'filename_document_kind', 'content_document_kind',
           'document_kind_source']


def selected_rows(path, ids, identity):
    """Scan small scalar/list columns; never materialize nested source occurrences."""
    table = pq.ParquetFile(path)
    required = set(COLUMNS)
    if not required <= set(table.schema_arrow.names):
        raise ValueError('Catalog lacks required comparison columns')
    result = {}
    wanted = pa.array(sorted(ids), type=pa.string())
    for batch in table.iter_batches(columns=COLUMNS, batch_size=2048):
        matched = batch.filter(pc.is_in(batch['document_id'], value_set=wanted))
        for row in matched.to_pylist():
            key = row[identity]
            if not key or key in result:
                raise ValueError('Missing or duplicate catalog identity')
            result[key] = row
    return result


def compare_case(proposal, original, document, sources, review):
    """Report label differences, not accuracy; unavailable bodies have no verdict."""
    key = proposal['document_id']
    if any(proposal.get(f) is not False for f in ['independent_reference', 'release_approved']):
        raise ValueError('Require unapproved assistant proposal')
    if (original['document_id'] != key or document['document_id'] != key
            or proposal['source_row_sha256'] != row_digest(original)):
        raise ValueError('Proposal does not bind the exact original row')
    if sorted(document.get('document_kind') or []) != original['after_kind']:
        raise ValueError('Catalog selected kinds differ from the bound ledger')
    expected_members = {r['source_id']: r for r in original['members']}
    actual_members = {r['source_id']: r for r in sources}
    if (len(actual_members) != len(sources) or len(expected_members) != len(original['members'])
            or set(expected_members) != set(actual_members)):
        raise ValueError('Catalog source membership differs from the ledger')
    for sid, row in actual_members.items():
        if row['document_id'] != key or any(row.get(f) != expected_members[sid].get(f)
                for f in ['body_key', 'filename', 'source_url']):
            raise ValueError('Catalog source identity differs from the ledger')
    forms = proposal['proposed_primary_forms'] + proposal['proposed_component_forms']
    if len(forms) != len(set(forms)):
        raise ValueError('Duplicate proposed form')
    if review:
        observed = review['observation']
        evidence = proposal.get('evidence') or {}
        if (review['source_row_sha256'] != row_digest(original)
                or proposal['status'] != 'assistant_proposal'
                or set(forms) != set(observed['observed_document_forms'])
                or any(evidence.get(f) != observed[f] for f in ['body_key', 'sha256', 'pages'])
                or any(evidence.get(f) != review[f] for f in ['receipt', 'receipt_sha256'])):
            raise ValueError('Proposal differs from its complete content review')
    elif proposal['status'] != 'unresolved_no_body' or forms or proposal.get('evidence'):
        raise ValueError('Unavailable case must not assert reviewed forms')
    selected = set(document.get('document_kind') or [])
    content = set(document.get('content_document_kind') or [])
    return dict(document_id=key, filename=original['filename'], source_count=len(sources),
                source_ids=sorted(actual_members), selected_kinds=sorted(selected),
                selected_kind_sources=document.get('document_kind_source') or [],
                filename_kinds=document.get('filename_document_kind') or [],
                retained_content_kinds=sorted(content), reviewed_forms=sorted(forms),
                label_comparison=('same_labels' if selected == set(forms) else 'different_labels')
                    if review else 'not_comparable_no_body',
                content_comparison=('same_labels' if content == set(forms) else 'different_labels')
                    if review and content else 'absent' if review else 'not_comparable_no_body',
                selected_only_labels=sorted(selected - set(forms)) if review else None,
                review_only_forms=sorted(set(forms) - selected) if review else None,
                proposal_handling=proposal['handling'], source_row_sha256=row_digest(original))


def run(proposals, checkpoint, catalog_summary, sources, documents, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    bindings = {str(checkpoint): file_digest(checkpoint), str(catalog_summary): file_digest(catalog_summary),
                str(Path(__file__)): file_digest(__file__)}
    cp = json.loads(Path(checkpoint).read_text())
    proposal_path = verified(proposals, cp['outputs'][str(proposals)], bindings)
    spec = json.loads(proposal_path.read_text())
    if any(spec.get(f) is not False for f in ['classification_mutations', 'independent_reference', 'release_approved']):
        raise ValueError('Require unapproved assistant proposals')
    for path, digest in cp['inputs'].items():
        verified(path, digest, bindings)
    original_path = verified(spec['original_ledger'], spec['original_ledger_sha256'], bindings)
    originals = read_ledger(original_path)
    reviews = load_reviews(spec['receipt'], spec['receipt_sha256'], bindings)
    cases = spec['records']
    ids = {p['document_id'] for p in cases}
    if len(ids) != len(cases) or ids != {k for k, r in originals.items() if r['review_basis'] == 'needs_review'}:
        raise ValueError('Proposals must cover the complete needs_review set exactly once')
    summary = json.loads(Path(catalog_summary).read_text())
    if summary['outputs']['ledger.jsonl'] != spec['original_ledger_sha256']:
        raise ValueError('Catalog evidence summary does not bind the original ledger')
    for path in [sources, documents]:
        verified(path, summary['bindings'][str(path)], bindings)
    source_rows = selected_rows(sources, ids, 'source_id')
    document_rows = selected_rows(documents, ids, 'document_id')
    if set(document_rows) != ids:
        raise ValueError('Missing selected catalog document')
    members = defaultdict(list)
    for row in source_rows.values():
        members[row['document_id']].append(row)
    comparisons = [compare_case(p, originals[p['document_id']], document_rows[p['document_id']],
                               members[p['document_id']], reviews.get(p['document_id'])) for p in cases]
    for path, digest in bindings.items():
        verified(path, digest, {})
    output.mkdir(parents=True)
    with (output / 'comparisons.jsonl').open('x') as stream:
        for row in comparisons:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    columns = ['document_id', 'filename', 'source_count', 'selected_kinds', 'retained_content_kinds',
               'reviewed_forms', 'label_comparison', 'content_comparison', 'proposal_handling']
    with (output / 'comparisons.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in comparisons:
            writer.writerow({k: '|'.join(row[k]) if isinstance(row[k], list) else row[k] for k in columns})
    result = dict(records=len(comparisons), source_rows=len(source_rows),
                  label_comparison=dict(Counter(r['label_comparison'] for r in comparisons)),
                  content_comparison=dict(Counter(r['content_comparison'] for r in comparisons)),
                  documents_with_retained_content=sum(bool(r['retained_content_kinds']) for r in comparisons),
                  bindings=bindings, outputs={name: file_digest(output / name)
                    for name in ['comparisons.jsonl', 'comparisons.csv']}, classification_mutations=False,
                  independent_reference=False, release_approved=False,
                  limitations='Saved historical catalog comparison, not fresh-catalog qualification or accuracy measurement. '
                    'Labels are compared literally; specificity, context and component differences are not automatically errors. '
                    'Projected fields suffice for comparison, not a full regrouping or refresh replay.')
    (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['proposals', 'checkpoint', 'catalog-summary', 'sources', 'documents', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({k: v for k, v in result.items() if k not in ['bindings', 'outputs']}, indent=2))
