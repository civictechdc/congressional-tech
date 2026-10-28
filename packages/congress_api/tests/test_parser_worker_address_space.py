"""A worker gets one bounded address-space allowance above initialized mappings."""
import os
import sys

import pytest

from congress_api.retention.parser_worker import ParserWorker


@pytest.mark.parametrize('hard,expected',[
    (-1,((3<<30)+(512<<20),)*2),
    (4<<30,((3<<30)+(512<<20),)*2),
    ((3<<30)+(512<<20),((3<<30)+(512<<20),)*2)])
def test_large_initialized_virtual_size_keeps_the_configured_growth_allowance(hard,expected):
    from congress_api.retention.parser_worker import _address_space_limits
    assert _address_space_limits(3<<30,512<<20,hard,infinity=-1)==expected


def test_finite_inherited_hard_limit_cannot_be_silently_raised_or_shrink_the_budget():
    from congress_api.retention.parser_worker import _address_space_limits
    with pytest.raises(ValueError,match='inherited.*hard limit'):
        _address_space_limits(3<<30,512<<20,(3<<30)+(256<<20),infinity=-1)


@pytest.mark.parametrize('baseline,budget,hard',[(0,1,-1),(-1,1,-1),(True,1,-1),(1,0,-1),(1,True,-1),(1,1,-2),(1,1,False)])
def test_invalid_address_space_metadata_refuses(baseline,budget,hard):
    from congress_api.retention.parser_worker import _address_space_limits
    with pytest.raises(ValueError):_address_space_limits(baseline,budget,hard,infinity=-1)


def test_real_persistent_worker_with_large_reservation_parses_without_limit_ratchet(tmp_path):
    parser=tmp_path/'reserved_parser.py'
    parser.write_text('''import mmap,os,sys
from congress_api.retention.process_resources import virtual_bytes
reservation=mmap.mmap(-1,2<<30)
initialized_vsz=virtual_bytes(os.getpid())
retained=None
calls=0
def parse(body):
 global calls,retained
 calls+=1
 if retained is None:retained=mmap.mmap(-1,8<<20)
 working=bytearray(8<<20)
 working[0]=1
 limits=None
 if sys.platform.startswith('linux'):
  import resource
  limits=list(resource.getrlimit(resource.RLIMIT_AS))
 return dict(pid=os.getpid(),calls=calls,initialized_vsz=initialized_vsz,limits=limits,value=body.decode())
''')
    with ParserWorker('reserved','v1',str(parser)+':parse',timeout_seconds=5,
                      memory_bytes=512<<20,max_input_bytes=1024) as worker:
        first=worker.parse('one',b'first')
        second=worker.parse('two',b'second')
        assert first['status']==second['status']=='completed'
        a,b=first['value'],second['value']
        assert a['pid']==b['pid'] and (a['calls'],b['calls'])==(1,2)
        assert (a['value'],b['value'])==('first','second')
        assert a['initialized_vsz']>=2<<30
        if sys.platform.startswith('linux'):
            assert a['limits']==b['limits'] and a['limits'][0]==a['limits'][1]
            # The baseline also includes protocol initialization after module load.
            assert a['limits'][0]>=a['initialized_vsz']+(512<<20)
