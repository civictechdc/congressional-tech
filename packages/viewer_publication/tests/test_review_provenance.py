"""B8: published kind selections follow their stable body link keys."""
from hashlib import sha256
import json
import os

import pytest

from docspec_client.client import NativeDatasets
from congress_api.retention.provenance import record_review, apply_staged
from viewer_publication.review_provenance import stage_reviews
from congress_api.retention.body_store import BodyStore,LocalAdapter

STAMP='2026-10-27T12:00:00Z'


def inputs(tmp_path):
    bodies=['1'*64,'2'*64]
    rows=[dict(document_id='doc-'+str(i),status='candidate_applied' if i==0 else 'annotation_only_unsupported_forms',
        selected=dict(document_kind=['witness-statement'] if i==0 else ['attachment']),
        review=dict(primary_forms=['witness-statement'] if i==0 else ['unapproved-form'],
            component_forms=[],body_observation=dict(sha256=body,notes='Original review note')))
        for i,body in enumerate(bodies)]
    value=dict(version=1,catalog_id='catalog',review_sha256='a'*64,rows=rows,files={})
    data=json.dumps(value).encode();reviews=tmp_path/'reviews.json';reviews.write_bytes(data)
    descriptor=tmp_path/'descriptor.json';descriptor.write_text(json.dumps(dict(
        sha256=sha256(data).hexdigest(),bytes=len(data),groups=2,catalog_id='catalog',review_sha256='a'*64)))
    identities=tmp_path/'identities.json';identities.write_text(json.dumps(dict(version=1,
        catalog_id='catalog',review_sha256='a'*64,rows=[dict(index=i,document_id='doc-'+str(i),
        body_key=f'bodies/sha256/{body[:2]}/{body}.gz',source_ids=['source-'+str(i)])
        for i,body in enumerate(bodies)])))
    return reviews,descriptor,identities


def test_native_review_join_keeps_published_selected_values(tmp_path):
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    reviews,descriptor,identities=inputs(tmp_path)
    result=stage_reviews(reviews,descriptor,identities,output=tmp_path/'stage',engine=engine,
                         decided_at=STAMP)
    assert result['records']==2
    records=[json.loads(line) for line in (tmp_path/'stage'/result['provenance']).read_text().splitlines()]
    assert [r['target'] for r in records]==['1'*16,'2'*16]
    assert [r['value'] for r in records]==[['witness-statement'],['attachment']]
    assert all(r['reviewer']=='assistant' and r['verdict']=='kind_override' and r['decided_at']==STAMP for r in records)
    assert all('Original review note' in r['note'] for r in records)
    assert apply_staged(tmp_path/'stage',BodyStore(LocalAdapter(tmp_path/'raw')))['objects']==1
    assert (tmp_path/'raw'/result['provenance']).is_file()


def test_mismatched_publication_is_refused_without_engine_call(tmp_path):
    reviews,descriptor,identities=inputs(tmp_path);reviews.write_text('{}')
    class Engine:
        def run_job(self,*args):raise AssertionError('bad pins reached engine')
    with pytest.raises(ValueError,match='pinned|pins'):
        stage_reviews(reviews,descriptor,identities,output=tmp_path/'stage',engine=Engine(),decided_at=STAMP)
    assert not (tmp_path/'stage').exists()


def test_missing_identity_cannot_drop_review_silently(tmp_path):
    reviews,descriptor,identities=inputs(tmp_path)
    value=json.loads(identities.read_text());value['rows'].pop();identities.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        stage_reviews(reviews,descriptor,identities,output=tmp_path/'stage',engine=None,decided_at=STAMP)
    assert not (tmp_path/'stage').exists()


def test_new_review_and_withdrawal_remain_append_only(tmp_path):
    store=BodyStore(LocalAdapter(tmp_path/'raw'))
    row=dict(id='review-one',target='1'*16,verdict='kind_override',value=['letter'],
             note='Assistant inspected retained file',reviewer='assistant',decided_at=STAMP,supersedes=None)
    key=record_review(store,row,timestamp='20261027T120000Z')
    withdrawn=dict(row,id='review-two',verdict='withdraw',value=None,supersedes='review-one')
    other=record_review(store,withdrawn,timestamp='20261027T120001Z')
    assert key!=other and json.loads((tmp_path/'raw'/key).read_text())==row
    assert json.loads((tmp_path/'raw'/other).read_text())==withdrawn
    with pytest.raises(RuntimeError,match='reused'):
        record_review(store,row,timestamp='20261027T120000Z')


def test_new_review_cli_stages_before_explicit_owner_apply(tmp_path,capsys):
    from congress_api.cli.provenance import main
    row=dict(id='authored-review',target='a'*16,verdict='title_override',value='Corrected title',
             note='Owner-authored correction',reviewer='owner',decided_at=STAMP,supersedes=None)
    source=tmp_path/'review.jsonl';source.write_text(json.dumps(row)+'\n')
    main(['--records',str(source),'--kind','reviews','--decided-at',STAMP,'--stage',str(tmp_path/'stage')])
    report=json.loads(capsys.readouterr().out)
    assert report['records']==1 and report['kind']=='reviews'
    assert (tmp_path/'stage'/report['provenance']).read_text()==json.dumps(row,separators=(',',':'))+'\n'
    with pytest.raises(ValueError,match='separate|stage'):
        main(['--records',str(source),'--kind','reviews','--decided-at',STAMP,
              '--stage',str(tmp_path/'other'),'--apply'])
