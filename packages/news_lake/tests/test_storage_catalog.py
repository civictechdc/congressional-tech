"""Catalog: news namespace, the 13 schema-derived tables, format v2, UUIDs."""
from news_lake.contract.records import KIND_TABLES


def test_namespace_and_all_tables_exist(lake):
    assert ('news',) in [tuple(ns) for ns in lake.catalog.list_namespaces()]
    assert sorted(KIND_TABLES.values()) == sorted(
        '.'.join(identifier) for identifier in lake.catalog.list_tables(('news',))
    )


def test_all_tables_use_format_v2_and_start_unpartitioned(lake):
    for table_name in KIND_TABLES.values():
        table = lake.table(table_name)
        assert table.metadata.format_version == 2, table_name
        assert all(not field.transform for field in table.spec().fields), table_name


def test_table_uuids_are_stable_across_reloads(lake):
    uuids = {name: lake.table_uuid(name) for name in KIND_TABLES.values()}
    for name, expected in uuids.items():
        again = lake.catalog.load_table(('news', name.split('.')[1]))
        assert str(again.metadata.table_uuid) == expected
        assert len(set(uuids.values())) == len(uuids)


def test_create_tables_is_idempotent(lake):
    lake.create_tables()
    assert len(lake.catalog.list_tables(('news',))) == 13
