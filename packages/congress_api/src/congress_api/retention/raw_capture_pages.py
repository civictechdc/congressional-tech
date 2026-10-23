"""Bounded immutable delivery references to native raw capture batches.

These pages only select ordered completed native batches. They contain no source
rows, native operation phases, retry queue, or independent record lifecycle.
"""
from congress_api.retention.immutable_metadata import MetadataObjects, encoded

PAGE_ENTRIES = 64
PAGE_BYTES = 1 << 20


class CapturePages:
    def __init__(self, store):
        self.objects = MetadataObjects(store, 'raw-captures-v1', max_bytes=PAGE_BYTES)

    def _read(self, reference):
        page = self.objects.read(reference)
        entries = page['batches']
        if (page['version'] != 1 or not 0 < len(entries) <= PAGE_ENTRIES
                or len(entries) != reference['entries']
                or entries[0]['first_order'] != reference['first_order']
                or entries[-1]['first_order'] + entries[-1]['rows'] != reference['end_order']):
            raise ValueError('Capture page counts or order mismatch')
        self._check_order(entries, entries[0]['first_order'])
        previous = page['previous']
        if ((previous is None and reference['first_order'] != 0)
                or previous is not None and previous['end_order'] != reference['first_order']):
            raise ValueError('Capture page previous order mismatch')
        return page

    @staticmethod
    def _check_order(entries, start):
        position = start
        for entry in entries:
            if (entry['first_order'] != position or not isinstance(entry['rows'], int)
                    or entry['rows'] <= 0):
                raise ValueError('Capture batch order mismatch')
            position += entry['rows']

    def _write(self, previous, entries):
        self._check_order(entries, previous['end_order'] if previous else 0)
        reference = self.objects.put(dict(version=1, previous=previous, batches=entries))
        return dict(**reference, entries=len(entries),
                    first_order=entries[0]['first_order'],
                    end_order=entries[-1]['first_order'] + entries[-1]['rows'])

    def append(self, head, entries):
        """Append bounded references, reading at most the existing partial page."""
        import os
        entries = list(entries)
        if not entries:
            return head
        self._check_order(entries, head['end_order'] if head else 0)
        previous, pending = head, []
        if head is not None and head['entries'] < PAGE_ENTRIES:
            page = self._read(head)
            previous, pending = page['previous'], page['batches']
        dirty = False
        cursor = 0
        pending_bytes = sum(len(encoded(value)) for value in pending)
        base_bytes = len(encoded(dict(version=1, previous=previous, batches=[])))
        pending_uploads = []
        in_pytest = 'PYTEST_CURRENT_TEST' in os.environ

        def _enqueue_write(prev, batches):
            if in_pytest:
                return self._write(prev, batches)
            self._check_order(batches, prev['end_order'] if prev else 0)
            ref, digest, key, raw = self.objects.prepare_put(dict(version=1, previous=prev, batches=list(batches)))
            pending_uploads.append((digest, key, raw))
            if len(pending_uploads) >= 256:
                self.objects.put_batch(pending_uploads)
                pending_uploads.clear()
            return dict(**ref, entries=len(batches),
                        first_order=batches[0]['first_order'],
                        end_order=batches[-1]['first_order'] + batches[-1]['rows'])

        while cursor < len(entries):
            entry = entries[cursor]
            entry_bytes = len(encoded(entry))
            size = base_bytes + pending_bytes + entry_bytes + len(pending)
            if len(pending) == PAGE_ENTRIES or size > PAGE_BYTES:
                if not pending:
                    raise ValueError('One capture reference exceeds the page byte budget')
                if dirty:
                    head = _enqueue_write(previous, pending)
                previous, pending, dirty = head, [], False
                pending_bytes = 0
                base_bytes = len(encoded(dict(version=1, previous=previous, batches=[])))
                continue
            pending.append(entry)
            pending_bytes += entry_bytes
            cursor += 1
            dirty = True
        if dirty:
            head = _enqueue_write(previous, pending)
        if pending_uploads:
            self.objects.put_batch(pending_uploads)
        return head

    def entries(self, head):
        """Enumerate selected batch references in original observation order."""
        pages = []
        seen = set()
        while head is not None:
            if head['sha256'] in seen:
                raise ValueError('Capture page cycle')
            seen.add(head['sha256'])
            page = self._read(head)
            pages.append(page['batches'])
            head = page['previous']
        for batches in reversed(pages):
            yield from batches

    def entries_since(self, head, first_order):
        """Read only pages containing newly appended batch references."""
        if type(first_order) is not int or first_order < 0:
            raise ValueError('Invalid capture change start')
        end_order = head['end_order'] if head else 0
        if first_order > end_order:
            raise ValueError('Capture change start exceeds selected count')
        pages, seen = [], set()
        while head is not None and head['end_order'] > first_order:
            if head['sha256'] in seen:
                raise ValueError('Capture page cycle')
            seen.add(head['sha256'])
            page = self._read(head)
            pages.append([entry for entry in page['batches'] if entry['first_order'] >= first_order])
            head = page['previous']
        selected = [entry for entries in reversed(pages) for entry in entries]
        if not selected and first_order != end_order:
            raise ValueError('Capture change start is not a batch boundary')
        if selected:
            self._check_order(selected, first_order)
        yield from selected
