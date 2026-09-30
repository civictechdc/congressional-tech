"""Counterexamples from the independent September 2026 package reviews."""
import itertools
import json
import re
import subprocess
import sys

import pytest

from house_naming import Engine, NamingError, check_catalog
from house_naming.extraction import Extractor
from house_naming.extraction_catalog import ROLE_INPUTS, PROCESSOR_INPUTS
from house_naming.catalog import load_guide


@pytest.fixture(scope='module')
def engine():
    return Engine()


@pytest.mark.parametrize('ordinal', ['ST', 'Nd', 'rD', 'TH'])
@pytest.mark.parametrize('separator', ['-', '_', ''])
def test_ordinal_numbers_remain_uncertain(engine, ordinal, separator):
    tail = ordinal + separator + ('Congress' if separator else '')
    name = f'BILLS-118HR2534116{tail}ih.pdf'
    result = engine.extract(name)
    assert all('measureNumber' not in m['record'] for m in result['matches'])
    assert any(f['name'] == 'ambiguous_number_token' for m in result['observations'] for f in m['fields'])
    with pytest.raises(NamingError, match='ordinal'):
        engine.validate(dict(kind='bill-numbered-described', congress=118, numberedSubject='HR2534116',
                             description=tail, stage='ih', versionSuffix='', extension='pdf'))
    referenced = engine.parse(f'BILLS-115HR5759ih-HR575921{tail}.pdf')['matches'][0]['record']
    assert referenced['measureNumber'] == 5759
    assert 'references' not in referenced


@pytest.mark.parametrize('suffix,expected', [('-err', {}), ('-err2', {}), ('-ERR', {}),
    ('-errata', {'errata': ''}), ('-errata2', {'errata': '2'}), ('-addendum', {'addendum': ''})])
def test_hearing_components_do_not_resolve_ambiguous_err(engine, suffix, expected):
    name = f'CHRG-107shrg83924{suffix}.pdf'
    record = engine.parse(name)['matches'][0]['record']
    assert {k: record[k] for k in ('errata', 'addendum') if k in record} == expected
    assert record['publicationSuffix'] == suffix
    assert engine.render(record) == name
    assert engine.validate(record) == record
    if suffix.lower().startswith('-err') and not expected:
        with pytest.raises(NamingError, match='errata disagrees'):
            engine.validate(dict(record, errata=''))


@pytest.mark.parametrize('digit', ['9', '0'])
def test_long_revision_is_literal_text(engine, digit):
    from house_naming.filenames import parse_filename
    name = 'notes-U' + digit * 5000 + '.pdf'
    result = engine.extract(name)
    assert ''.join(p['raw'] for p in result['pieces']) == name
    fields = [f for m in (*result['observations'], *result['suppressed']) for f in m['fields']]
    assert any(f['name'] == 'revision_number' and f['raw'] == digit * 5000 for f in fields)
    assert 'filename-too-long' in parse_filename(name).issues
    assert any(f['code'] == 'u' for f in fields) == (digit != '0')
    cli = subprocess.run([sys.executable, '-m', 'house_naming', 'extract', name],
                         capture_output=True, text=True, timeout=5)
    assert cli.returncode == 0, cli.stderr


@pytest.mark.parametrize('role,damage', [(role, damage) for role in sorted(ROLE_INPUTS)
    for damage in ('remove', 'rename', 'capture', 'scope')
    if damage != 'capture' or ROLE_INPUTS[role][1]])
def test_required_roles_fail_catalog_check_before_extraction(engine, role, damage):
    guide = engine.guide
    rid = guide['extraction_roles'][role]
    rule = next(r for r in guide['extraction_rules'] if r['id'] == rid)
    if damage == 'remove':
        guide['extraction_rules'].remove(rule)
    elif damage == 'rename':
        rule['id'] += '-renamed'
    elif damage == 'capture':
        field = sorted(ROLE_INPUTS[role][1])[0]
        rule['pattern'] = rule['pattern'].replace(f'(?P<{field}>', f'(?P<renamed_{field}>')
    else:
        rule['scope'] = 'stem'
    with pytest.raises(NamingError) as failure:
        check_catalog(guide)
    assert failure.value.code == 'invalid-catalog'
    with pytest.raises(NamingError):
        Extractor(guide)


