"""Release native relations from the complete application job's SQL graph."""
from congress_api.lake.model_sql import _dependencies, _parser, sql_dependencies

__all__ = ['retire_relations', 'sql_dependencies']


def retire_relations(spec):
    """Replace manual releases with each named step's final native reader.

    Lazy views retain their providers until the view's final reader. Materialized
    results and connected components own independent batches, ending that chain.
    C7 runs exports and queries after all steps, with no releases between them;
    their providers therefore remain registered until native job teardown.
    """
    steps = spec['steps']
    available = {item['name'] for item in spec['inputs']}
    dependencies = {}
    final = set()
    with _parser() as parser:
        for index, step in enumerate(steps):
            name = step['name']
            if name in available:
                raise ValueError('Duplicate model relation: ' + name)
            sql = step['components']['sql'] if 'components' in step else step['sql']
            readers = _dependencies(parser, sql)
            if readers - available:
                raise ValueError('Model reader has unavailable relations: ' + name + ': ' + ', '.join(sorted(readers-available)))
            dependencies[name] = readers
            available.add(name)
        for reader in [*spec['outputs'], *spec.get('queries', ())]:
            readers = _dependencies(parser, reader['sql'])
            if readers - available:
                raise ValueError('Final model reader has unavailable relations: ' + reader['name'])
            final |= readers
    # C7 cannot self-release. Omit relations with no path to an actual reader,
    # including unused views that would otherwise retain their input providers.
    live = set(final)
    for step in reversed(steps):
        if step['name'] in live:
            live |= dependencies[step['name']]
    steps = [step for step in steps if step['name'] in live]
    positions = {step['name']: index for index, step in enumerate(steps)}
    last = dict(positions)
    for index, step in enumerate(steps):
        for name in dependencies[step['name']] & positions.keys():
            last[name] = index
    for name in final & positions.keys():
        last[name] = len(steps)
    # Propagate ownership backwards only through lazy providers. This also
    # retires unused views at registration, avoiding hidden Arc-held batches.
    for step in reversed(steps):
        if 'components' not in step and not step.get('materialize'):
            for name in dependencies[step['name']] & positions.keys():
                last[name] = max(last[name], last[step['name']])
    releases = [[] for _step in steps]
    for step in reversed(steps):
        index = last[step['name']]
        if index < len(steps):
            releases[index].append(step['name'])
    # Drop dependent views before their providers when both die at one reader.
    planned = []
    lazy = {step['name'] for step in steps if 'components' not in step and not step.get('materialize')}
    for step, retired in zip(steps, releases):
        if not lazy.intersection(retired):
            previous = [name for name in dict.fromkeys(step.get('release_after', ())) if name in retired]
            retired = previous + [name for name in retired if name not in previous]
        step = {key: value for key, value in step.items() if key != 'release_after'}
        planned.append(dict(step, release_after=retired) if retired else step)
    return dict(spec, steps=planned)
