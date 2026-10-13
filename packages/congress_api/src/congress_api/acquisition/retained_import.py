"""Select separate initial and retry passes for importing retained responses.

The caller owns scope, saved-byte validation and storage serialization. Each
pass uses the maintained collector and its ordinary receipts and checkpoints.
"""
from congress_api.acquisition.raw_sync import RETRY_OUTCOMES, run_sync


def partition_retained_urls(state, urls):
    """Preserve input order while separating new/pending URLs from failures."""
    urls = list(urls)
    if (any(not isinstance(url, str) or not url for url in urls)
            or len(set(urls)) != len(urls)):
        raise ValueError('Import selection requires distinct nonempty URLs')
    initial, retries = [], []
    for url in urls:
        current = state.get(url)
        if current is None or current.get('outcome') == 'pending':
            initial.append(url)
        elif current.get('outcome') in RETRY_OUTCOMES:
            retries.append(url)
        else:
            raise ValueError(f'Import selection is not new, pending or retryable: {url}')
    return initial, retries


def capture_retained_batch(archive, urls, *, seed_context=None, **options):
    """Capture one homogeneous batch; reject mixed modes before any mutation.

    Use separate run IDs for the batches returned by partition_retained_urls.
    Successful/current terminal rows must be resolved by the caller beforehand.
    """
    initial, retries = partition_retained_urls(archive.state, urls)
    if not initial and not retries:
        raise ValueError('Import batch is empty')
    if initial and retries:
        raise ValueError('Separate initial and retry import batches')
    reserved = {'urls', 'retry_outcomes', 'retry_now', 'initial_only', 'reinspect_retained'}
    if reserved.intersection(options):
        raise ValueError('Import batch owns selection options')
    if initial:
        seeds = [dict(seed_context or {}, url=url)
                 for url in initial if url not in archive.state]
        return run_sync(archive, seeds, urls=initial, initial_only=True, **options)
    outcomes = {archive.state[url]['outcome'] for url in retries}
    return run_sync(archive, [], urls=retries, retry_outcomes=outcomes,
                    retry_now=True, **options)
