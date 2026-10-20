"""Slice 4 exit gate: fixture people, reversible decisions, code-point spans."""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

import pytest

from news_lake.context import AdapterContext, adapter_namespace, build_run
from news_lake.contract import ContractError, check_corpus, validate_shape
from news_lake.identity import PEOPLE, PEOPLE_BY_ID, apply_decisions, link_mentions
from news_lake.identity.linking import resolution_for

AT = '2026-10-20T04:00:00Z'
FROZEN = AdapterContext(clock=lambda: datetime(2026, 10, 20, 4, 0, 0, tzinfo=timezone.utc))
RUN_NAMESPACE = adapter_namespace('test:runs')
_id = lambda key: str(uuid5(NAMESPACE_URL, 'news-lake-identity-test:' + key))


def pid(key):
    """Stable id of a fixture person (recomputed the same way people.py does)."""
    return str(uuid5(adapter_namespace('identity:people'), f'person:{key}'))


def decision(key, action, *, left=None, right=None, prior=None, at=AT, decided_by='fixture:reviewer'):
    record = {
        'kind': 'identity_decision',
        'id': _id(key),
        'recorded_at': at,
        'action': action,
        'decided_by': decided_by,
        'reason': f'fixture decision {key}',
    }
    if left is not None:
        record['left_id'] = left
    if right is not None:
        record['right_id'] = right
    if prior is not None:
        record['prior_decision_id'] = prior
    return record


# -- fixture people -------------------------------------------------------------


def test_people_are_contract_valid_and_cover_the_identity_hazards():
    assert len(PEOPLE) == 5
    for person in PEOPLE:
        validate_shape(person)
    assert pid('alex-doe-city') != pid('alex-doe-county')
    assert PEOPLE_BY_ID[pid('alex-doe-city')]['name'] == 'Alex Doe'
    assert PEOPLE_BY_ID[pid('alex-doe-county')]['name'] == 'Alex Doe'  # same-name pair
    schemes = {i['scheme'] for i in PEOPLE_BY_ID[pid('taylor-tran')]['identifiers']}
    assert schemes == {'example_gov_id'}  # crosswalk scheme
    all_schemes = {i['scheme'] for person in PEOPLE for i in person['identifiers']}
    assert all_schemes >= {'example_gov_id', 'wikidata_qid', 'example_press_registry'}
    # Renamed person keeps the old name as an alias.
    assert [a['value'] for a in PEOPLE_BY_ID[pid('robin-roe')]['aliases']] == ['Robin Oldname']
    # Tenures: one open-ended (unknown end), one closed; inclusive from, exclusive to.
    city = PEOPLE_BY_ID[pid('alex-doe-city')]['tenures'][0]
    assert 'to' not in city
    county = PEOPLE_BY_ID[pid('alex-doe-county')]['tenures'][0]
    assert county['from'] < county['to']
    check_corpus(PEOPLE)


# -- decision graph ---------------------------------------------------------------


def test_no_decisions_leaves_every_entity_its_own_root():
    result = apply_decisions(PEOPLE)
    assert result['roots'] == {person['id']: person['id'] for person in PEOPLE}
    assert result['applied'] == [] and result['retracted'] == []


def test_same_as_maps_left_to_right_directionally():
    # robin/jose/taylor pairwise share no identifier schemes, so they merge.
    a, b, c = pid('robin-roe'), pid('taylor-tran'), pid('jose-rios')
    records = PEOPLE + [
        decision('d1', 'same_as', left=a, right=b, at='2026-10-20T05:00:00Z'),
        decision('d2', 'same_as', left=b, right=c, at='2026-10-20T06:00:00Z'),
    ]
    result = apply_decisions(records)
    assert result['roots'][a] == c and result['roots'][b] == c and result['roots'][c] == c
    assert result['groups'][c] == sorted([a, b, c])


