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


class RoutingPages:
    """Immutable delivery routing; leaves name caller-owned exact native pins.

    Branches contain at most sixteen child references. A missing child denotes
    an empty route, so future insertions never require a global repartition.
    Only the application selector chooses which immutable routing root is public.
    """
    def __init__(self, store, namespace):
        from congress_api.retention.immutable_metadata import MetadataObjects
        self.objects = MetadataObjects(store, namespace)

    def _read(self, reference, prefix):
        page = self.objects.read(reference)
        if page.get('version') != 1 or page.get('prefix') != prefix:
            raise ValueError('Routing page basis mismatch')
        if ('value' in page) == ('children' in page):
            raise ValueError('Routing page must name one leaf or branch')
        if 'children' in page:
            children = page['children']
            if (len(prefix) >= 64 or not 0 < len(children) <= 16
                    or any(char not in '0123456789abcdef' or len(char) != 1 for char in children)):
                raise ValueError('Invalid routing child references')
        elif not isinstance(page['value'], dict):
            raise ValueError('Routing leaf must name exact native metadata')
        return page

    def lookup(self, root, key):
        digest, prefix, reference = key_hash(key), '', root
        while reference is not None:
            page = self._read(reference, prefix)
            if 'value' in page:
                return prefix, page['value']
            char = digest[len(prefix)]
            prefix += char
            reference = page['children'].get(char)
        return prefix, None

    def replace(self, root, prefix, leaves):
        """Replace exactly one selected leaf, sharing every untouched branch."""
        if (not isinstance(prefix, str) or len(prefix) > 64
                or any(char not in '0123456789abcdef' for char in prefix)):
            raise ValueError('Invalid routing prefix')
        if not leaves or any(not leaf.startswith(prefix) or len(leaf) > 64
                             or any(c not in '0123456789abcdef' for c in leaf) for leaf in leaves):
            raise ValueError('Replacement leaves fall outside the affected prefix')

        def build(current, values):
            if current in values:
                if len(values) != 1:
                    raise ValueError('Replacement leaf prefixes overlap')
                value = values[current]
                if value is None:
                    return None
                if not isinstance(value, dict):
                    raise ValueError('Routing leaf must name exact native metadata')
                return self.objects.put(dict(version=1, prefix=current, value=value))
            children = {}
            for char in '0123456789abcdef':
                subset = {leaf: value for leaf, value in values.items() if leaf.startswith(current + char)}
                if subset:
                    reference = build(current + char, subset)
                    if reference is not None:
                        children[char] = reference
            return self.objects.put(dict(version=1, prefix=current, children=children)) if children else None

        def replace_at(reference, current):
            page = self._read(reference, current) if reference is not None else None
            if current == prefix:
                if page is not None and 'children' in page:
                    raise ValueError('Replace a selected leaf, not an unrelated branch')
                return build(current, leaves)
            if page is None or 'children' not in page:
                raise ValueError('Replacement prefix is not a selected leaf')
            children = dict(page['children'])
            char = prefix[len(current)]
            replacement = replace_at(children.get(char), current + char)
            if replacement is None:
                children.pop(char, None)
            else:
                children[char] = replacement
            return self.objects.put(dict(version=1, prefix=current, children=children)) if children else None

        return replace_at(root, '')

    def leaf_items(self, root):
        def walk(reference, prefix):
            if reference is None:
                return
            page = self._read(reference, prefix)
            if 'value' in page:
                yield prefix, page['value']
            else:
                for char, child in sorted(page['children'].items()):
                    yield from walk(child, prefix + char)
        yield from walk(root, '')
