"""Concurrent retention additions and publication refusal at the real writer."""
import json

import pytest

from test_archive_publish import Native, StorageError, Store, candidate, encoded, record
from viewer_publication.archive_publish import POINTER, SPICY_PINS, publish_candidate, write_spicy_generations


def pair(value):
    return dict(family='members',digest=value*64)


class PinStore(Store):
    def __init__(self):
        super().__init__()
        self.pin_version=0;self.before_pin_put=None;self.pin_ack='ok';self.pin_read_etag=True

    def get_object(self,**request):
        result=super().get_object(**request)
        if request['Key']==SPICY_PINS:
            result['ETag']='pins-'+str(self.pin_version) if self.pin_read_etag else None
        return result

    def put_object(self,**request):
        if request['Key']!=SPICY_PINS:return super().put_object(**request)
        if self.before_pin_put is not None:
            hook=self.before_pin_put;self.before_pin_put=None;hook()
        if ('IfMatch' in request and request['IfMatch']!='pins-'+str(self.pin_version)
                or request.get('IfNoneMatch')=='*' and SPICY_PINS in self.objects):
            raise StorageError(412)
        assert 'IfMatch' in request or request.get('IfNoneMatch')=='*'
        super().put_object(**request);self.pin_version+=1
        if self.pin_ack=='lost':raise OSError('pin acknowledgment lost')
        return dict(ETag='pins-'+str(self.pin_version)) if self.pin_ack=='ok' else {}


def add(store,*values):
    return write_spicy_generations(store,bucket='archive-fixture',generations=[pair(v) for v in values])


@pytest.mark.parametrize('present',[False,True])
def test_pin_union_uses_the_token_from_its_own_read(present):
    store=PinStore()
    if present:store.objects[SPICY_PINS]=encoded(dict(version=1,generations=[pair('a')]))
    result=add(store,'b')
    assert result['generations']==([pair('a'),pair('b')] if present else [pair('b')])
    request=store.requests[0]
    assert request.get('IfMatch')==('pins-0' if present else None)
    assert request.get('IfNoneMatch')==(None if present else '*')
    assert len(store.requests)==1


def test_stale_addition_refuses_and_fresh_addition_preserves_both_writers():
    store=PinStore();add(store,'a')
    store.before_pin_put=lambda:add(store,'b')
    with pytest.raises(StorageError):add(store,'c')
    assert json.loads(store.objects[SPICY_PINS])['generations']==[pair('a'),pair('b')]
    assert add(store,'c')['generations']==[pair('a'),pair('b'),pair('c')]
    assert len(store.requests)==3


@pytest.mark.parametrize('existing',[None,[],{},dict(version=True,generations=[]),
    dict(version=1,generations=[dict(family='members')]),
    dict(version=1,generations=[dict(family='',digest='a'*64)]),
    dict(version=1,generations=[dict(family='members',digest='bad')]),
    dict(version=1,generations=[['members','a'*64]])])
def test_malformed_existing_protection_refuses_without_overwrite(existing):
    store=PinStore();raw=encoded(existing);store.objects[SPICY_PINS]=raw
    with pytest.raises(ValueError):add(store,'b')
    assert store.objects[SPICY_PINS]==raw and store.requests==[]


def test_missing_pin_read_token_refuses_even_when_no_addition_is_needed():
    store=PinStore();add(store,'a');store.requests.clear();store.pin_read_etag=False
    with pytest.raises(ValueError,match='no ETag'):add(store,'a')
    assert store.requests==[]


@pytest.mark.parametrize('raw',[
    b'{"version":1,"generations":'+encoded([pair('a')])+b',"generations":[]}',
    b'{"version":1,"generations":[{"family":"members","digest":"'+b'a'*64+b'","digest":"'+b'b'*64+b'"}]}',
])
def test_duplicate_json_fields_cannot_erase_existing_protection(raw):
    store=PinStore();store.objects[SPICY_PINS]=raw
    with pytest.raises(ValueError,match='Duplicate generation-pin'):add(store,'c')
    assert store.objects[SPICY_PINS]==raw and store.requests==[]


def test_addition_cannot_create_an_unreadable_oversized_pin_document(monkeypatch):
    from viewer_publication import archive_publish
    store=PinStore();raw=encoded(dict(version=1,generations=[pair('a')]))
    store.objects[SPICY_PINS]=raw;monkeypatch.setattr(archive_publish,'CONTROL_BYTES',len(raw))
    with pytest.raises(ValueError,match='exceed control byte limit'):add(store,'b')
    assert store.objects[SPICY_PINS]==raw and store.requests==[]


