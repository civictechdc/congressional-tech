from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.immutable_metadata import MetadataObjects


def test_lru_metadata_cache_rereads_evicted_exact_objects(tmp_path):
    class Store(LocalStore):
        reads = 0

        def read(self, key):
            self.reads += 1
            return super().read(key)

    store = Store(tmp_path)
    writer = MetadataObjects(store, 'cache-test')
    refs = [writer.put(dict(value=index)) for index in range(3)]
    reader = MetadataObjects(store, 'cache-test', max_cache_entries=2)
    for ref in refs[:2]:
        reader.read(ref)
    reader.read(refs[0])  # Keep the first object hot.
    reader.read(refs[2])
    assert store.reads == 3
    assert reader.read(refs[0]) == dict(value=0)
    assert reader.read(refs[1]) == dict(value=1)
    assert store.reads == 4
    assert len(reader._cache) == 2
