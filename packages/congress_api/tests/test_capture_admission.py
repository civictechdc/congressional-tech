from concurrent.futures import ThreadPoolExecutor

import pytest

from congress_api.acquisition.admission import Admission, AdmissionDenied


def test_concurrent_attempts_share_caps_and_unknown_survives_restart(tmp_path):
    path=tmp_path/'budget.sqlite'
    ledger=Admission(path,request_cap=3,spend_cap=4)
    def reserve(_):
        try:
            return ledger.reserve('provider',2)
        except AdmissionDenied:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(reserve,range(8)))
    admitted=[r for r in results if r]
    assert len(admitted)==2
    fresh=Admission(path,request_cap=3,spend_cap=4)
    assert fresh.totals()==dict(requests=2,committed_cost=4,unknown=2)
    with pytest.raises(AdmissionDenied):
        fresh.reserve('provider',1)
    fresh.settle(admitted[0],1)
    third=fresh.reserve('provider',1)
    fresh.settle(third,1)
    assert fresh.totals()==dict(requests=3,committed_cost=4,unknown=1)
    with pytest.raises(AdmissionDenied):
        fresh.reserve('direct',0)
    with pytest.raises(ValueError):
        Admission(path,request_cap=4,spend_cap=4)
