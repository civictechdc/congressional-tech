"""Optional progress events; the command chooses how to display and retain them."""
import logging

LOGGER = logging.getLogger(__name__)


def report(stage, *, completed=None, total=None, unit=None):
    LOGGER.info(stage, extra={'progress': {
        'stage': stage, 'completed': completed, 'total': total, 'unit': unit}})


def advance(metric, amount=1):
    LOGGER.info(metric, extra={'counter': (metric, amount)})


def track(items, stage, *, unit, total=None, every=1000):
    """Count work after the caller processes each item, including the final item."""
    if total is None and hasattr(items, '__len__'):
        total = len(items)
    done = 0
    report(stage, completed=done, total=total, unit=unit)
    for item in items:
        yield item
        done += 1
        if done % every == 0:
            report(stage, completed=done, total=total, unit=unit)
    report(stage, completed=done, total=total, unit=unit)
