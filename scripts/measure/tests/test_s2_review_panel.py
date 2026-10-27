"""S2 acceptance: inspectable labels, covered strata, and explicit uncertainty."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).parents[3]


def test_s2_review_panel_has_evidence_and_expected_coverage():
    contract = json.loads((ROOT / 'model/fixtures/s2-sample-contract.json').read_text())
    panel = json.loads((ROOT / 'docs/measurements/engine-first-20261027/s2-site/sample.json').read_text())
    files, bodies = panel['files'], panel['bodies']
    assert len(files) >= contract['minimum_files']
    assert len({row['body_sha256'] for row in files}) >= contract['minimum_distinct_bodies']
    assert len({row['id'] for row in files}) == len(files)
    coverage = set()
    for row in files:
        assert row['decision'] in contract['decisions']
        assert row['rationale'].strip()
        assert row['reviewer'] in {'site', 'prior_human_review', 'owner'}
        body = bodies[row['body_sha256']]
        for name in ['stored_sha256', 'decoded_sha256']:
            if body[name] is not None:
                assert re.fullmatch('[a-f0-9]{64}', body[name])
        assert row['body_key'].startswith('bodies/')
        assert body['acquisition_status'] == 'inspected' or row['decision'] == 'owner_decision_required'
        if row['decision'] == 'owner_decision_required':
            assert row['owner_question'].strip()
        else:
            assert body['stored_sha256'] and body['decoded_sha256'] == row['body_sha256']
            assert body['excerpt'] or body['title'] or body.get('format_evidence')
        assert row['context_url'] or row.get('historical_review')
        coverage.update(row['strata'])
    assert set(contract['required_strata']) <= coverage
    assert panel['prior_rule_labels_are_truth'] is False
    assert panel['population_accuracy_claimed'] is False
    assert len([row for row in files if row.get('historical_review')]) == 29
    for relation in panel['relationships']:
        assert relation['decision'] in {'same_document', 'separate_documents', 'owner_decision_required'}
        assert relation['rationale'] and relation['evidence']
        assert relation['files'] and set(relation['files']) <= {row['id'] for row in files}
        if relation['decision'] == 'owner_decision_required':
            assert relation['owner_question']


def test_owner_decisions_are_a_new_version_with_the_four_applied_rules():
    import hashlib
    path=ROOT/'docs/measurements/engine-first-20261027/s2-site/sample.json'
    old=json.loads(path.read_text())
    new=json.loads(path.with_name('sample-v2.json').read_text())
    assert old['version']==1 and new['version']==2
    assert new['previous_version_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    before={x['id']:x for x in old['files']}
    changed=[x for x in new['files'] if before[x['id']]['decision']=='owner_decision_required']
    assert len(changed)==47
    assert all(x['reviewer']=='owner' and x['applied_rule'] and x['prior_rationale'] for x in changed)
    assert all(x['decision']!='owner_decision_required' for x in new['files'])
    assert sum(x['applied_rule']=='frontmatter_package_pointer' for x in changed)==38
    assert sum(x['applied_rule']=='separate_document_overview' for x in changed)==6
    oneoffs={x['id']:(x['decision'],x['applied_rule']) for x in changed if x['id'] in {'p059','p064','p118','p165'}}
    assert oneoffs=={'p059':('real_document','self_contained_document'),
        'p064':('real_document','self_contained_document'),
        'p118':('download_wrapper','preview_access_pointer'),
        'p165':('landing','frontmatter_package_pointer')}
    assert new['bodies']==old['bodies'] and new['relationships']==old['relationships']
    assert {x['id']:x for x in new['files'] if x['id'] not in {r['id'] for r in changed}}=={
        x['id']:x for x in old['files'] if x['decision']!='owner_decision_required'}