def test_cycle_is_rejected():
    a, b = pid('robin-roe'), pid('taylor-tran')
    records = PEOPLE + [
        decision('d1', 'same_as', left=a, right=b, at='2026-10-20T05:00:00Z'),
        decision('d2', 'same_as', left=b, right=a, at='2026-10-20T06:00:00Z'),
    ]
    with pytest.raises(ContractError) as raised:
        apply_decisions(records)
    assert raised.value.rule == 'decision_cycle'


def test_cycle_reached_through_a_shortcut_is_rejected():
    # d1 and d2 make A, B, C one class and shortcut A->B; d3's B->A is still a
    # real cycle even though A and B already resolve to the same root.
    a, b, c = pid('robin-roe'), pid('taylor-tran'), pid('jose-rios')
    records = PEOPLE + [
        decision('d1', 'same_as', left=b, right=c, at='2026-10-20T05:00:00Z'),
        decision('d2', 'same_as', left=a, right=b, at='2026-10-20T06:00:00Z'),
        decision('d3', 'same_as', left=b, right=a, at='2026-10-20T07:00:00Z'),
    ]
    with pytest.raises(ContractError) as raised:
        apply_decisions(records)
    assert raised.value.rule == 'decision_cycle'


def test_valid_dag_with_a_shared_left_endpoint_is_accepted():
    # {A->B, A->C, C->B} is acyclic. The third arrow is not a confirmation of
    # the union-find root alone; it also resolves the class to sink B.
    a, b, c = pid('robin-roe'), pid('taylor-tran'), pid('jose-rios')
    records = PEOPLE + [
        decision('d1', 'same_as', left=a, right=b, at='2026-10-20T05:00:00Z'),
        decision('d2', 'same_as', left=a, right=c, at='2026-10-20T06:00:00Z'),
        decision('d3', 'same_as', left=c, right=b, at='2026-10-20T07:00:00Z'),
    ]
    result = apply_decisions(records)
    assert result['applied'] == [_id('d1'), _id('d2'), _id('d3')]
    assert result['roots'][a] == b and result['roots'][b] == b and result['roots'][c] == b
    assert result['groups'][b] == sorted([a, b, c])


@pytest.mark.parametrize('action', ['same_as', 'different_from'])
def test_reflexive_decisions_passed_directly_are_rejected(action):
    a = pid('robin-roe')
    with pytest.raises(ContractError) as raised:
        apply_decisions(PEOPLE + [decision('d1', action, left=a, right=a)])
    assert raised.value.rule == 'reflexive_identity_decision'


def test_redundant_confirmation_between_equivalent_entities_is_benign():
    a, b, c = pid('robin-roe'), pid('taylor-tran'), pid('jose-rios')
    records = PEOPLE + [
        decision('d1', 'same_as', left=a, right=b, at='2026-10-20T05:00:00Z'),
        decision('d2', 'same_as', left=b, right=c, at='2026-10-20T06:00:00Z'),
        decision('d3', 'same_as', left=a, right=c, at='2026-10-20T07:00:00Z'),  # confirmation
    ]
    result = apply_decisions(records)
    assert len(result['applied']) == 3
    assert result['roots'][a] == c


def test_same_as_across_different_from_is_rejected():
    a, b = pid('robin-roe'), pid('taylor-tran')
    records = PEOPLE + [
        decision('d1', 'different_from', left=a, right=b, at='2026-10-20T05:00:00Z'),
        decision('d2', 'same_as', left=a, right=b, at='2026-10-20T06:00:00Z'),
    ]
    with pytest.raises(ContractError) as raised:
        apply_decisions(records)
    assert raised.value.rule == 'contradictory_decision'


def test_different_from_across_equivalence_is_rejected():
    a, b = pid('robin-roe'), pid('taylor-tran')
    records = PEOPLE + [
        decision('d1', 'same_as', left=a, right=b, at='2026-10-20T05:00:00Z'),
        decision('d2', 'different_from', left=a, right=b, at='2026-10-20T06:00:00Z'),
    ]
    with pytest.raises(ContractError) as raised:
        apply_decisions(records)
    assert raised.value.rule == 'contradictory_decision'


