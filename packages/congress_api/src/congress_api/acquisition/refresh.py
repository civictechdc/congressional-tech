"""Schedule source refreshes by age, publisher revision and parser version.

Check recent meetings weekly, meetings up to two years old every 28 days, and
older meetings annually. A changed source revision is due immediately."""

import datetime as dt


def due(previous, day, version, today):
    if not previous or previous.get("version") != version:
        return True
    ## A late XML revision puts even an old House meeting back on the faster schedule.
    day = max(day[:10], previous.get("xml_update", "")[:10])
    age = (today - dt.date.fromisoformat(day)).days
    interval = 7 if age <= 30 else 28 if age <= 730 else 365
    return (today - dt.date.fromisoformat(previous["checked"])).days >= interval
