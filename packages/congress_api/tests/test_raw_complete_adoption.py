"""Maintained adoption composes source custody, typed raw values and readings."""
from pathlib import Path
import json

import pytest

from congress_api.retention import raw_adoption
from congress_api.retention.raw_storage import RAW_KEY, RawStorage
from congress_api.retention.catalog_cache import save_results
from congress_api.retention.capture_metadata import PREFIX, restore_readings
from congress_api.retention.raw_archive import Archive
from native_memory_helpers import memory_raw_storage
from test_raw_adoption import inputs
from testing_fakes import SelectorStore
from test_raw_readings import part


def setup(tmp_path):
    store=SelectorStore();paths,hashes,captures,states=inputs(tmp_path)
    capture=part(store,'capture','body:a')
    part(store,'capture-only','body:b','failed')
    save_results(store,'bodies','legacy-reader',('reader','body_key'),{
        ('document','body:a'):{'body_format':['pdf'],'content_title':['Exact',None,'Exact']},
        ('cover','body:a'):{},('xml','body:c'):{}})
    owner=memory_raw_storage(store,state_schema=states.schema,max_state_rows=3,max_capture_rows=3)
    options=dict(paths=paths,sha256s=hashes,operation='complete-adoption',directory=tmp_path/'operation',
        filename_version=dict(selector_sha256=None,selected_ref=None))
    return store,owner,options,captures,states


def test_complete_adoption_uses_exact_sources_and_streaming_owner(tmp_path,monkeypatch):
    from congress_api.retention import raw_archive
    store,owner,options,captures,states=setup(tmp_path)
    original=dict(store.objects)
    assert not hasattr(raw_archive, 'LegacyArchiveSeed')
    monkeypatch.setattr(raw_archive,'LegacyArchiveSeed',lambda *a,**k:pytest.fail('Full compatibility reconstruction'), raising=False)
    owner.readings.prepare=lambda *a,**k:pytest.fail('All-body dictionary')
    selected=raw_adoption.adopt_archive(owner,**options)
    assert selected.captures().equals(captures) and selected.states().equals(states)
    cache={};restore_readings(selected.body_readings(['body:a','body:b','body:c']),cache)
    assert cache[('cover','body:a')]=={} and cache[('xml','body:c')]=={}
    assert cache[('document','body:a')]['content_title']==['Exact',None,'Exact']
    assert all(store.objects[key]==value for key,value in original.items())
    assert store.writes.count(RAW_KEY)==1
    keys=store.keys
    store.keys=lambda prefix:pytest.fail('Global reading discovery') if prefix.startswith('indexes/processing/') else keys(prefix)
    archive=Archive(store,'native-startup',storage=owner)
    assert archive.selected.has_body_reading('body:c')


def test_complete_adoption_resumes_with_retained_inputs_and_completed_native_pins(tmp_path):
    store,owner,options,captures,states=setup(tmp_path)
    run=owner.native.run_table;calls=0
    def interrupt(table,**kwargs):
        nonlocal calls
        calls+=1
        if calls==3: raise RuntimeError('Worker lost')
        return run(table,**kwargs)
    owner.native.run_table=interrupt
    with pytest.raises(RuntimeError,match='Worker lost'):
        raw_adoption.adopt_archive(owner,**options)
    assert RAW_KEY not in store.objects and (options['directory']/'reading-inputs.json').is_file()
    completed=list(owner.native.writes)
    owner.native.run_table=run
    fresh=RawStorage(store,owner.native,state_schema=states.schema,max_state_rows=3,max_capture_rows=3)
    selected=raw_adoption.adopt_archive(fresh,**options)
    assert selected.captures().equals(captures)
    assert all(owner.native.writes.count(key)==1 for key in completed)
    assert list(selected.body_readings(['body:c']))[0]['reader']=='xml'


@pytest.mark.parametrize('change',['cache','capture_parts'])
def test_complete_adoption_refuses_changed_source_before_selection(tmp_path,change):
    store,owner,options,_,_=setup(tmp_path)
    run=owner.native.run_table;changed=False
    def mutate(table,**kwargs):
        nonlocal changed
        result=run(table,**kwargs)
        if not changed:
            changed=True
            if change=='cache':store.objects['indexes/processing/bodies.parquet']=b'changed'
            else:part(store,'appeared-later','body:new')
        return result
    owner.native.run_table=mutate
    with pytest.raises(ValueError,match='changed during adoption'):
        raw_adoption.adopt_archive(owner,**options)
    assert RAW_KEY not in store.objects


def test_completed_adoption_retry_keeps_later_readings_and_does_not_scan_history(tmp_path):
    store,owner,options,_,_=setup(tmp_path)
    selected=raw_adoption.adopt_archive(owner,**options)
    newer=part(store,'new-reading','body:a','failed')
    later=owner.publish(owner.prepare(selected,operation='later',reading_parts=[newer],replace_readings=['body:a']))
    before=list(store.writes),list(owner.native.writes)
    store.keys=lambda *a,**k:pytest.fail('Completed retry rescanned source inventory')
    replay=raw_adoption.adopt_archive(owner,**options)
    assert replay.identity==later.identity
    assert list(replay.body_readings(['body:a']))[0]['status']=='failed'
    assert (store.writes,owner.native.writes)==before


def test_prepare_reading_input_rejects_invalid_retained_path_identity(tmp_path):
    from congress_api.retention.raw_adoption_inputs import prepare_reading_input
    store=SelectorStore();receipt=tmp_path/'reading-inputs.json'
    receipt.write_text(json.dumps(dict(version=1,cache=dict(key='indexes/processing/bodies.parquet'),
        input=dict(sha256='../elsewhere',bytes=4))))
    with pytest.raises(ValueError,match='input identity'):
        prepare_reading_input(store,directory=tmp_path)
    assert not store.writes


def test_actual_native_complete_adoption_recovers_with_exact_pins_and_rich_state(tmp_path):
    import os
    import shutil
    from native_test_helpers import native_test_client
    binary=os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    store,fixture,options,captures,states=setup(tmp_path)
    native=native_test_client(binary,tmp_path/'native')
    owner=RawStorage(store,native,state_schema=states.schema,max_state_rows=3,max_capture_rows=3)
    run=native.run_table;completed=[]
    def interrupted(table,**kwargs):
        if len(completed)==2:raise RuntimeError('Native worker lost')
        pin=run(table,**kwargs);completed.append(pin)
        return pin
    native.run_table=interrupted
    with pytest.raises(RuntimeError,match='Native worker lost'):
        raw_adoption.adopt_archive(owner,**options)
    assert RAW_KEY not in store.objects
    fresh=native_test_client(binary,tmp_path/'native')
    resumed=RawStorage(store,fresh,state_schema=states.schema,max_state_rows=3,max_capture_rows=3)
    selected=raw_adoption.adopt_archive(resumed,**options)
    assert selected.states().equals(states) and selected.captures().equals(captures)
    pins=list(resumed.capture_pages.entries(selected.manifest['captures']['head']))
    assert [entry['release'] for entry in pins[:2]]==completed
    cache={};restore_readings(selected.body_readings(['body:a','body:b','body:c']),cache)
    assert cache[('cover','body:a')]=={} and cache[('xml','body:c')]=={}
    assert cache[('document','body:a')]['content_title']==['Exact',None,'Exact']
