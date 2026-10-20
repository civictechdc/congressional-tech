"""Pure hash-prefix routing for bounded application source partitions.

Native DocSpec owns every partition's records, versions and completion. These
functions only route application keys and divide an affected bounded Arrow table;
they do not store values, select snapshots or manage operation recovery.
"""
from hashlib import sha256

import pyarrow as pa


def key_hash(key):
    if not isinstance(key, str):
        raise ValueError('Partition keys must be strings')
    return sha256(key.encode('utf-8')).hexdigest()


def route_prefix(key, prefixes):
    """Resolve exactly one selected leaf; missing or overlapping scope refuses."""
    digest = key_hash(key)
    matches = [prefix for prefix in prefixes if digest.startswith(prefix)]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous selected partition route')
    return matches[0]


def split_partition(table, *, key, prefix, max_rows, max_bytes):
    """Split only this full leaf, preserving typed rows and order within leaves.

    The byte bound counts decoded Arrow buffers, not compressed objects or total
    process memory. One oversized row and indistinguishable SHA-256 keys refuse
    explicitly; neither case triggers a corpus-wide rehash or rebuild.
    """
    if (not isinstance(prefix, str) or len(prefix) > 64
            or any(char not in '0123456789abcdef' for char in prefix)):
        raise ValueError('Invalid hash partition prefix')
    if max_rows < 1 or max_bytes < 1:
        raise ValueError('Partition budgets must be positive')
    keys = table[key].to_pylist()
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate partition keys')
    hashes = [key_hash(value) for value in keys]
    if any(not value.startswith(prefix) for value in hashes):
        raise ValueError('Rows fall outside the affected partition prefix')

    def divide(indices, current):
        part = table.take(pa.array(indices, type=pa.int64()))
        if len(part) <= max_rows and part.nbytes <= max_bytes:
            return [(current, part)]
        if len(part) <= 1:
            raise ValueError('A single row exceeds the partition byte budget')
        if len(current) == 64:
            raise ValueError('SHA-256 collision exceeds the partition budget')
        # Retain empty child routes so future keys have exactly one owner.
        # Callers need no native dataset for an empty child.
        children = {current + char: [] for char in '0123456789abcdef'}
        for index in indices:
            children[hashes[index][:len(current) + 1]].append(index)
        return [leaf for child, members in sorted(children.items())
                for leaf in divide(members, child)]

    return divide(list(range(len(table))), prefix)
