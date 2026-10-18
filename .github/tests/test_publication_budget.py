"""Publication byte limits are exclusive; diagnostics retain at most 20 paths."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "publication_budget", Path(__file__).resolve().parents[1] / "scripts/publication-budget.py")
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)


def test_missing_and_empty(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        budget.check(tmp_path / "missing")
    assert budget.check(tmp_path) == (0, 0)
    with pytest.raises(ValueError, match="must stay below 0"):
        budget.check(tmp_path, total_limit=0)


@pytest.mark.parametrize("limit", ["file_limit", "total_limit"])
def test_exact_limit_is_rejected(tmp_path, limit):
    (tmp_path / "data").write_bytes(b"1234")
    assert budget.check(tmp_path, **{limit: 5}) == (1, 4)
    with pytest.raises(ValueError):
        budget.check(tmp_path, **{limit: 4})


def test_total_and_git_exclusion(tmp_path):
    (tmp_path / "one").write_bytes(b"12")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "two").write_bytes(b"345")
    (nested / ".git").mkdir()
    (nested / ".git" / "huge").write_bytes(b"x" * 100)
    (tmp_path / ".git").write_bytes(b"gitdir: ignored")
    assert budget.check(tmp_path, file_limit=4, total_limit=6) == (2, 5)
    with pytest.raises(ValueError, match="uses 5 bytes"):
        budget.check(tmp_path, total_limit=5)


def test_diagnostics_are_bounded(tmp_path):
    for number in range(100):
        (tmp_path / str(number)).write_bytes(b"x")
    with pytest.raises(ValueError) as error:
        budget.check(tmp_path, file_limit=1)
    assert str(error.value).count("(1 bytes)") == 20
