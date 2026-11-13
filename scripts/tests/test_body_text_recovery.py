"""Recovery keeps strong copy pins and the declared rendering resolution."""
import importlib.util
from pathlib import Path

import pytest


def command():
    spec = importlib.util.spec_from_file_location('retry_body_text', Path(__file__).parents[1] / 'retry_body_text.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_copy_probe_retries_an_unpinned_response_and_preserves_observations(monkeypatch):
    module = command()
    closed = []
    class Body:
        def close(self): closed.append(True)
    class Client:
        calls = 0
        def __init__(self,*args,**kwargs): pass
        def get_object(self,**kwargs):
            Client.calls += 1
            return dict(Body=Body(),ContentRange='' if Client.calls==1 else 'bytes 0-0/123',
                        ETag='"strong"',ResponseMetadata={'HTTPStatusCode':200 if Client.calls==1 else 206})
    monkeypatch.setattr(module,'PublicOrigin',Client)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    item=dict(body_sha256='a'*64,physical_key='bodies/sha256/aa/'+'a'*64,stored_bytes=None)
    result=module.observed_copy(item,'https://example.invalid')
    assert result['stored_bytes']==123 and result['listed_etag']=='"strong"'
    assert result['captured_stored_bytes'] is None and 'probe_error' not in result
    assert [r['status'] for r in result['copy_observations']]==['unpinned_response','refused','observed']
    assert len(closed)==2 and item['stored_bytes'] is None


def test_copy_probe_never_accepts_a_weak_etag(monkeypatch):
    module=command()
    class Body:
        def close(self): pass
    class Client:
        def __init__(self,*args,**kwargs): pass
        def get_object(self,**kwargs):
            return dict(Body=Body(),ContentRange='bytes 0-0/1',ETag='W/"weak"',ResponseMetadata={'HTTPStatusCode':206})
    monkeypatch.setattr(module,'PublicOrigin',Client)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    result=module.observed_copy(dict(physical_key='body',stored_bytes=1),'https://example.invalid')
    assert 'strong ETag' in result['probe_error']
    assert sum(r['status']=='refused' for r in result['copy_observations'])==3


@pytest.mark.parametrize('identity', [None, {'backend': 'scripted'}])
def test_recovery_lifts_pixel_exclusion_without_changing_resolution(monkeypatch, identity):
    from congress_api.parsers import body_text
    from spicy_docs.extraction import DefaultReader, ExtractionError
    reader=DefaultReader(dpi=200,raw_rgb=True)
    strategy=object()
    monkeypatch.setattr(body_text,'apple_vision',lambda:body_text.PageRule(strategy,reader,identity))
    with pytest.raises(ExtractionError,match='max_pixels'):
        reader.check_pixels(5000,5000)
    rule=body_text.recovery_apple_vision()
    rule.reader.check_pixels(5000,5000)
    assert rule.strategy is strategy and rule.reader.dpi==200 and rule.reader.raw_rgb
    if identity is None:
        assert rule.checkpoint_identity is None  # A missing policy cannot become reusable by lifting a bound.
    else:
        assert rule.checkpoint_identity == dict(identity, max_pixels=(1 << 63) - 1)
