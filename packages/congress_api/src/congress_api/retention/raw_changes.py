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
        head, pending = None, []
        for key in keys:
            proposal = dict(version=1, previous=head, keys=[*pending, key])
            if len(pending) == KEYS_PER_PAGE or len(encoded(proposal)) > self.objects.max_bytes:
                if not pending:
                    raise ValueError('One changed URL exceeds the metadata byte budget')
                head = self.objects.put(dict(version=1, previous=head, keys=pending))
                pending = []
            if len(encoded(dict(version=1, previous=head, keys=[key]))) > self.objects.max_bytes:
                raise ValueError('One changed URL exceeds the metadata byte budget')
            pending.append(key)
        return self.objects.put(dict(version=1, previous=head, keys=pending)) if pending else head

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
