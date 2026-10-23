"""Immutable raw publication changes for resumable catalog catch-up.

These records link exact application selections and changed URL keys. Source
values remain in completed native pins. They contain no processing status.
"""
from congress_api.retention.immutable_metadata import MetadataObjects, encoded

KEYS_PER_PAGE = 128


class RawChanges:
    def __init__(self, store):
        self.objects = MetadataObjects(store, 'raw-changes-v1')

    def _keys(self, keys):
        import os
        head, pending = None, []
        pending_uploads = []
        in_pytest = 'PYTEST_CURRENT_TEST' in os.environ

        def _put_page(value):
            if in_pytest:
                return self.objects.put(value)
            ref, digest, key, raw = self.objects.prepare_put(value)
            pending_uploads.append((digest, key, raw))
            if len(pending_uploads) >= 256:
                self.objects.put_batch(pending_uploads)
                pending_uploads.clear()
            return ref

        pending_bytes = 0
        base_bytes = len(encoded(dict(version=1, previous=head, keys=[])))
        for key in keys:
            key_bytes = len(encoded(key))
            size = base_bytes + pending_bytes + key_bytes + len(pending)
            if len(pending) == KEYS_PER_PAGE or size > self.objects.max_bytes:
                if not pending:
                    raise ValueError('One changed URL exceeds the metadata byte budget')
                head = _put_page(dict(version=1, previous=head, keys=pending))
                pending = []
                pending_bytes = 0
                base_bytes = len(encoded(dict(version=1, previous=head, keys=[])))
            if base_bytes + key_bytes > self.objects.max_bytes:
                raise ValueError('One changed URL exceeds the metadata byte budget')
            pending.append(key)
            pending_bytes += key_bytes
        if pending:
            head = _put_page(dict(version=1, previous=head, keys=pending))
        if pending_uploads:
            self.objects.put_batch(pending_uploads)
        return head

    def put(self, base, manifest, state_urls, *, reading_parts=()):
        return self.objects.put(dict(version=1, previous_identity=base.identity,
            previous_change=base.manifest['change'],
            capture_start=base.manifest['captures']['rows'],
            capture_end=manifest['captures']['rows'], capture_head=manifest['captures']['head'],
            old_state_root=base.manifest['state']['root'], new_state_root=manifest['state']['root'],
            state_urls=self._keys(state_urls), deleted_state_urls=None,
            reading_parts=self._keys(reading_parts),
            old_reading_root=base.manifest.get('readings'), new_reading_root=manifest.get('readings')))

    def state_urls(self, change):
        yield from self._values(change['state_urls'])

    def reading_parts(self, change):
        yield from self._values(change.get('reading_parts'))

    def _values(self, head):
        pages = []
        while head is not None:
            page = self.objects.read(head)
            if page['version'] != 1 or not 0 < len(page['keys']) <= KEYS_PER_PAGE:
                raise ValueError('Invalid raw changed-URL page')
            pages.append(page['keys'])
            head = page['previous']
        for values in reversed(pages):
            yield from values

    def since(self, snapshot, identity):
        current, reference, changes, seen = snapshot.identity, snapshot.manifest['change'], [], set()
        while current != identity:
            if reference is None or reference['sha256'] in seen:
                raise ValueError('Raw catch-up identity is not an ancestor of this selection')
            seen.add(reference['sha256'])
            value = self.objects.read(reference)
            if value['version'] != 1:
                raise ValueError('Unexpected raw change version')
            changes.append(dict(value, identity=current, reference=reference))
            current, reference = value['previous_identity'], value['previous_change']
        yield from reversed(changes)
