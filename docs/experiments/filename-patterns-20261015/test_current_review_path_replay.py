from copy import deepcopy
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from catalog_filename_replay import normalized
from current_review_path_replay import changes, audit_scenario, run
from packet_review_candidate import apply_review, group_digest, bind_review
from packet_review_replay import exercise_paths
from pilot_reconcile import file_digest
from test_catalog_filename_replay import baseline
from test_review_catalog_reconcile import current_case


def scenario():
    p,o,d,m,s,r=current_case()
    candidate=apply_review(d,m,bind_review(p,o,d,m,r))
    return m,[d],{d['document_id']:candidate}


def test_unchanged_scenario_and_null_padding_preserve_candidates():
    sources,documents,candidates=scenario()
    result=audit_scenario([dict(sources[0],new_null=None)],documents,sources,documents,candidates)
    assert result['baseline_semantics_unchanged'] and result['candidates_identical']
    assert result['candidate_status']=={'candidate_applied':1}
    assert result['withdrawal_restores_present_baselines']


@pytest.mark.parametrize('field',['body_key','filename','source_occurrences'])
def test_changed_values_are_retained_and_binding_is_not_replaced(field):
    sources,documents,candidates=scenario();changed=deepcopy(sources)
    changed[0][field]=[{'source_link_label':['changed literal claim']}] if field=='source_occurrences' else 'replacement'
    result=audit_scenario(changed,documents,sources,documents,candidates)
    assert not result['baseline_semantics_unchanged'] and not result['candidates_identical']
    assert result['candidate_status']=={'scope_changed':1}
    assert result['source_changes']['fields']['source'][field]['after']==changed[0][field]


def test_added_and_missing_groups_remain_explicit():
    sources,documents,candidates=scenario()
    result=audit_scenario([],[],sources,documents,candidates)
    assert result['candidate_status']=={'missing_document':1}
    assert result['document_changes']['missing_ids']==['document']
    extra=dict(documents[0],document_id='extra')
    result=audit_scenario(sources,[*documents,extra],sources,documents,candidates)
    assert result['document_changes']['added_ids']==['extra']
    assert not result['baseline_semantics_unchanged']


def test_duplicate_identity_is_rejected():
    with pytest.raises(ValueError,match='Duplicate'):
        changes([], [dict(source_id='s')]*2,'source_id')


def test_shared_scenarios_execute_real_groupers_cache_and_both_refresh_modes(tmp_path,monkeypatch):
    from congress_api.retention import document_index as index
    root=baseline(tmp_path);source=pq.ParquetFile(root/'indexes/document-filenames.parquet')
    documents=pq.ParquetFile(root/'indexes/documents.parquet');out=tmp_path/'paths';out.mkdir()
    monkeypatch.setattr(index,'read_retained_body',lambda *a:pytest.fail('Body read during metadata replay'))
    seen={}
    def verify(name,sources,docs,stats=None):
        seen[name]=(len(sources),len(docs),stats)
    exercise_paths(source,documents,source.read().to_pylist(),out,verify)
    assert list(seen)==['reference_grouper','reference_reversed_alias_order','disk_grouper',
        'cached_disk_groups','metadata_refresh_reuse','metadata_refresh_reparse']
    assert all(s==source.metadata.num_rows and d==documents.metadata.num_rows for s,d,_ in seen.values())
    assert seen['cached_disk_groups'][2]['reused_document_groups']==documents.metadata.num_rows


@pytest.mark.parametrize('tamper',[False,True])
def test_current_replay_integration_on_bound_saved_candidate(tmp_path,tamper):
    root=baseline(tmp_path);directory=tmp_path/'current';directory.mkdir()
    selected={}
    for name,identity in [('document-filenames.parquet','source_id'),('documents.parquet','document_id')]:
        table=pq.read_table(root/'indexes'/name)
        rows=[r for r in table.to_pylist() if r['filename']=='opaque.pdf']
        assert len(rows)==1
        pq.write_table(pa.Table.from_pylist(rows,schema=table.schema),directory/name)
        selected[identity]=normalized(rows[0])
    s,d=selected['source_id'],selected['document_id']
    review=dict(document_id=d['document_id'],group_sha256=group_digest(d,[s]),observed_forms=['report'],
                primary_forms=['report'],component_forms=[],reviewer='assistant',independent_reference=False,release_approved=False)
    # Unsupported form exercises annotation preservation in every real path.
    candidate=apply_review(d,[s],review)
    candidates=directory/'candidates.jsonl';candidates.write_text(json.dumps(candidate)+'\n')
    summary=directory/'summary.json';summary.write_text(json.dumps(dict(bindings={},
        outputs={p.name:file_digest(p) for p in directory.iterdir() if p.is_file()})))
    checkpoint=tmp_path/'checkpoint.json';checkpoint.write_text(json.dumps(dict(summary_path=str(summary),summary_sha256=file_digest(summary))))
    if tamper:
        candidates.write_text('{}\n')
        with pytest.raises(ValueError,match='digest'):run(checkpoint,tmp_path/'result')
        assert not (tmp_path/'result').exists()
    else:
        result=run(checkpoint,tmp_path/'result')
        assert len(result['scenarios'])==7
        # This older fixture has an unsupported content_title field and lacks
        # the current name_token. Reparsing must expose both changes, not rebind.
        assert not result['all_baselines_unchanged'] and not result['all_candidates_identical']
        for name,scenario in result['scenarios'].items():
            if name!='metadata_refresh_reparse':
                assert scenario['baseline_semantics_unchanged'] and scenario['candidates_identical']
        changed=result['scenarios']['metadata_refresh_reparse']
        assert changed['candidate_status']=={'scope_changed':1}
        diagnostic=json.loads((tmp_path/'result/metadata_refresh_reparse.json').read_text())
        assert set(next(iter(diagnostic['source_changes']['fields'].values())))=={'content_title','name_token'}
        assert not result['review_rebinding'] and not result['production_changes']
        with pytest.raises(FileExistsError):run(checkpoint,tmp_path/'result')