@pytest.mark.parametrize('ack',['lost','missing'])
def test_uncertain_pin_ack_preserves_protection_and_does_not_retry(ack):
    store=PinStore();store.pin_ack=ack
    with pytest.raises((OSError,ValueError)):add(store,'a')
    assert json.loads(store.objects[SPICY_PINS])['generations']==[pair('a')]
    assert len(store.requests)==1
    store.pin_ack='ok'
    assert add(store,'a')['generations']==[pair('a')]
    assert len(store.requests)==1  # An already protected generation needs no PUT.


@pytest.mark.parametrize('unchanged',[False,True])
@pytest.mark.parametrize('failure',['conflict','lost'])
def test_pin_failure_stops_both_publisher_paths_before_pointer_activation(tmp_path,unchanged,failure):
    store=PinStore();artifacts,manifest=candidate(tmp_path)
    value,keys=record(entity_digests={'members':'a'*64});canaries=[]
    pointer=dict(release_id=manifest['release_id']) if unchanged else None
    if pointer is not None:store.objects[POINTER]=encoded(pointer)
    if failure=='conflict':store.before_pin_put=lambda:add(store,'b')
    else:store.pin_ack='lost'
    def passed(**context):return dict(status='passed',releaseId=context['release_id'],targets='owner-approved')
    with pytest.raises((StorageError,OSError)):
        publish_candidate(client=store,engine=Native(store),bucket='archive-fixture',work=tmp_path/'publish',
            **artifacts,input_record=value,receipt_keys=keys,pointer=pointer,
            expected_etag='initial' if unchanged else None,public_origin='https://archive.example.test',
            contract=passed,canary=lambda **kwargs:canaries.append(kwargs),first_release=not unchanged)
    assert store.objects.get(POINTER)==(encoded(pointer) if pointer else None)
    assert not any(r['Key']==POINTER for r in store.requests)
    assert canaries==[]
    assert json.loads(store.objects[SPICY_PINS])['generations']==[pair('b' if failure=='conflict' else 'a')]


def test_maintenance_adds_its_census_without_removing_pending_generation():
    from test_archive_maintenance import LIVE,NOW,PREVIOUS,Store as MaintenanceStore,add_input
    from viewer_publication.archive_maintenance import maintain_releases
    store=MaintenanceStore();add_input(store,LIVE,'live');add_input(store,PREVIOUS,'previous')
    store.objects[SPICY_PINS]=encoded(dict(version=1,generations=[pair('a')]))
    store.times[SPICY_PINS]=NOW
    from viewer_publication.receipt_pins import PREFIX
    inventory=store.inventory
    store.inventory=lambda:[item for item in inventory() if item['Key'].startswith(PREFIX)]
    maintain_releases(store,now=NOW,execute=True)
    assert json.loads(store.objects[SPICY_PINS])['generations']==[pair('a')]


def test_maintenance_refuses_unconditional_pin_fallback_before_deletion():
    from test_archive_maintenance import LIVE,NOW,OLD,PREVIOUS,Store as MaintenanceStore,add_input
    from viewer_publication.archive_maintenance import maintain_releases
    from viewer_publication.receipt_pins import PREFIX
    store=MaintenanceStore();add_input(store,LIVE,'live');add_input(store,PREVIOUS,'previous')
    store.create(PREFIX+OLD+'/manifest.json',b'{}');store.write_spicy_generations=None
    with pytest.raises(TypeError,match='conditional generation-pin'):maintain_releases(store,now=NOW,execute=True)
    assert store.deleted==[] and SPICY_PINS not in store.objects


def test_maintenance_pin_conflict_prevents_every_release_deletion():
    from test_archive_maintenance import LIVE,NOW,OLD,PREVIOUS,Store as MaintenanceStore
    from test_phase2_release_pruning import _add_entity_input
    from viewer_publication.archive_maintenance import maintain_releases
    from viewer_publication.receipt_pins import PREFIX
    store=MaintenanceStore()
    _add_entity_input(store,LIVE,'live',{'members':'a'*64})
    _add_entity_input(store,PREVIOUS,'previous',{'members':'a'*64})
    store.create(PREFIX+OLD+'/manifest.json',b'{}')
    client=PinStore();client.objects=store.objects;add(client,'c')
    inventory=store.inventory
    store.inventory=lambda:[item for item in inventory() if item['Key'].startswith(PREFIX)]
    store.times[SPICY_PINS]=NOW
    store.write_spicy_generations=lambda generations:write_spicy_generations(client,
        bucket='archive-fixture',generations=generations)
    client.before_pin_put=lambda:add(client,'b')
    with pytest.raises(StorageError):maintain_releases(store,now=NOW,execute=True)
    assert store.deleted==[]
    assert json.loads(store.objects[SPICY_PINS])['generations']==[pair('b'),pair('c')]
