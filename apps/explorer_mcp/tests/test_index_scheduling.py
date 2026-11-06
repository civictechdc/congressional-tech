"""Eligible indexed work remains ordered, selective and reversible."""
from contextlib import closing
import json

from congressional_explorer_mcp.index_builder import (_next_body_query,_exclude_ineligible_pending,qualify_caption_sources)
from congressional_explorer_mcp.text_index import connect,initialize
from congressional_explorer_mcp.release import encoded


def body(db,key,kind='document',state='pending',extra=None,units=0):
    db.execute('INSERT INTO bodies(body_key,target,state,extra,units) VALUES(?,?,?,?,?)',
        [key,encoded(dict(unit_kind=kind)).decode(),state,encoded(extra or {}).decode(),units])


def source(db,key,body_key,*,reason=None,seen='current',context=None,kind='document'):
    db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?)',[key,body_key,kind,encoded(context or {}).decode(),seen,reason])


def next_key(db,selected=None):
    row=db.execute(*_next_body_query('current',selected)).fetchone()
    return row['body_key'] if row else None


def test_ordered_eligible_work_and_small_source_key_plan(tmp_path):
    with closing(connect(tmp_path/'work.sqlite')) as db:
        initialize(db)
        for key,kind in [('00-blocked','playlist'),('01-child','caption'),('02-document','document'),('03-playlist','playlist')]:
            body(db,key,kind)
        source(db,'missing','00-blocked',reason='unavailable: retained playlist resource map missing',kind='caption')
        source(db,'child','01-child',reason='pending: playlist root verification',kind='caption')
        source(db,'retired','02-document',seen='older')
        source(db,'doc','02-document')
        source(db,'playlist','03-playlist',kind='caption')
        _exclude_ineligible_pending(db,'current')
        assert db.execute("SELECT count(*) FROM bodies WHERE state='excluded: no eligible source'").fetchone()[0]==2
        plan=[row['detail'] for row in db.execute('EXPLAIN QUERY PLAN '+_next_body_query('current')[0],_next_body_query('current')[1])]
        assert any('pending_body_order' in row for row in plan)
        assert any('source_body_generation_order' in row for row in plan)
        assert not any('TEMP B-TREE' in row or 'LIST SUBQUERY' in row for row in plan)
        assert next_key(db)=='03-playlist'
        assert next_key(db,['doc','doc'])=='02-document'
        sql,args=_next_body_query('current',['doc','playlist'])
        small_plan=[row['detail'] for row in db.execute('EXPLAIN QUERY PLAN '+sql,args)]
        assert any('sqlite_autoindex_sources_1' in row for row in small_plan)
        assert not any('source_generation' in row for row in small_plan)
        assert next_key(db,['missing','child','retired']) is None
        db.execute("UPDATE bodies SET state='indexed' WHERE body_key='03-playlist'")
        assert next_key(db)=='02-document'
        db.execute("UPDATE bodies SET state='indexed' WHERE body_key='02-document'")
        assert next_key(db) is None
        # Shared-source eligibility and a normal retry reset preserve membership.
        source(db,'direct-child','01-child',kind='caption')
        qualify_caption_sources(db,'current')
        assert next_key(db)=='01-child'
        db.execute("UPDATE bodies SET state='retryable' WHERE body_key='01-child'")
        assert next_key(db) is None
        db.execute("UPDATE bodies SET state='pending' WHERE state='retryable'")
        _exclude_ineligible_pending(db,'current')
        assert next_key(db)=='01-child'


def caption(db,identity,root_key,ordinal,child_key=None,event=None,reason=None):
    context=dict(reference=dict(source_id=identity,event_id=event),root_key=root_key,resource_ordinal=ordinal,
        playlist=True,declared_uri='child.vtt' if ordinal else None)
    source(db,f'{identity}:{event}:{ordinal}',root_key if ordinal==0 else child_key,
        reason=reason,context=context,kind='caption')