def test_catalog_requires_rule_list(engine):
    guide = engine.guide
    del guide['extraction_rules']
    with pytest.raises(NamingError) as failure:
        check_catalog(guide)
    assert failure.value.code == 'invalid-catalog'


@pytest.mark.parametrize('rid,field', [
    (rule['id'], field) for rule in load_guide()['extraction_rules']
    for processor in rule.get('processors', ()) for field in sorted(PROCESSOR_INPUTS[processor])
])
def test_optional_handlers_require_the_captures_they_read(engine, rid, field):
    guide = engine.guide
    rule = next(r for r in guide['extraction_rules'] if r['id'] == rid)
    rule['pattern'] = rule['pattern'].replace(f'(?P<{field}>', f'(?P<renamed_{field}>')
    with pytest.raises(NamingError) as failure:
        check_catalog(guide)
    assert failure.value.code == 'invalid-catalog'


@pytest.mark.parametrize('priority', [0, 1, 2, 3])
def test_every_accepted_stem_priority_executes(engine, priority):
    guide = engine.guide
    guide['extraction_rules'].append(dict(id='review-stem', scope='stem', priority=priority,
        pattern=r'(?P<review_field>ZZQX)', description='Unique regression token.'))
    if priority == 3:
        with pytest.raises(NamingError, match='Unsupported priority'):
            check_catalog(guide)
    else:
        check_catalog(guide)
        assert any(r['rule'] == 'review-stem' for r in Extractor(guide).extract('ZZQX.pdf')['observations'])


@pytest.mark.parametrize('scope,name', [
    ('document-wording-search', 'ZZQX.pdf'), ('transport-search', 'file.pdfZZQX')])
def test_new_scope_rules_execute_without_python_registration(engine, scope, name):
    guide = engine.guide
    guide['extraction_rules'].append(dict(id='catalog-only-rule', scope=scope, priority=0,
        pattern=r'(?P<review_field>ZZQX)', description='Catalog-only extension.'))
    check_catalog(guide)
    assert any(m['rule'] == 'catalog-only-rule' for m in Extractor(guide).extract(name)['observations'])


def test_suffix_regexes_keep_original_field_boundaries(engine):
    # Independent old shapes establish the exact split, including an all-separator name.
    rules = {r['id']: r for r in engine.extraction_rules()}
    for rid, field, separator, suffixes in [
        ('subject-labeled', 'subject_token', ' _-', ['Statement', 'Witness List', 'not-a-label']),
        ('unmatched-trailing-date', 'name_token', ' ._-', ['2022-01-01', '01012022', 'invalid']),
        ('assumed-name-with-identifier', 'name_token', ' ._-', ['1234', '12pdf', 'not-a-number']),
    ]:
        new = re.compile(rules[rid]['pattern'], re.I | re.ASCII)
        tail = rules[rid]['pattern'].split(')[' + separator + ']+', 1)[1]
        old = re.compile(f'(?P<{field}>' + (r'(?![0-9])' if field == 'name_token' else '')
                         + r'.+?)[' + separator + ']+' + tail, re.I | re.ASCII)
        for prefix in (''.join(p) for n in range(1, 5) for p in itertools.product('A ._-', repeat=n)):
            for suffix in suffixes:
                name = prefix + suffix
                a, b = old.fullmatch(name), new.fullmatch(name)
                assert bool(a) == bool(b), (rid, name)
                if a:
                    assert a.groupdict() == b.groupdict(), (rid, name)
                    assert [a.span(k) for k in a.groupdict()] == [b.span(k) for k in b.groupdict()]


@pytest.mark.parametrize('shape', ['separators', 'numeric', 'many-refinements'])
def test_adversarial_literal_work_is_bounded(shape):
    code = '''from house_naming import Engine, NamingError
import json, sys
e=Engine()
name = {'separators': '_-' * 4096 + '.pdf', 'numeric': '1-1-' * 4000 + '.pdf',
        'many-refinements': '1-' * 1000 + 'Smith-2.pdf'}[sys.argv[1]]
try:
 r=e.extract(name)
 print(json.dumps({'observations':len(r['observations'])}))
except NamingError as exc:
 print(json.dumps(exc.as_dict()))
'''
    result = subprocess.run([sys.executable, '-c', code, shape], capture_output=True, text=True, timeout=3)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    if shape == 'separators':
        assert data['observations'] == 2
    else:
        assert data['code'] == 'extraction-limit'