def test_transitive_group_merge_across_different_from_is_rejected():
    a, b, c = pid('robin-roe'), pid('taylor-tran'), pid('jose-rios')
    records = PEOPLE + [
        decision('d1', 'same_as', left=a, right=b, at='2026-10-20T05:00:00Z'),
        decision('d2', 'different_from', left=b, right=c, at='2026-10-20T06:00:00Z'),
        decision('d3', 'same_as', left=a, right=c, at='2026-10-20T07:00:00Z'),  # a~b, b!~c
    ]
    with pytest.raises(ContractError) as raised:
        apply_decisions(records)
    assert raised.value.rule == 'contradictory_decision'


def test_authoritative_identifier_conflict_fails_the_merge():
    a, b = pid('alex-doe-city'), pid('alex-doe-county')  # wikidata Q1000001 vs Q1000002
    records = PEOPLE + [decision('d1', 'same_as', left=a, right=b)]
    with pytest.raises(ContractError) as raised:
        apply_decisions(records)
    assert raised.value.rule == 'authoritative_id_conflict'


def test_identical_identifiers_corroborate_instead_of_conflicting():
    a, b = pid('robin-roe'), pid('taylor-tran')
    corroborated = dict(PEOPLE_BY_ID[b])
    corroborated['identifiers'] = list(corroborated['identifiers']) + [
        {'scheme': 'wikidata_qid', 'value': 'Q1000003'}]  # robin's exact identifier
    records = [PEOPLE_BY_ID[k] if k != b else corroborated for k in PEOPLE_BY_ID]
    records += [decision('d1', 'same_as', left=a, right=b)]
    result = apply_decisions(records)
    assert result['roots'][a] == b


def test_retraction_rules():
    a, b = pid('robin-roe'), pid('taylor-tran')
    with pytest.raises(ContractError, match='retraction_target_missing'):
        apply_decisions(PEOPLE + [decision('r', 'retract', prior=_id('nonexistent'))])
    with pytest.raises(ContractError) as raised:
        apply_decisions(PEOPLE + [
            decision('d1', 'same_as', left=a, right=b, at='2026-10-20T05:00:00Z'),
            decision('r1', 'retract', prior=_id('d1'), at='2026-10-20T06:00:00Z'),
            decision('r2', 'retract', prior=_id('r1'), at='2026-10-20T07:00:00Z'),
        ])
    assert raised.value.rule == 'retraction_target_retraction'
    with pytest.raises(ContractError) as raised:  # target recorded later
        apply_decisions(PEOPLE + [
            decision('r1', 'retract', prior=_id('d1'), at='2026-10-20T05:00:00Z'),
            decision('d1', 'same_as', left=a, right=b, at='2026-10-20T06:00:00Z'),
        ])
    assert raised.value.rule == 'retraction_target_not_earlier'
    with pytest.raises(ContractError) as raised:  # double retraction
        apply_decisions(PEOPLE + [
            decision('d1', 'same_as', left=a, right=b, at='2026-10-20T05:00:00Z'),
            decision('r1', 'retract', prior=_id('d1'), at='2026-10-20T06:00:00Z'),
            decision('r2', 'retract', prior=_id('d1'), at='2026-10-20T07:00:00Z'),
        ])
    assert raised.value.rule == 'retraction_target_already_retracted'


