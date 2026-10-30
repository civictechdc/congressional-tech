"""Explicit retries and resource-based admission preserve capture boundaries."""
from congress_api.transport.rust_fetch import RustFetcher
from testing_fakes import response


def test_resource_refusal_preserves_native_error_and_never_uses_provider(monkeypatch):
    from congress_api.transport import rust_fetch
    calls=[]
    # Supply a complete synthetic native result without starting a worker.
    def fetch(url, **options):
        calls.append(options['transport'])
        result=response(url,b'')
        result.update(complete=False,error='response_limit',source_metadata={
            'body_read_skipped':'declared_size_limit','declared_body_bytes':9999})
        return result
    monkeypatch.setattr(rust_fetch,'fetch_source',fetch)
    fetcher=RustFetcher.__new__(RustFetcher);fetcher.max_bytes=1024;fetcher.limit_basis='resource_budget'
    result,(outcome,links)=fetcher._fetch('https://www.govinfo.gov/a.pdf',transport='auto')
    assert calls==['direct'] and outcome=='resource_limit' and not links
    assert result['error']=='response_limit' and not result['complete']
    assert result['source_metadata']['declared_body_bytes']==9999
    assert result['body_limit_basis']=='resource_budget' and result['body_limit_bytes']==1024
