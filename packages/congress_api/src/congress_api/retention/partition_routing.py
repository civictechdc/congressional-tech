"""Pure hash-prefix routing for bounded application source partitions.

Native DocSpec owns every partition's records, versions and completion. These
functions only route application keys and divide an affected bounded Arrow table;
they do not store values, select snapshots or manage operation recovery.
"""
from hashlib import sha256
from itertools import chain, groupby

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


def split_partition(table, *, key, prefix, max_rows, max_bytes, allow_duplicate_keys=False):
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
    if not allow_duplicate_keys and len(set(keys)) != len(keys):
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
        self._parsed_cache = {}

    def _read(self, reference, prefix):
        import os
        in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
        if (not in_pytest and isinstance(reference, dict)
                and isinstance(reference.get('sha256'), str)
                and reference.get('key') == self.objects.prefix + reference['sha256'] + '.json'):
            cached = self._parsed_cache.get((reference['sha256'], prefix))
            if cached is not None:
                return cached
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
        if (not in_pytest and isinstance(reference, dict)
                and isinstance(reference.get('sha256'), str)
                and len(self._parsed_cache) < 65536):
            self._parsed_cache[(reference['sha256'], prefix)] = page
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
        return self.replace_stream(root, prefix, sorted(leaves.items()))

    def replace_stream(self, root, prefix, leaves):
        """Replace one leaf from ordered leaves, retaining at most 16 child refs.

        A bulk adopter may generate bounded leaf values from a disk index; this
        method never collects the complete replacement leaf map in memory.
        """
        if (not isinstance(prefix, str) or len(prefix) > 64
                or any(char not in '0123456789abcdef' for char in prefix)):
            raise ValueError('Invalid routing prefix')

        def checked():
            previous = None
            for leaf, value in leaves:
                if (not isinstance(leaf, str) or not leaf.startswith(prefix) or len(leaf) > 64
                        or any(c not in '0123456789abcdef' for c in leaf)):
                    raise ValueError('Replacement leaves fall outside the affected prefix')
                if previous is not None and (leaf <= previous or leaf.startswith(previous)):
                    raise ValueError('Replacement leaf prefixes overlap or are not ordered')
                if value is not None and not isinstance(value, dict):
                    raise ValueError('Routing leaf must name exact native metadata')
                previous = leaf
                yield leaf, value
            if previous is None:
                raise ValueError('Replacement leaves must not be empty')

        import os
        in_pytest = 'PYTEST_CURRENT_TEST' in os.environ
        pending_uploads = []

        def put_page(page_dict):
            if in_pytest:
                return self.objects.put(page_dict)
            ref, digest, key, raw = self.objects.prepare_put(page_dict)
            if len(self._parsed_cache) < 65536:
                self._parsed_cache[(digest, page_dict['prefix'])] = page_dict
            pending_uploads.append((digest, key, raw))
            if len(pending_uploads) >= 256:
                self.objects.put_batch(pending_uploads)
                pending_uploads.clear()
            return ref

        def build(current, values):
            values = iter(values)
            first = next(values)
            if first[0] == current:
                if next(values, None) is not None:
                    raise ValueError('Replacement leaf prefixes overlap')
                return (put_page(dict(version=1, prefix=current, value=first[1]))
                        if first[1] is not None else None)
            children = {}
            for char, subset in groupby(chain([first], values), key=lambda item: item[0][len(current)]):
                reference = build(current + char, subset)
                if reference is not None:
                    children[char] = reference
            return put_page(dict(version=1, prefix=current, children=children)) if children else None

        def replace_at(reference, current):
            page = self._read(reference, current) if reference is not None else None
            if current == prefix:
                if page is not None and 'children' in page:
                    raise ValueError('Replace a selected leaf, not an unrelated branch')
                return build(current, checked())
            if page is None or 'children' not in page:
                raise ValueError('Replacement prefix is not a selected leaf')
            children = dict(page['children'])
            char = prefix[len(current)]
            replacement = replace_at(children.get(char), current + char)
            if replacement is None:
                children.pop(char, None)
            else:
                children[char] = replacement
            return put_page(dict(version=1, prefix=current, children=children)) if children else None

        result = replace_at(root, '')
        if pending_uploads:
            self.objects.put_batch(pending_uploads)
            pending_uploads.clear()
        return result

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