def test_merge_then_retract_reverses_and_only_unapplies_its_target():
    a, b, c = pid('robin-roe'), pid('taylor-tran'), pid('jose-rios')
    merged = apply_decisions(PEOPLE + [decision('d1', 'same_as', left=a, right=b)])
    assert merged['roots'][a] == b
    unmerged = apply_decisions(PEOPLE + [
        decision('d1', 'same_as', left=a, right=b, at='2026-10-20T05:00:00Z'),
        decision('r1', 'retract', prior=_id('d1'), at='2026-10-20T06:00:00Z'),
    ])
    assert unmerged['roots'][a] == a and unmerged['roots'][b] == b
    assert unmerged['retracted'] == [_id('d1')]
    # Retracting the first of two merges keeps the second intact.
    chain = apply_decisions(PEOPLE + [
        decision('d1', 'same_as', left=a, right=b, at='2026-10-20T05:00:00Z'),
        decision('d2', 'same_as', left=b, right=c, at='2026-10-20T06:00:00Z'),
        decision('r1', 'retract', prior=_id('d1'), at='2026-10-20T07:00:00Z'),
    ])
    assert chain['roots'][a] == a
    assert chain['roots'][b] == c and chain['roots'][c] == c


# -- linking ---------------------------------------------------------------------


def make_version(key, title, text=None):
    record = {
        'kind': 'version',
        'id': _id('version:' + key),
        'recorded_at': AT,
        'item_id': _id('item:' + key),
        'capture_id': _id('capture:' + key),
        'run_id': _id('run-extract:' + key),
        'title': title,
        'publication': {'precision': 'unknown'},
        'access': 'metadata_only',
    }
    if text is not None:
        record['access'] = 'restricted'
        record['rights_basis'] = 'Synthetic fixture.'
        record['text'] = text
        record['text_hash'] = sha256(text.encode('utf-8')).hexdigest()
    return record


def make_entity(key, name, aliases=()):
    return {
        'kind': 'entity',
        'id': _id('entity:' + key),
        'recorded_at': AT,
        'entity_type': 'person',
        'name': name,
        'aliases': [{'value': alias, 'language': 'en'} for alias in aliases],
        'identifiers': [],
    }


def make_corpus(versions):
    """Minimal valid shell (items, captures, runs) around hand-built versions."""
    shells = []
    for version in versions:
        capture = {
            'kind': 'capture', 'id': version['capture_id'], 'recorded_at': AT, 'provider': 'rss',
            'request_url': f"https://example.com/{version['item_id']}", 'observed_at': AT,
            'access': 'restricted' if 'text' in version else 'metadata_only', 'status': 'succeeded',
        }
        if 'text' in version:
            capture.update({
                'payload_uri': f"https://example.com/{version['item_id']}/payload.html",
                'payload_hash': sha256(version['text'].encode('utf-8')).hexdigest(),
                'media_type': 'text/html',
                'rights_basis': 'Synthetic fixture.',
            })
        shells.extend([
            capture,
            {'kind': 'item', 'id': version['item_id'], 'recorded_at': AT,
             'canonical_url': f"https://example.com/{version['id']}", 'url_aliases': [],
             'content_type': 'news_article', 'first_seen_at': AT},
            build_run(RUN_NAMESPACE, FROZEN, processor='extract', processor_version='fixture-1',
                      config={'fixture': True}, inputs=[{'kind': 'capture', 'id': version['capture_id']}]),
        ])
        shells[-1]['id'] = version['run_id']
    return shells


def linking_run(versions):
    run = build_run(
        RUN_NAMESPACE,
        FROZEN,
        processor='mentions', processor_version='exact-1', config={'matcher': 'exact-casefold'},
        inputs=[{'kind': 'version', 'id': v['id']} for v in versions], mode='live',
    )
    run['id'] = _id('run-mentions')
    return run


def test_resolved_mentions_carry_entity_ids_and_span_title_and_text():
    version = make_version('v1', 'Robin Roe speaks', 'Robin Roe addressed the council.')
    run = linking_run([version])
    mentions = link_mentions([version], PEOPLE, apply_decisions(PEOPLE), run)
    surface = next(m for m in mentions if m['surface'] == 'Robin Roe')
    assert surface['resolution'] == 'resolved'
    assert surface['entity_id'] == pid('robin-roe')
    assert {(s['field'], s['start'], s['end']) for s in surface['occurrences']} == {
        ('title', 0, 9), ('text', 0, 9)}
    check_corpus(make_corpus([version]) + [version, run, *PEOPLE] + mentions)


