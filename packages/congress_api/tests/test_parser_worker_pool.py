"""A bounded pool reuses supervised workers and returns results in input order."""
import threading
import pytest
from congress_api.retention import parser_worker

LIMITS=dict(timeout_seconds=1,memory_bytes=16<<20,max_input_bytes=1024,max_output_bytes=1024)


def test_pool_runs_concurrently_bounds_input_and_closes_every_worker():
    lock=threading.Lock();started=threading.Event();released=threading.Event();state=dict(created=0,closed=0,active=0,peak=0,produced=0)
    class Worker:
        def __init__(self,*args,**kwargs):self.calls=0
        def __enter__(self):
            with lock:state['created']+=1
            return self
        def __exit__(self,*args):
            with lock:state['closed']+=1
        def parse(self,value,payload):
            with lock:
                state['active']+=1;state['peak']=max(state['peak'],state['active'])
                if state['active']==2:started.set()
            assert released.wait(2)
            with lock:state['active']-=1
            self.calls+=1
            return int(value)
    def inputs():
        for value in range(30):
            state['produced']+=1
            if state['produced']==8:
                assert started.wait(2);released.set()
            yield value
    with parser_worker.ParserWorkerPool('p','v','fixture:parse',workers=2,memory_budget=64<<20,
            worker_factory=Worker,**LIMITS) as pool:
        results=pool.map(lambda worker,value:worker.parse(str(value),b'input'),inputs())
        assert next(results)==0 and state['produced']==8
        assert [0,*results]==list(range(30))
    assert state['peak']==2 and 1<=state['created']<=2
    assert state['created']==state['closed'] and state['active']==0


@pytest.mark.parametrize('workers,budget',[(0,64<<20),(True,64<<20),(33,1<<40),(2,16<<20)])
def test_pool_refuses_invalid_bounds_before_worker_allocation(workers,budget):
    def forbidden(*args,**kwargs):raise AssertionError('worker before admission')
    with pytest.raises(ValueError):
        parser_worker.ParserWorkerPool('p','v','fixture:parse',workers=workers,memory_budget=budget,
            worker_factory=forbidden,**LIMITS)


def test_pool_failure_closes_started_workers_and_preserves_the_error():
    state=dict(created=0,closed=0)
    class Worker:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):state['created']+=1;return self
        def __exit__(self,*args):state['closed']+=1
    def parse(worker,value):
        if value==2:raise RuntimeError('retained failure')
        return value
    with pytest.raises(RuntimeError,match='retained failure'):
        with parser_worker.ParserWorkerPool('p','v','fixture:parse',workers=2,memory_budget=64<<20,
                worker_factory=Worker,**LIMITS) as pool:list(pool.map(parse,range(100)))
    assert state['created']==state['closed']
