"""Bounded completion-driven calls through a caller-owned executor."""
from concurrent.futures import wait,FIRST_COMPLETED


def completed_map(executor,function,items,*,max_pending):
    """Yield each result once; pending work stays bounded without input-order waits."""
    if type(max_pending) is not int or max_pending<=0:
        raise ValueError('Pending work requires a positive integer bound')
    source=iter(items);pending=set()
    try:
        for _ in range(max_pending):
            try:item=next(source)
            except StopIteration:break
            pending.add(executor.submit(function,item))
        while pending:
            done,_=wait(pending,return_when=FIRST_COMPLETED)
            while done:
                future=done.pop();pending.remove(future)
                result=future.result()
                try:item=next(source)
                except StopIteration:pass
                else:pending.add(executor.submit(function,item))
                yield result
    finally:
        for future in pending:future.cancel()