def test_old_alias_of_a_renamed_person_still_links():
    version = make_version('v2', 'Oldname returns', 'Robin Oldname held a press conference.')
    run = linking_run([version])
    mentions = link_mentions([version], PEOPLE, apply_decisions(PEOPLE), run)
    alias = next(m for m in mentions if m['surface'] == 'Robin Oldname')
    assert alias['resolution'] == 'resolved'
    assert alias['entity_id'] == pid('robin-roe')


def test_offsets_are_code_points_not_utf16_units():
    # '🎤' is one code point but two UTF-16 units; an emoji before the surface
    # shifts a UTF-16 index by one extra. Code-point offsets must not shift.
    text = '🎤 José Ríos spoke.'
    version = make_version('v3', '🎤 José Ríos spoke.', text)
    run = linking_run([version])
    mentions = link_mentions([version], PEOPLE, apply_decisions(PEOPLE), run)
    surface = next(m for m in mentions if m['surface'] == 'José Ríos')
    title_span = next(s for s in surface['occurrences'] if s['field'] == 'title')
    assert title_span['start'] == 2 and title_span['end'] == 11  # 9 code points after '🎤 '
    check_corpus(make_corpus([version]) + [version, run, *PEOPLE] + mentions)


def test_casefold_expanding_surface_matches_all_spellings_with_exact_spans():
    # 'ß'.casefold() == 'ss' changes the code-point length; the span must be
    # measured on the original haystack, not on the folded form.
    entity = make_entity('max-weiss', 'Max Weiß')
    version = make_version(
        'v9',
        'Max Weiß and MAX WEISS',
        'Max Weiss spoke; MAX WEISS agreed.',
    )
    run = linking_run([version])
    mentions = link_mentions([version], [entity], apply_decisions([entity]), run)
    by_surface = {mention['surface']: mention for mention in mentions}
    assert set(by_surface) == {'Max Weiß', 'MAX WEISS', 'Max Weiss'}
    assert by_surface['Max Weiß']['occurrences'] == [
        {'field': 'title', 'start': 0, 'end': 8}]
    assert by_surface['MAX WEISS']['occurrences'] == [
        {'field': 'text', 'start': 17, 'end': 26},
        {'field': 'title', 'start': 13, 'end': 22},
    ]
    assert by_surface['Max Weiss']['occurrences'] == [
        {'field': 'text', 'start': 0, 'end': 9}]
    check_corpus(make_corpus([version]) + [version, run, entity] + mentions)


def test_partial_word_surfaces_do_not_match():
    roe = make_entity('robin-roe-boundary', 'Robin Roe')
    doe = make_entity('alex-doe-boundary', 'Alex Doe', aliases=['A. Doe'])
    version = make_version(
        'v10',
        'Robin Roebuck and M.A. Doering',
        'Robin Roebuck met M.A. Doering.',
    )
    run = linking_run([version])
    mentions = link_mentions([version], [roe, doe], apply_decisions([roe, doe]), run)
    assert mentions == []


def test_initials_and_non_ascii_surfaces_match_at_word_boundaries():
    version = make_version(
        'v11',
        'A. Doe speaks',
        'A. Doe and José Ríos spoke.',
    )
    run = linking_run([version])
    mentions = link_mentions([version], PEOPLE, apply_decisions(PEOPLE), run)
    doe = next(m for m in mentions if m['surface'] == 'A. Doe')
    assert doe['resolution'] == 'resolved'
    assert doe['entity_id'] == pid('alex-doe-city')
    assert {(s['field'], s['start'], s['end']) for s in doe['occurrences']} == {
        ('title', 0, 6), ('text', 0, 6)}
    rios = next(m for m in mentions if m['surface'] == 'José Ríos')
    assert rios['resolution'] == 'resolved'
    assert rios['entity_id'] == pid('jose-rios')
    assert {(s['field'], s['start'], s['end']) for s in rios['occurrences']} == {
        ('text', 11, 20)}
    check_corpus(make_corpus([version]) + [version, run, *PEOPLE] + mentions)


