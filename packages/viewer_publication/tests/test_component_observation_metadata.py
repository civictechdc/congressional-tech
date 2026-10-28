"""Shared observation assets keep document metadata linear and bounded."""
import json

import pyarrow as pa

from congress_api.retention.catalog_validation import catalog_source_ids_digest
from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY
from viewer_publication.filename_native import ViewerAssets, publish_occurrence_assets, typed_observations
from test_native_component_chunk_budget import chunk


def test_binary_document_assets_equal_combined_output_without_flat_index(tmp_path):
    kind = pa.struct([('label', pa.list_(pa.string())), ('links', pa.list_(pa.string()))])
    schema = pa.schema([('source_occurrences', pa.list_(kind))])
    original = [None, [], [None, {'label': ['é', '', None], 'links': []},
                            {'label': None, 'links': ['https://example.test']}]]
    class Values:
        def __init__(self, values):self.values = pa.array(values, type=kind)
        def __len__(self):return len(self.values)
        def __iter__(self):return iter([self.values])
    source = typed_observations(schema, pa.array(['a','b','c']),
                                lambda identity: None if original[ord(identity)-ord('a')] is None
                                else Values(original[ord(identity)-ord('a')]))
    outputs = []
    for flat in [True,False]:
        folder = tmp_path / str(flat);folder.mkdir()
        assets = ViewerAssets(folder / 'assets')
        result = publish_occurrence_assets(source, folder, assets, policy=DEFAULT_DECODED_POLICY,
                                          metrics={}, include_flat=flat)
        outputs.append(result)
        assert (folder / 'occurrences.parquet').exists() == flat
    assert 'occurrences' in outputs[0] and 'occurrences' not in outputs[1]
    assert outputs[1] == {name:value for name,value in outputs[0].items() if name!='occurrences'}


def test_component_pages_stay_bounded_when_a_chunk_has_thousands_of_parents(tmp_path):
    count = 4096
    with chunk(tmp_path, 'documents', ['small'] * count, observations=True) as (current,args,expected):
        current._prepare_chunk(*args)
        reference = json.loads(current.db.execute('SELECT reference FROM chunk_assets').fetchone()[0])
        assert reference['document_file']['rows'] == count
        assert reference['document_observations']['rows'] == count
        assert set(reference['document_observations']['files']) == {
            'observations','observation_rows','observation_index'}
        for row in expected.select(['source_id','document_id']).to_pylist():
            source,document = row['source_id'],row['document_id']
            proof = {'validation':{'counts':{'source_rows':1},
                                  'source_ids_sha256':catalog_source_ids_digest([source])}}
            current.db.execute('UPDATE components SET proof=?,reference=? WHERE id=?',
                (json.dumps(proof),json.dumps({'component':document,'page':{'key':'proof','sha256':'a'*64,'bytes':1}}),document))
            current.db.execute('UPDATE stats SET n=1 WHERE id=?',(document,))
            current.db.execute('INSERT INTO member_ids VALUES (?,?,?)',(document,0,source))
        current._prepare_entries()
        entries = current.db.execute('SELECT id,entry FROM components ORDER BY id').fetchall()
        assert len(entries) == count
        assert sum(len(value.encode()) for _,value in entries) < count * 4096
        for offset in range(0,count,64):
            planned = current._stage({'kind':'component-leaf','prefix':'','native_sha256':'a'*64,
                'members':{document:{'pending':document} for document,_ in entries[offset:offset+64]}})
            reference = current.finish(planned)
            assert reference['bytes'] <= current.assets.max_node_bytes
