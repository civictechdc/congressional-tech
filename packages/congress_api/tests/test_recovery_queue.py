from datetime import datetime, timezone
import pytest
from congress_api.acquisition.recovery_queue import plan_recovery

URL = "https://www.govinfo.gov/content/pkg/CHRG-1.zip"
NOW = datetime(2026, 10, 6, 21, tzinfo=timezone.utc)


def completed(
    outcome="retry_later", when="2026-10-06T20:00:00+00:00", attempts=4, url=URL
):
    return {
        url: dict(
            attempts=attempts,
            latest_state=dict(url=url, outcome=outcome, next_attempt_at=when),
        )
    }


def test_deadline_does_not_consume_cycle_for_unattempted_selection():
    rows = [dict(url=URL), dict(url=URL + "other")]
    result = plan_recovery(rows, [completed()], NOW)
    assert result["due"] == sorted([URL, URL + "other"])
    assert result["cycles"] == {URL: 1}


def test_generation_gets_only_one_additional_cycle():
    assert plan_recovery([dict(url=URL)], [completed()], NOW)["due"] == [URL]
    assert not plan_recovery([dict(url=URL)], [completed(), completed()], NOW)["due"]
    assert not plan_recovery([dict(url=URL)], [completed()], NOW, max_cycles=1)["due"]


@pytest.mark.parametrize(
    "outcome",
    ["saved", "resource_limit", "http_error", "request_failed", "excluded_scope"],
)
def test_terminal_or_other_failure_not_repeated(outcome):
    assert plan_recovery([dict(url=URL)], [completed(outcome)], NOW)["finished"] == [
        URL
    ]


def test_waits_until_publisher_delay_expires():
    future = "2026-10-06T22:00:00+00:00"
    result = plan_recovery([dict(url=URL)], [completed(when=future, attempts=1)], NOW)
    assert not result["due"] and result["waiting"] == [
        dict(url=URL, next_attempt_at=future)
    ]


def test_nonzip_deferrals_do_not_extend_scope():
    url = "https://www.govinfo.gov/app/details/X"
    assert not plan_recovery([dict(url=url)], [completed(url=url)], NOW)["due"]


def test_receipt_budget_violation_refused():
    with pytest.raises(ValueError):
        plan_recovery([dict(url=URL)], [completed(attempts=5)], NOW)
