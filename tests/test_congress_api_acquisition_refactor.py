"""Acquisition argument errors must precede credentials and retained-state writes."""

import pytest

from congress_api.acquisition import gpo, house, senate


@pytest.mark.parametrize("nthreads", [0, -1])
def test_gpo_rejects_invalid_worker_count_before_acquisition(tmp_path, monkeypatch, nthreads):
    def unexpected_credentials():
        pytest.fail("Invalid worker count reached credential loading")

    monkeypatch.setattr(gpo, "load_congress_api_key", unexpected_credentials)
    output = tmp_path / "hearings.csv"
    with pytest.raises(ValueError, match="nthreads must be positive"):
        gpo.main(output, nthreads=nthreads)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("reader", [house, senate])
@pytest.mark.parametrize("option", ["refresh_limit", "limit"])
def test_chamber_readers_reject_negative_budgets_before_reading_inputs(tmp_path, reader, option):
    args = dict(meetings=tmp_path / "missing-meetings.gz", state_dir=tmp_path, output_dir=tmp_path)
    if reader is house:
        args["gpo_path"] = tmp_path / "missing-gpo.csv"
    with pytest.raises(ValueError, match=f"{option} must be nonnegative"):
        reader.main(**args, **{option: -1})
    assert not list(tmp_path.iterdir())
