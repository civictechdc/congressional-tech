"""Native raw-to-catalog update, qualification and explicit source-rule upgrade."""


def update_from_raw(store, *, raw_storage, directory, candidate, expected_bodies=(), seeds=()):
    """Resume the maintained native receipt-to-catalog update in retained storage."""
    from .catalog_raw_updates import update_from_raw as update
    return update(store, raw_storage=raw_storage, directory=directory, candidate=candidate,
                  expected_bodies=expected_bodies, seeds=seeds)


def qualify_source_contributions(store, *, raw_storage, directory, candidate, expected_bodies=(), seeds=()):
    from .catalog_raw_updates import qualify_source_contributions as qualify
    return qualify(store, raw_storage=raw_storage, directory=directory, candidate=candidate,
                   expected_bodies=expected_bodies, seeds=seeds)


def upgrade_source_rules(store, *, raw_storage, directory, candidate, rule_version, expected_bodies=(), seeds=(),
                         schema_additions=(), write_defaults=None, scalar_backfill=None,
                         continuous_backfill=None, dependency_correction=None):
    from .catalog_raw_updates import upgrade_source_rules as upgrade
    return upgrade(store, raw_storage=raw_storage, directory=directory, candidate=candidate,
                   rule_version=rule_version, expected_bodies=expected_bodies, seeds=seeds,
                   schema_additions=schema_additions, write_defaults=write_defaults,
                   scalar_backfill=scalar_backfill, continuous_backfill=continuous_backfill,
                   dependency_correction=dependency_correction)
