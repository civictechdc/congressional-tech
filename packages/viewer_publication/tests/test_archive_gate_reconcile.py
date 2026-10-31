"""Reconcile only an exact selected pointer after an uncertain PUT."""
import json
from io import BytesIO

import pytest

from viewer_publication.archive_gate import gate_and_flip


class Store:
    def __init__(self, outcome):
        self.outcome=outcome
        self.value={'release_id':'a'*64,'previous_release_id':None}
        self.puts=0

    def put_object(self, **args):
        self.puts+=1
        if self.outcome=='committed':
            self.value=json.loads(args['Body'])
        elif self.outcome=='competing':
            self.value={'release_id':'c'*64,'previous_release_id':'a'*64}
        raise OSError('lost response')

    def get_object(self, **args):
        raw=json.dumps(self.value).encode()
        return {'Body':BytesIO(raw),'ETag':'observed','ContentLength':len(raw)}


def test_lost_pointer_acknowledgment_is_reconciled_without_a_second_put():
    store=Store('committed')
    passed=lambda: {'status':'passed','releaseId':'b'*64,'targets':'owner-approved'}
    receipt=gate_and_flip(store,bucket='fake',release_id='b'*64,previous_release_id='a'*64,
        expected_etag='old',contract=passed,canary=passed)
    assert receipt.etag=='observed' and receipt.reconciled
    assert store.puts==1


@pytest.mark.parametrize('outcome',['unchanged','competing'])
def test_unselected_candidate_preserves_the_original_failure(outcome):
    store=Store(outcome)
    passed=lambda: {'status':'passed','releaseId':'b'*64,'targets':'owner-approved'}
    with pytest.raises(OSError,match='lost response'):
        gate_and_flip(store,bucket='fake',release_id='b'*64,previous_release_id='a'*64,
            expected_etag='old',contract=passed,canary=passed)
    assert store.puts==1
