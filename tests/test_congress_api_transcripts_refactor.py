"""Eastern scheduled times follow actual daylight-saving transitions."""

import pytest

from congress_api.transcripts.context import et_time


@pytest.mark.parametrize(('timestamp', 'expected'), [
    ('2019-12-05T15:00:00Z', '10:00 a.m.'),
    ('2026-03-08T06:59:00Z', '1:59 a.m.'),
    ('2026-03-08T07:00:00Z', '3:00 a.m.'),
    ('2026-03-30T14:00:00Z', '10:00 a.m.'),
    ('2025-11-02T05:59:00Z', '1:59 a.m.'),
    ('2025-11-02T06:00:00Z', '1:00 a.m.'),
    ('2025-11-01T14:00:00Z', '10:00 a.m.'),
    ('2026-03-30T10:00:00-04:00', '10:00 a.m.'),
    ('2026-03-30T14:00:00', ''),
    ('invalid', ''),
])
def test_eastern_scheduled_time(timestamp, expected):
    assert et_time(timestamp) == expected
