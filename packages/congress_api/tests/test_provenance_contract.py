"""B7/B8 public provenance schemas refuse malformed records before raw I/O."""
import pytest

from congress_api.retention.provenance import validate_provenance,write_records

STAMP='2026-10-27T12:00:00Z'


def recovery():
    return dict(id='recovery-decision',original_url='https://docs.house.gov/original.pdf',
        recovered_url='https://archive.example/copy.pdf',recovered_filename=None,
        body_sha256='a'*64,kind='rejected',match_basis='verified_archive_capture',
        evidence_sha256='e'*64,identity_note=None,decided_by='owner',decided_at=STAMP,supersedes=None)


def review():
    return dict(id='review-decision',target='a'*16,verdict='kind_override',value=['letter'],
                note='Retained file inspected',reviewer='assistant',decided_at=STAMP,supersedes=None)


class NoWrites:
    def put(self,*args,**kwargs):
        raise AssertionError('Malformed provenance reached raw storage')


@pytest.mark.parametrize('field,value',[
    ('original_url',None),('original_url',42),('original_url',['https://docs.house.gov/a']),
    ('original_url','/relative.pdf'),('original_url','ftp://docs.house.gov/a'),('original_url','https:///a'),
    ('recovered_url',42),('recovered_url',[]),('recovered_url','/relative.pdf'),
    ('recovered_url','ftp://archive.example/a'),('recovered_url','https:///a'),
    ('recovered_filename',42),('recovered_filename',['copy.pdf']),
    ('body_sha256',None),('body_sha256',42),('body_sha256',['a'*64]),('body_sha256','not-a-digest'),
    ('evidence_sha256','not-a-digest'),('evidence_sha256',42),('evidence_sha256',['e'*64]),
    ('kind',['rejected']),('kind',True),('kind',None),('kind','  '),
    ('match_basis',42),('match_basis',[]),('match_basis','  '),
    ('identity_note',42),('identity_note',['note']),
    ('decided_by',True),('decided_by',None),('decided_by',[]),('decided_by','  '),
])
def test_malformed_recovery_schema_refuses_before_raw_io(field,value):
    row=dict(recovery(),**{field:value})
    with pytest.raises(ValueError):
        write_records(NoWrites(),'recoveries',[row],timestamp='20261027T120000Z')


@pytest.mark.parametrize('field,value',[
    ('note',[]),('note',42),('note',False),
    ('reviewer',True),('reviewer',None),('reviewer',[]),('reviewer','  '),
    ('target',42),('target',{'hex':'a'*16}),('verdict',['kind_override']),
])
def test_malformed_review_schema_refuses_before_raw_io(field,value):
    row=dict(review(),**{field:value})
    with pytest.raises(ValueError):
        write_records(NoWrites(),'reviews',[row],timestamp='20261027T120000Z')


@pytest.mark.parametrize('kind,record',[('recoveries',recovery),('reviews',review)])
def test_every_schema_field_remains_required(kind,record):
    for field in record():
        row=record();del row[field]
        with pytest.raises(ValueError):
            write_records(NoWrites(),kind,[row],timestamp='20261027T120000Z')


def test_nullable_audit_text_and_digest_preserve_honest_unknowns():
    row=dict(recovery(),recovered_url=None,recovered_filename=None,match_basis=None,
             evidence_sha256=None,identity_note=None)
    assert validate_provenance('recoveries',row) is row
    assert validate_provenance('reviews',dict(review(),note=None))['note'] is None


def test_url_spelling_and_category_vocabulary_are_not_rewritten():
    row=dict(recovery(),original_url='HTTPS://Docs.House.Gov/Some File.pdf?Document=MixedCase',
        recovered_url='https://Archive.Example/COPY.PDF',recovered_filename='Original File.PDF',
        kind='explicit-profile-kind')
    expected=dict(row)
    assert validate_provenance('recoveries',row)==expected


def test_explicit_owner_recovery_supersedes_without_mutating_the_base(tmp_path):
    import json
    from congress_api.cli.provenance import main
    from congress_api.retention.provenance import load_stage
    base=dict(recovery(),id='base-decision',kind='recovered_document',decided_by='reconciliation')
    owner=dict(base,id='owner-decision',kind='requested_content_in_official_hearing',
               decided_by='owner',decided_at='2026-10-27T21:28:14Z',supersedes=base['id'])
    staged=[]
    for name,row in [('base',base),('owner',owner)]:
        records=tmp_path/(name+'.jsonl')
        records.write_text(json.dumps(row)+'\n')
        root=tmp_path/name
        main(['--records',str(records),'--kind','recoveries','--decided-at',row['decided_at'],'--stage',str(root)])
        _,manifest=load_stage(root)
        path=root/manifest['provenance']
        staged.append((path,path.read_bytes()))
        assert json.loads(path.read_text())==row
    assert staged[0][0].read_bytes()==staged[0][1]
    assert owner['supersedes']==base['id'] and owner['kind']!='rejected'
