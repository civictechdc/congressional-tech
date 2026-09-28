"""Recognize former collector defaults without treating them as source values."""

PLACEHOLDER_LABELS = frozenset({
    "Reported edition; revision not established",
    "Reported recording; revision not established",
})


def collector_placeholder_conflict(values):
    """Only the exact old defaults (with an optional final period) qualify."""
    return bool(values) and all(isinstance(value, str) and value.removesuffix(".") in PLACEHOLDER_LABELS for value in values)
