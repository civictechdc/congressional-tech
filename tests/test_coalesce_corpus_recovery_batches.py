from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/corpus_recovery'))
from coalesce_corpus_recovery_batches import coalesce, coalesce_when_due, publication_due
from corpus_recovery.inventory import digest, sealed_inputs

class CoalesceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.baseline=self.root/'baseline.json'
        self.baseline.write_text(json.dumps(dict(recoveries=[dict(original_url='kept',body_key='old')],schema=1)))
    def batch(self,name,url,raw=b'pdf',historic=False):
        root=self.root/name;root.mkdir()
        sha=hashlib.sha256(raw).hexdigest();key=f'bodies/sha256/{sha[:2]}/{sha}.gz'
        row=dict(original_url=url,body_key=key,validated=True)
        accepted=[dict(original_url=url,body_key=key)]
        if historic:accepted.append(dict(original_url='deleted',body_key='old'))
        values={'recoveries.json':[row],'accepted.json':dict(recoveries=accepted),
            'bodies.json':{key:dict(sha256=sha,bytes=len(raw),path='/body-not-read-by-coalescer')},'zip-receipts.json':[]}
        for n,v in values.items():(root/n).write_text(json.dumps(v))
        (root/'manifest.json').write_text(json.dumps(dict(created_at='2026-10-16T00:00:00Z',recovered_urls=1,files={n:digest(root/n) for n in values})))
        (root/'prepared-source-records.json').write_text(json.dumps([dict(original_url=url,
            captures=[dict(body_key=key,sha256=sha,bytes=len(raw))])]))
        (root/'source-record-preparation.json').write_text(json.dumps(dict(unresolved=[],batch_manifest_sha256=digest(root/'manifest.json'))))
        return root
    def test_union_preserves_receipts_deduplicates_bodies_without_payload_io(self):
        a=self.batch('a','one',historic=True);b=self.batch('b','two')
        result=coalesce([a,b],baseline=self.baseline,destination=self.root/'combined')
        self.assertEqual((result['recovered_urls'],result['distinct_bodies']),(2,1))
        _,_,counts=sealed_inputs(self.root/'combined');self.assertEqual(counts['receipt_records'],2)
        accepted=json.loads((self.root/'combined/accepted.json').read_text())
        self.assertEqual({r['original_url'] for r in accepted['recoveries']},{'kept','one','two'})
    def test_conflicting_baseline_body_refuses_early(self):
        a=self.batch('a','kept')
        with self.assertRaisesRegex(ValueError,'authoritative baseline'):
            coalesce([a],baseline=self.baseline,destination=self.root/'combined')
    def test_conflicting_same_url_refuses(self):
        a=self.batch('a','one');b=self.batch('b','one',b'different')
        with self.assertRaisesRegex(ValueError,'Conflicting recovered'):coalesce([a,b],baseline=self.baseline,destination=self.root/'combined')
    def test_input_mutation_refuses(self):
        a=self.batch('a','one');(a/'recoveries.json').write_text('[]')
        with self.assertRaisesRegex(ValueError,'Batch changed'):coalesce([a],baseline=self.baseline,destination=self.root/'combined')
    def test_cli_path_obeys_cadence_and_flush(self):
        a=self.batch('a','one')
        result=coalesce_when_due([a],baseline=self.baseline,destination=self.root/'combined',
            now=datetime(2026,10,16,0,1,tzinfo=timezone.utc))
        self.assertFalse(result['ready']);self.assertFalse((self.root/'combined').exists())
        result=coalesce_when_due([a],baseline=self.baseline,destination=self.root/'combined',flush=True)
        self.assertEqual(result['input_batches'],1)
    def test_cadence_does_not_wait_for_entire_acquisition(self):
        rows=[dict(created_at='2026-10-16T00:00:00Z',recovered_urls=1)]
        self.assertTrue(publication_due(rows,now=datetime(2026,10,16,0,15,tzinfo=timezone.utc)))
        self.assertFalse(publication_due(rows,now=datetime(2026,10,16,0,1,tzinfo=timezone.utc)))
        rows[0]['recovered_urls']=100
        self.assertTrue(publication_due(rows,now=datetime(2026,10,16,0,1,tzinfo=timezone.utc)))

if __name__=='__main__':unittest.main()
