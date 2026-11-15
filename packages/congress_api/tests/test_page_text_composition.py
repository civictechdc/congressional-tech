"""Final page composition preserves real bytes and refuses ambiguous source/page inputs."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from congress_api.lake.page_text_composition import compose_pages
from congress_api.parsers.body_text import Reading, page_offsets
from congress_api.retention.page_checkpoints import pack
from spicy_docs.extraction.model import Observation, PageContent, PageResult, TextBlock


def artifact(path, data):
    if not isinstance(data, bytes):
        data = json.dumps(data, sort_keys=True).encode()
    path.write_bytes(data)
    return dict(path=str(path), bytes=len(data), sha256=sha256(data).hexdigest())


def fixture(tmp_path, *, inherited_ocr=True):
    source = b'actual source'
    pages = ['First café\n', '', 'Last •']
    text = '\n'.join(pages)
    base = dict(body_sha=sha256(source).digest(), parser='pdf_text', parser_version='a'*64,
                text=text, page_offsets=list(page_offsets(pages)), ocr_pages=[1] if inherited_ocr else [],
                macos_build='build-a' if inherited_ocr else None, text_sha256=sha256(text.encode()).digest())
    reading = dict(body_sha=base['body_sha'], parser='pdf_text', parser_version='a'*64,
                   status='completed', error_type=None, text_bytes=len(text.encode()))
    block = TextBlock('Repaired α')
    observed = Observation('full', block.text,
        {'backend': 'apple-vision', 'macos_build': 'build-a'}, None, (block,))
    result = PageResult(dict(page=2, page_count=3, source_sha256=base['body_sha'].hex(),
                             source_size_bytes=len(source), media_type='application/pdf', geometry={'dpi':200}),
                        PageContent((block,), (observed,)))
    replacement = dict(page=2,
        policy=artifact(tmp_path/'policy.json', {'backend':observed.configuration, 'reader':{'dpi':200},
                                              'strategy':'NativeOrOcr', 'require_images':False}),
        intermediate=artifact(tmp_path/'page.json', pack(result)),
        final=artifact(tmp_path/'final.txt', b'Repaired \xce\xb1\n'),
        review=artifact(tmp_path/'review.txt', b'Exact scoped final-page review.'))
    kwargs = dict(source_bytes=len(source), source_page_count=3,
                  source_evidence=artifact(tmp_path/'source.json', {'sha256':base['body_sha'].hex(), 'pages':3}),
                  replacements=[replacement])
    return base, reading, kwargs


def test_composes_final_pages_without_touching_inherited_bytes_or_inputs(tmp_path):
    base, reading, kwargs = fixture(tmp_path)
    original = deepcopy((base, reading, kwargs))
    row, result, receipt = compose_pages(base, reading, **kwargs)
    assert row['text'] == 'First café\n\nRepaired α\n\nLast •'
    assert row['page_offsets'] == list(page_offsets(['First café\n', 'Repaired α\n', 'Last •']))
    assert result.ocr_pages == (1, 2) and result.macos_build == 'build-a'
    assert result.row()['status'] == 'completed' and result.row()['text_bytes'] == len(row['text'].encode())
    assert row['text_sha256'] == sha256(row['text'].encode()).digest()
    assert row['parser_version'] != base['parser_version']
    assert receipt['inherited_pages'] == 2 and receipt['replaced_pages'] == [2]
    assert receipt['selection_performed'] is False and receipt['publication_performed'] is False
    assert 'selected' not in receipt and 'published' not in receipt
    assert receipt['provenance']['base']['page_offsets'] == base['page_offsets']
    assert set(receipt['provenance']['implementation']) == {'composition', 'body_text', 'page_checkpoints'}
    assert 'original' in receipt['provenance']['inherited_interpretation']
    assert (base, reading, kwargs) == original


@pytest.mark.parametrize('damage', ['digest', 'reading-key', 'status', 'reading-size'])
def test_refuses_an_unmatched_completed_base(tmp_path, damage):
    base, reading, kwargs = fixture(tmp_path)
    if damage == 'digest': base['text'] += 'changed'
    elif damage == 'reading-key': reading['parser_version'] = 'b'*64
    elif damage == 'status': reading['status'] = 'error'
    else: reading['text_bytes'] += 1
    with pytest.raises(ValueError):
        compose_pages(base, reading, **kwargs)


@pytest.mark.parametrize('offsets', [[1, 5, 7], [0, 0, 7], [0, 2, 7], [0, 1000, 1001], [0, True, 7], []])
def test_refuses_invalid_utf8_page_maps(tmp_path, offsets):
    base, reading, kwargs = fixture(tmp_path)
    base['page_offsets'] = offsets
    with pytest.raises(ValueError, match='offsets|page count'):
        compose_pages(base, reading, **kwargs)


@pytest.mark.parametrize('field,value', [
    ('source_sha256', '0'*64), ('source_size_bytes', 1), ('page', 1), ('page', True), ('page_count', 4)])
def test_refuses_wrong_intermediate_source_or_page_even_when_its_hash_matches(tmp_path, field, value):
    base, reading, kwargs = fixture(tmp_path)
    reference = kwargs['replacements'][0]['intermediate']
    packed = json.loads((tmp_path/'page.json').read_bytes())
    packed['metadata'][field] = value
    kwargs['replacements'][0]['intermediate'] = artifact(tmp_path/'wrong.json', packed)
    assert reference['sha256'] != kwargs['replacements'][0]['intermediate']['sha256']
    with pytest.raises(ValueError, match='source|page identity'):
        compose_pages(base, reading, **kwargs)


def test_refuses_duplicate_replacements_and_artifact_drift(tmp_path):
    base, reading, kwargs = fixture(tmp_path)
    kwargs['replacements'].append(kwargs['replacements'][0])
    with pytest.raises(ValueError, match='Duplicate'):
        compose_pages(base, reading, **kwargs)
    kwargs['replacements'].pop()
    (tmp_path/'final.txt').write_text('changed')
    with pytest.raises(ValueError, match='artifact'):
        compose_pages(base, reading, **kwargs)


def test_no_prior_ocr_is_distinct_from_a_conflicting_prior_build(tmp_path):
    base, reading, kwargs = fixture(tmp_path, inherited_ocr=False)
    row, result, _ = compose_pages(base, reading, **kwargs)
    assert result.ocr_pages == (2,) and row['macos_build'] == 'build-a'
    base['ocr_pages'], base['macos_build'] = [1], 'build-b'
    with pytest.raises(ValueError, match='different macOS builds'):
        compose_pages(base, reading, **kwargs)
    base['macos_build'] = None
    with pytest.raises(ValueError, match='unavailable'):
        compose_pages(base, reading, **kwargs)


def test_replacement_backend_is_not_inferred_from_a_macos_label(tmp_path):
    base, reading, kwargs = fixture(tmp_path)
    packed = json.loads((tmp_path/'page.json').read_bytes())
    packed['observations'][0]['configuration']['backend'] = 'other-engine'
    kwargs['replacements'][0]['intermediate'] = artifact(tmp_path/'other.json', packed)
    with pytest.raises(ValueError, match='Apple Vision'):
        compose_pages(base, reading, **kwargs)


def test_policy_bytes_change_identity_but_relocation_does_not(tmp_path):
    base, reading, kwargs = fixture(tmp_path)
    first, _, _ = compose_pages(base, reading, **kwargs)
    replacement = kwargs['replacements'][0]
    replacement['final'] = artifact(tmp_path/'moved.txt', (tmp_path/'final.txt').read_bytes())
    relocated, _, _ = compose_pages(base, reading, **kwargs)
    assert first['parser_version'] == relocated['parser_version']
    policy = json.loads((tmp_path/'policy.json').read_text())
    policy['require_images'] = True
    replacement['policy'] = artifact(tmp_path/'new-policy.json', policy)
    changed, _, _ = compose_pages(base, reading, **kwargs)
    assert changed['text'] == first['text'] and changed['parser_version'] != first['parser_version']


def test_empty_final_page_and_unaffected_blank_pages_are_preserved(tmp_path):
    base, reading, kwargs = fixture(tmp_path, inherited_ocr=False)
    kwargs['replacements'][0]['final'] = artifact(tmp_path/'blank.txt', b'')
    row, _, receipt = compose_pages(base, reading, **kwargs)
    assert row['text'] == base['text'] and row['page_offsets'] == base['page_offsets']
    assert receipt['replaced_pages'] == [2]  # Empty reviewed output still has its own actual provenance.


@pytest.mark.parametrize('damage', ['label-only', 'backend', 'reader'])
def test_policy_names_cannot_replace_actual_settings(tmp_path, damage):
    base, reading, kwargs = fixture(tmp_path)
    policy = json.loads((tmp_path/'policy.json').read_text())
    if damage == 'label-only': policy = {'label':'reviewed'}
    elif damage == 'backend': policy['backend']['macos_build'] = 'invented'
    else: policy['reader']['dpi'] = 300
    kwargs['replacements'][0]['policy'] = artifact(tmp_path/'wrong-policy.json', policy)
    with pytest.raises(ValueError, match='settings'):
        compose_pages(base, reading, **kwargs)


def groq_packet(base, *, finish='stop', model='qwen/test', outcome=None, image_in_request=None):
    """A genuine PNG and actual-shaped retained request/response, without a provider call."""
    import base64
    from io import BytesIO
    from PIL import Image
    image = BytesIO()
    Image.new('RGB', (2, 3), 'white').save(image, format='PNG')
    encoded = lambda v: json.dumps(v, sort_keys=True).encode()
    pin = lambda b: dict(bytes=len(b), sha256=sha256(b).hexdigest())
    prompt = b'Preserve printed words only.'
    properties = dict(continuity={'type':'string'}, markdown={'type':'string'},
        tables={'type':'array','items':{'type':'object','properties':{
            'id':{'type':'string'},'columns':{'type':'array','items':{'type':'string'}},
            'rows':{'type':'array','items':{'type':'string'}}},
            'required':['id','columns','rows'],'additionalProperties':False}},
        doc_type={'type':'string'}, date={'type':['string','null']},
        identifiers={'type':'array','items':{'type':'string'}})
    schema = dict(name='congressional_page_minimal',strict=True,
        schema=dict(type='object',properties=properties,required=list(properties),additionalProperties=False))
    request = dict(model='qwen/test',temperature=0,max_completion_tokens=4096,
        messages=[dict(role='system',content=prompt.decode()),dict(role='user',content=[
            dict(type='text',text='<document>\n'), dict(type='image_url',image_url=dict(
                url='data:image/png;base64,'+base64.b64encode(image.getvalue() if image_in_request is None else image_in_request).decode())),
            dict(type='text',text='\n</document>')])],
        response_format=dict(type='json_schema',json_schema=schema))
    outcome = outcome or dict(continuity='complete',markdown='Actual source words α',tables=[],
        doc_type='other',date='1990',identifiers=['metadata only'])
    response = dict(id='response-actual',model=model,service_tier='on_demand',x_groq={'id':'http-actual'},choices=[
        dict(finish_reason=finish,message=dict(role='assistant',content=json.dumps(outcome)))])
    identity = dict(endpoint='https://api.groq.com/openai/v1/chat/completions',model='qwen/test',
        source=dict(sha256=base['body_sha'].hex(),bytes=len(b'actual source')),
        physical_file_page=2,page_count=3,dpi_from_retained_render=200,dimensions=[2,3],mode='RGB',
        input_image=pin(image.getvalue()),request=pin(encoded(request)),schema=pin(encoded(schema)),
        system_prompt=pin(prompt))
    receipt = dict(status=200,error=None,response=pin(encoded(response)),headers={'x-request-id':'http-actual'})
    return dict(identity=encoded(identity),request=encoded(request),response=encoded(response),
        schema=encoded(schema),prompt=prompt,receipt=encoded(receipt),image=image.getvalue())


def structured_fixture(tmp_path, *, inherited_ocr=True):
    from congress_api.lake.structured_page import retained_groq_page
    base, reading, kwargs = fixture(tmp_path, inherited_ocr=inherited_ocr)
    packet = groq_packet(base)
    result, settings = retained_groq_page(packet)
    refs = {name:artifact(tmp_path/(name+'.retained'),data) for name,data in packet.items()}
    kwargs['replacements'][0].update(
        policy=artifact(tmp_path/'structured-policy.json',dict(backend=settings,reader={'dpi':200},
            structured_provider_artifacts=refs)),
        intermediate=artifact(tmp_path/'structured-page.json',pack(result)),
        final=artifact(tmp_path/'structured-final.txt',result.text.encode()))
    return base, reading, kwargs


@pytest.mark.parametrize('inherited_ocr', [True, False])
def test_structured_page_keeps_actual_provider_and_truthful_mixed_build(tmp_path, inherited_ocr):
    base, reading, kwargs = structured_fixture(tmp_path, inherited_ocr=inherited_ocr)
    row, result, receipt = compose_pages(base, reading, **kwargs)
    assert row['text'] == 'First café\n\nActual source words α\nLast •'
    assert result.ocr_pages == ((1,2) if inherited_ocr else (2,))
    assert row['macos_build'] == ('build-a' if inherited_ocr else None)
    assert receipt['provenance']['remote_recognition_pages'] == [2]
    remote = receipt['provenance']['replacements'][0]
    assert remote['recognition_provider'] == 'groq' and remote['macos_build'] is None
    assert remote['policy_settings']['backend']['model'] == 'qwen/test'
    assert set(remote['structured_provider_artifacts']) == {'identity','request','response','schema','prompt','receipt','image'}
    assert '1990' not in row['text'] and 'metadata only' not in row['text']
    assert receipt['selection_performed'] is False


def test_remote_only_base_can_be_selectively_composed_again_without_fake_macos(tmp_path):
    base, reading, kwargs = structured_fixture(tmp_path, inherited_ocr=False)
    first, made, _ = compose_pages(base, reading, **kwargs)
    actual_reading = dict(body_sha=first['body_sha'],parser='pdf_text',parser_version=first['parser_version'],**made.row())
    second, result, _ = compose_pages(first, actual_reading, **kwargs)
    assert second['text'] == first['text'] and result.ocr_pages == (2,) and result.macos_build is None
    damaged = deepcopy(actual_reading)
    next(f for f in damaged['fields'] if f['field']=='page_composition_sha256')['value']='0'*64
    with pytest.raises(ValueError, match='version-bound'):
        compose_pages(first, damaged, **kwargs)


def test_prior_remote_page_survives_a_later_vision_page_repair(tmp_path):
    base, reading, kwargs = structured_fixture(tmp_path, inherited_ocr=False)
    first, made, _ = compose_pages(base, reading, **kwargs)
    actual_reading=dict(body_sha=first['body_sha'],parser='pdf_text',parser_version=first['parser_version'],**made.row())
    _, _, vision = fixture(tmp_path)
    payload=json.loads((tmp_path/'page.json').read_bytes())
    payload['metadata']['page']=3
    vision['replacements'][0]['page']=3
    vision['replacements'][0]['intermediate']=artifact(tmp_path/'vision-p3.json',payload)
    second, result, receipt=compose_pages(first,actual_reading,**vision)
    assert result.ocr_pages==(2,3) and result.macos_build=='build-a'
    assert 'Actual source words α' in second['text']
    assert receipt['provenance']['remote_recognition_pages']==[2]
    assert receipt['provenance']['macos_build_scope'].startswith('Vision contribution only')


@pytest.mark.parametrize('damage', ['final-omission','page-text','fake-vision','wrong-source'])
def test_structured_composition_refuses_rebound_but_inconsistent_output(tmp_path, damage):
    base, reading, kwargs = structured_fixture(tmp_path)
    replacement = kwargs['replacements'][0]
    if damage == 'final-omission':
        replacement['final'] = artifact(tmp_path/'omitted.txt',b'Actual words')
    else:
        value = json.loads((tmp_path/'structured-page.json').read_bytes())
        if damage == 'page-text': value['blocks'][0]['text']='Plausible invented words'
        elif damage == 'fake-vision': value['observations'][0]['configuration']['macos_build']='invented'
        else: value['metadata']['source_sha256']='0'*64
        replacement['intermediate']=artifact(tmp_path/'changed-page.json',value)
    with pytest.raises(ValueError, match='differs|identity'):
        compose_pages(base, reading, **kwargs)


@pytest.mark.parametrize('change,match', [
    ({'finish':'length'},'incomplete'),({'model':'different'},'model mismatch'),
    ({'image_in_request':b'not the retained image'},'exact retained image')])
def test_retained_provider_refuses_failure_or_wrong_image(tmp_path, change, match):
    from congress_api.lake.structured_page import retained_groq_page
    base, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match=match):
        retained_groq_page(groq_packet(base,**change))


def test_retained_provider_binds_http_and_response_request_ids(tmp_path):
    from congress_api.lake.structured_page import retained_groq_page
    base, _, _ = fixture(tmp_path)
    packet=groq_packet(base)
    receipt=json.loads(packet['receipt'])
    receipt['headers']['x-request-id']='unrelated-response'
    packet['receipt']=json.dumps(receipt).encode()
    with pytest.raises(ValueError,match='request identities'):
        retained_groq_page(packet)


def test_structured_table_blanks_are_preserved_and_orphans_refused(tmp_path):
    from congress_api.lake.structured_page import retained_groq_page
    base, _, _ = fixture(tmp_path)
    outcome=dict(continuity='complete',markdown='Printed words\n{{table:t1}}',tables=[
        dict(id='t1',columns=['Name','Yes','No'],rows=['Person |  | X'])],
        doc_type='form_or_disclosure',date=None,identifiers=[])
    result,_=retained_groq_page(groq_packet(base,outcome=outcome))
    assert '| Person |  | X |' in result.text
    outcome['markdown']='Printed words'
    with pytest.raises(ValueError,match='placeholders'):
        retained_groq_page(groq_packet(base,outcome=outcome))

