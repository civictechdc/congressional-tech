"""Weekly YouTube staging issues the digest of the exact retained bytes once."""
from copy import deepcopy
import gzip
from hashlib import sha256
import json
from unittest.mock import patch

import pytest

from congress_api.retention import weekly_tables as weekly


@pytest.mark.parametrize("upstream", [{"item": {"b": 2, "a": 1}}, ["x", 1], "original text", b"raw bytes", bytearray(b"raw bytes")])
def test_staging_returns_one_hash_for_exact_serialized_bytes(tmp_path, upstream):
    record = {"videoId": "fixture", "publishedAt": "2025-01-04T00:00:00Z", "upstream": upstream}
    expected = (json.dumps(upstream, sort_keys=True).encode() if isinstance(upstream, (dict, list))
                else upstream.encode() if isinstance(upstream, str) else bytes(upstream))
    with patch.object(weekly, "sha256", wraps=weekly.sha256) as hashed:
        result = weekly.youtube_video_to_row("hsii00", record, staging_dir=tmp_path)
    assert hashed.call_count == 1
    assert hashed.call_args.args[0] == expected
    digest = sha256(expected).hexdigest()
    assert result["upstream_sha256"] == digest
    assert gzip.decompress((tmp_path / f"bodies/sha256/{digest[:2]}/{digest}.gz").read_bytes()) == expected


def test_changed_payload_gets_new_identity_and_existing_digest_keeps_behavior(tmp_path):
    record = {"videoId": "fixture", "publishedAt": "2025-01-04T00:00:00Z", "upstream": {"item": [1, 2]}}
    before = deepcopy(record)
    first = weekly.youtube_video_to_row("hsii00", record, staging_dir=tmp_path)
    record["upstream"]["item"] = [1, 3]
    second = weekly.youtube_video_to_row("hsii00", record, staging_dir=tmp_path)
    assert first["upstream_sha256"] != second["upstream_sha256"]
    assert len(list(tmp_path.rglob("*.gz"))) == 2
    assert before["upstream"]["item"] == [1, 2]
    record["upstream_sha256"] = first["upstream_sha256"]
    with patch.object(weekly, "sha256", side_effect=AssertionError("existing digest must not be recalculated")):
        assert weekly.youtube_video_to_row("hsii00", record, staging_dir=tmp_path)["upstream_sha256"] == first["upstream_sha256"]


def test_unstaged_payload_still_hashes_once():
    record = {"videoId": "fixture", "publishedAt": "2025-01-04T00:00:00Z", "upstream": "text"}
    with patch.object(weekly, "sha256", wraps=weekly.sha256) as hashed:
        result = weekly.youtube_video_to_row("hsii00", record)
    assert hashed.call_count == 1
    assert result["upstream_sha256"] == sha256(b"text").hexdigest()
