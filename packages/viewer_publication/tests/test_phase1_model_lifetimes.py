"""Every native model reader owns its inputs until their actual final use."""
import json
import os

import pytest


def test_dependencies_use_sql_ast_scopes_and_ignore_literals_and_comments():
    from viewer_publication.archive_model_lifetimes import sql_dependencies
    sql = '''WITH masked AS (SELECT * FROM "raw_facts"),
        nested AS (WITH raw_facts AS (SELECT * FROM other_facts)
                   SELECT * FROM raw_facts)
        SELECT 'FROM phantom' FROM masked
        LEFT ANTI JOIN nested USING(id) -- JOIN imaginary
        WHERE EXISTS (SELECT 1 FROM guard_facts)'''
    assert sql_dependencies(sql) == {'raw_facts', 'other_facts', 'guard_facts'}
    assert sql_dependencies("WITH facts AS (SELECT * FROM facts) SELECT * FROM facts") == {'facts'}
    assert sql_dependencies("SELECT 'é' FROM left_facts RIGHT ANTI JOIN right_facts USING(id)") == {
        'left_facts', 'right_facts'}
    with pytest.raises(ValueError, match='parse'):
        sql_dependencies('SELECT * FROM (')


def test_last_readers_include_lazy_view_ownership_components_exports_and_guards():
    from viewer_publication.archive_model_lifetimes import retire_relations
    spec = dict(inputs=[dict(name='raw'), dict(name='registry')], steps=[
        dict(name='facts', sql='SELECT * FROM raw', materialize=True),
        dict(name='lazy', sql='SELECT * FROM facts'),
        dict(name='unused', sql='SELECT * FROM facts'),
        dict(name='lazy2', sql='SELECT * FROM lazy'),
        dict(name='snapshot', sql='SELECT * FROM lazy2 JOIN registry USING(id)', materialize=True),
        dict(name='components', components=dict(sql='SELECT * FROM snapshot')),
        dict(name='final', sql='SELECT * FROM components', materialize=True),
    ], outputs=[dict(name='export', sql='SELECT * FROM final')],
        queries=[dict(name='guard', sql='SELECT count(*) FROM snapshot')])
    retained = retire_relations(spec)
    assert 'release_after' not in spec['steps'][0], 'caller plan must remain intact'
    releases = {step['name']: step.get('release_after', []) for step in retained['steps']}
    assert releases == dict(facts=[], lazy=[], lazy2=[],
        snapshot=['lazy2', 'lazy', 'facts'], components=[], final=['components'])


def test_missing_or_forward_model_dependency_refuses_before_native_execution():
    from viewer_publication.archive_model_lifetimes import retire_relations
    with pytest.raises(ValueError, match='unavailable'):
        retire_relations(dict(inputs=[], steps=[dict(name='early', sql='SELECT * FROM later'),
            dict(name='later', sql='SELECT 1')], outputs=[], queries=[]))


def test_actual_raw_lake_model_releases_every_relation_after_its_last_reader(tmp_path):
    """Run the real producers and guards, then independently simulate ownership.

    Source SQL in the submitted job includes every component, export and query;
    the simulation expands lazy providers but stops at materialized successors.
    """
    from archive_job_fixture import real_model_spec
    from viewer_publication.archive_model_job import execute, validate_spec
    from viewer_publication.archive_model_lifetimes import sql_dependencies
    value, _digest, _html = real_model_spec(tmp_path)
    result = execute(validate_spec(value, base=tmp_path))
    assert result['status'] == 'built'
    job = json.loads((tmp_path/'model/job.json').read_text())
    steps = job['steps']; names = {step['name'] for step in steps}
    dependencies = {step['name']: sql_dependencies(step.get('sql', step.get('components', {}).get('sql')))
                    for step in steps}
    lazy = {step['name'] for step in steps if 'components' not in step and not step.get('materialize')}

    def providers(readers):
        result = set(readers)
        for name in readers & lazy:
            result |= providers(dependencies[name])
        return result

    last = {step['name']: index for index, step in enumerate(steps)}
    for index, step in enumerate(steps):
        for name in providers(dependencies[step['name']]) & names:
            last[name] = max(last[name], index)
    for reader in job['outputs'] + job['queries']:
        for name in providers(sql_dependencies(reader['sql'])) & names:
            last[name] = len(steps)  # C7 retains final readers until job teardown.
    available = {item['name'] for item in job['inputs']}
    for index, step in enumerate(steps):
        assert providers(dependencies[step['name']]) <= available, step['name']
        available.add(step['name'])
        expected = {name for name in names if last[name] == index}
        assert set(step.get('release_after', [])) == expected, step['name']
        available -= expected
        # No registered lazy provider may keep a released input alive by Arc.
        assert all(providers(dependencies[name]) <= available for name in available & lazy)
    for reader in job['outputs'] + job['queries']:
        assert providers(sql_dependencies(reader['sql'])) <= available, reader['name']
    assert available & names == {name for name in names if last[name] == len(steps)}
    assert len(names) == 148  # Complete model, two unused diagnostics removed, interval candidates shared.
