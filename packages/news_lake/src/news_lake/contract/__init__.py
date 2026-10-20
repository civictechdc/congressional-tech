"""Record contract: shape validation, schema-derived routing, corpus semantics."""
from news_lake.contract.errors import ContractError
from news_lake.contract.records import (
    CONTENT_TABLES,
    CONTRACT_VERSION,
    KIND_ORDER,
    KIND_TABLES,
    TABLE_KINDS,
    TABLE_MUTATIONS,
    UPSERT_TABLES,
    load_jsonl,
    mutation_for_table,
    parse_jsonl,
    table_for_kind,
    validate_shape,
)
from news_lake.contract.semantics import check_corpus

__all__ = [
    'ContractError',
    'CONTENT_TABLES',
    'CONTRACT_VERSION',
    'KIND_ORDER',
    'KIND_TABLES',
    'TABLE_KINDS',
    'TABLE_MUTATIONS',
    'UPSERT_TABLES',
    'check_corpus',
    'load_jsonl',
    'mutation_for_table',
    'parse_jsonl',
    'table_for_kind',
    'validate_shape',
]
