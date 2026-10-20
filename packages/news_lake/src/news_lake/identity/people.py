"""Five authoritative person entities (illustrative fixtures, docs style).

Same fixture discipline as docs/examples/records.jsonl: synthetic people,
deterministic uuid5 ids under a documented namespace, one fixed recorded_at.
Includes the two identity hazards the packet calls out: a same-name pair of
two different people, and a person who renamed (the old name survives as an
alias). Tenures use inclusive from / exclusive to; a missing endpoint means
unknown, not verified current service (C3/C6).
"""
from news_lake.context import adapter_namespace, named_id

NAMESPACE = adapter_namespace('identity:people')
RECORDED_AT = '2026-10-20T04:00:00Z'


def _person_id(key):
    return named_id(NAMESPACE, f'person:{key}')


def _entity(key, *, name, aliases=(), identifiers=(), tenures=(), affiliations=()):
    record = {
        'kind': 'entity',
        'id': _person_id(key),
        'recorded_at': RECORDED_AT,
        'entity_type': 'person',
        'name': name,
        'aliases': list(aliases),
        'identifiers': list(identifiers),
    }
    if tenures:
        record['tenures'] = list(tenures)
    if affiliations:
        record['affiliations'] = list(affiliations)
    return record


ALEX_DOE_CITY = _entity(
    'alex-doe-city',
    name='Alex Doe',
    aliases=[{'value': 'A. Doe', 'language': 'en'}],
    identifiers=[
        {'scheme': 'example_gov_id', 'value': 'C-101'},
        {'scheme': 'wikidata_qid', 'value': 'Q1000001'},
    ],
    tenures=[{'office': 'Council member', 'jurisdiction': 'Example City', 'from': '2024-01-01'}],
)

ALEX_DOE_COUNTY = _entity(  # same name, different person (the same-name pair)
    'alex-doe-county',
    name='Alex Doe',
    identifiers=[
        {'scheme': 'example_gov_id', 'value': 'C-202'},
        {'scheme': 'wikidata_qid', 'value': 'Q1000002'},
    ],
    tenures=[{'office': 'County supervisor', 'jurisdiction': 'Example County',
              'from': '2022-01-01', 'to': '2026-01-01'}],
)

ROBIN_ROE = _entity(  # renamed person: the old name remains an alias
    'robin-roe',
    name='Robin Roe',
    aliases=[{'value': 'Robin Oldname', 'language': 'en'}],
    identifiers=[{'scheme': 'wikidata_qid', 'value': 'Q1000003'}],
    tenures=[{'office': 'Mayor', 'jurisdiction': 'Example City',
              'from': '2021-01-01', 'to': '2025-01-01'}],
)

JOSE_RIOS = _entity(  # non-ASCII surfaces (code-point offset tests)
    'jose-rios',
    name='José Ríos',
    aliases=[{'value': 'J. Ríos', 'language': 'es'}],
    identifiers=[{'scheme': 'example_press_registry', 'value': 'PR-2044'}],
    tenures=[{'office': 'Deputy', 'jurisdiction': 'Example Region',
              'from': '2023-01-01', 'to': '2024-01-01'}],
    affiliations=[{'organization': 'Example Party', 'from': '2019-01-01'}],
)

TAYLOR_TRAN = _entity(
    'taylor-tran',
    name='Taylor Tran',
    identifiers=[{'scheme': 'example_gov_id', 'value': 'T-1007'}],
    affiliations=[{'organization': 'Example Party', 'from': '2020-01-01'}],
)

PEOPLE = [ALEX_DOE_CITY, ALEX_DOE_COUNTY, ROBIN_ROE, JOSE_RIOS, TAYLOR_TRAN]
PEOPLE_BY_ID = {person['id']: person for person in PEOPLE}