def test_scoped_playlist_reenrolls_shared_occurrences_without_touching_other_roots(tmp_path):
    with closing(connect(tmp_path/'work.sqlite')) as db:
        initialize(db)
        body(db,'root-shared','playlist');body(db,'root-other','playlist')
        body(db,'child','caption',state='excluded: no eligible source')
        body(db,'other-child','caption',state='excluded: no eligible source')
        for identity,event in [('a',1),('a',2),('b',3)]:
            caption(db,identity,'root-shared',0,event=event)
            caption(db,identity,'root-shared',1,'child',event=event,reason='pending: playlist root verification')
        source(db,'missing-map',None,kind='caption',reason='unavailable: retained playlist resource map missing',
            context=dict(reference=dict(source_id='missing'),root_key='root-shared',resource_ordinal=0,playlist=True))
        caption(db,'c','root-other',0,event=4)
        caption(db,'c','root-other',1,'other-child',event=4,reason='pending: playlist root verification')
        qualify_caption_sources(db,'current')
        unaffected=db.execute("SELECT value FROM root_coverage WHERE source_id='c'").fetchone()[0]
        db.execute("UPDATE bodies SET state='manifest',extra=? WHERE body_key='root-shared'",[encoded(dict(uris=['child.vtt'],endlist=True,publisher_snapshot='closed')).decode()])
        statements=[];db.set_trace_callback(statements.append)
        qualify_caption_sources(db,'current','root-shared')
        db.set_trace_callback(None)
        assert db.execute("SELECT state FROM bodies WHERE body_key='child'").fetchone()[0]=='pending'
        assert db.execute("SELECT state FROM bodies WHERE body_key='other-child'").fetchone()[0]=='excluded: no eligible source'
        assert db.execute("SELECT value FROM root_coverage WHERE source_id='c'").fetchone()[0]==unaffected
        assert db.execute("SELECT count(*) FROM sources WHERE body_key='child' AND reason IS NULL").fetchone()[0]==3
        root_scan=next(sql for sql in statements if sql.startswith('SELECT source_key,context,reason,body_key FROM sources'))
        assert "json_extract(context,'$.root_key')='root-shared'" in root_scan
        updates=[sql for sql in statements if sql.startswith('UPDATE bodies SET state=')]
        assert len(updates)==1 and "body_key='child'" in updates[0]
        assert json.loads(db.execute("SELECT value FROM root_coverage WHERE source_id='a'").fetchone()[0])['archive_state']=='pending'
        missing=json.loads(db.execute("SELECT value FROM root_coverage WHERE source_id='missing'").fetchone()[0])
        assert missing['publisher_snapshot']=='closed' and missing['archive_state']=='unavailable'
        assert next_key(db)=='root-other'  # A remaining eligible playlist precedes the newly eligible child.
        db.execute("UPDATE bodies SET state='indexed',units=2 WHERE body_key='child'")
        qualify_caption_sources(db,'current','root-shared')
        expected={row['source_id']:row['value'] for row in db.execute('SELECT * FROM root_coverage')}
        qualify_caption_sources(db,'current')
        assert {row['source_id']:row['value'] for row in db.execute('SELECT * FROM root_coverage')}==expected
        assert json.loads(expected['a'])['indexed_cues']==2  # Repeated event occurrences do not duplicate cues.


def test_invalid_parent_cannot_remove_an_eligible_shared_child(tmp_path):
    with closing(connect(tmp_path/'work.sqlite')) as db:
        initialize(db)
        body(db,'bad-root','playlist',state='unreadable')
        body(db,'shared','caption');body(db,'unavailable','caption')
        caption(db,'bad','bad-root',0)
        caption(db,'bad','bad-root',1,'shared')
        source(db,'direct','shared',kind='caption')
        source(db,'only-unavailable','unavailable',reason='unavailable: caption resource not retained',kind='caption')
        qualify_caption_sources(db,'current','bad-root')
        _exclude_ineligible_pending(db,'current')
        assert db.execute("SELECT state FROM bodies WHERE body_key='shared'").fetchone()[0]=='pending'
        assert db.execute("SELECT state FROM bodies WHERE body_key='unavailable'").fetchone()[0]=='excluded: no eligible source'
        assert next_key(db)=='shared'
