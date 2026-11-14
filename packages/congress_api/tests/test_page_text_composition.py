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