def test_ambiguous_same_name_pair_yields_no_entity_id():
    version = make_version('v4', 'Alex Doe votes', 'Alex Doe voted.')
    run = linking_run([version])
    mentions = link_mentions([version], PEOPLE, apply_decisions(PEOPLE), run)
    surface = next(m for m in mentions if m['surface'] == 'Alex Doe')
    assert surface['resolution'] == 'ambiguous'
    assert 'entity_id' not in surface
    # An explicit different_from keeps them distinct as well.
    distinct = apply_decisions(PEOPLE + [decision(
        'd1', 'different_from', left=pid('alex-doe-city'), right=pid('alex-doe-county'))])
    surface = next(m for m in link_mentions([version], PEOPLE, distinct, run) if m['surface'] == 'Alex Doe')
    assert surface['resolution'] == 'ambiguous'


def test_merge_then_retract_changes_mention_resolution():
    # Two same-name fixture entities that do NOT collide on identifiers:
    # build a county twin without the colliding wikidata id.
    twin = {
        'kind': 'entity', 'id': _id('alex-doe-twin'), 'recorded_at': AT, 'entity_type': 'person',
        'name': 'Alex Doe', 'aliases': [], 'identifiers': [],
    }
    entities = [PEOPLE_BY_ID[pid('alex-doe-city')], twin]
    version = make_version('v5', 'Alex Doe votes', 'Alex Doe voted.')
    run = linking_run([version])
    merged = apply_decisions(entities + [decision('d1', 'same_as',
                                                  left=pid('alex-doe-city'), right=twin['id'])])
    mentions = link_mentions([version], entities, merged, run)
    surface = next(m for m in mentions if m['surface'] == 'Alex Doe')
    assert surface['resolution'] == 'resolved'
    assert surface['entity_id'] == twin['id']  # left maps to right (directional)
    retracted = apply_decisions(entities + [
        decision('d1', 'same_as', left=pid('alex-doe-city'), right=twin['id'], at='2026-10-20T05:00:00Z'),
        decision('r1', 'retract', prior=_id('d1'), at='2026-10-20T06:00:00Z'),
    ])
    mentions = link_mentions([version], entities, retracted, run)
    surface = next(m for m in mentions if m['surface'] == 'Alex Doe')
    assert surface['resolution'] == 'ambiguous'
    assert 'entity_id' not in surface


def test_unresolved_branch_of_resolution_for():
    assert resolution_for([], {}) == ('unresolved', None)


def test_stale_surface_in_a_changed_version_produces_no_out_of_bounds_spans():
    old = make_version('v6', 'Taylor Tran resigns', 'Taylor Tran resigned today.')
    changed = make_version('v7', 'Committee meets', 'The committee met without members present.')
    run = linking_run([changed])
    mentions = link_mentions([changed], PEOPLE, apply_decisions(PEOPLE), run)
    assert mentions == []  # no candidate surface present; nothing emitted
    check_corpus(make_corpus([changed]) + [changed, run])
    # And the earlier version still links cleanly under its own run.
    run_old = linking_run([old])
    mentions_old = link_mentions([old], PEOPLE, apply_decisions(PEOPLE), run_old)
    assert any(m['surface'] == 'Taylor Tran' for m in mentions_old)
    check_corpus(make_corpus([old]) + [old, run_old, *PEOPLE] + mentions_old)


def test_aboutness_defaults_to_unknown_without_invented_confidence():
    version = make_version('v8', 'Taylor Tran speaks', 'Taylor Tran spoke.')
    run = linking_run([version])
    mentions = link_mentions([version], PEOPLE, apply_decisions(PEOPLE), run)
    for mention in mentions:
        assert mention['aboutness'] == 'unknown'
        assert 'identity_confidence' not in mention
        assert 'aboutness_confidence' not in mention
