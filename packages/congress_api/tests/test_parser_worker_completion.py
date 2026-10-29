"""A slow first input cannot leave later parser slots idle."""
import threading
from congress_api.retention.parser_worker import ParserWorkerPool


def test_completed_inputs_replenish_while_the_first_input_is_still_blocked():
    release=threading.Event();received=[];state=dict(produced=0,closed=0)
    class Worker:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):state['closed']+=1
    def inputs():
        for n in range(40):
            state['produced']+=1
            assert state['produced']<=len(received)+9,'At most4N pending calls plus the delivered result'
            yield n
    def parse(worker,n):
        if n==0:assert release.wait(3),'Ordered consumption stalled all later replenishment'
        return n
    try:
        with ParserWorkerPool('p','v','fixture:parse',workers=2,memory_budget=64<<20,worker_factory=Worker,
            timeout_seconds=1,memory_bytes=16<<20,max_input_bytes=1024,max_output_bytes=1024) as pool:
            for value in pool.map(parse,inputs()):
                received.append(value)
                if len(received)==20:
                    assert 0 not in received
                    release.set()
    finally:release.set()
    assert sorted(received)==list(range(40)) and 1<=state['closed']<=2
