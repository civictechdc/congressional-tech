"""Interpret retained source checks without inventing observation dates.

A latest failure and an earlier successful observation remain separate facts.
Negative availability requires both an actual observation time and source scope.
"""
import json
from dataclasses import dataclass
from datetime import datetime


def observed_time(raw, now):
    """Accept explicit zoned source times no later than the evaluation time."""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed <= now else None
    except (AttributeError, TypeError, ValueError):
        return None


def live_receipt(record, url, now):
    """Return the last valid retrieval/404 receipt for this exact URL."""
    check = record.get("observation_check") or record.get("last_check") or {}
    if not isinstance(check, dict) or check.get("mode") != "live":
        return None
    for receipt in reversed(check.get("receipts") or []):
        if not isinstance(receipt, dict) or receipt.get("url") != url:
            continue
        expected = {200: "retrieved", 404: "not_found"}.get(receipt.get("status_code"))
        if expected is None or receipt.get("outcome") != expected:
            continue
        observed = observed_time(receipt.get("completed_at"), now)
        if observed is not None:
            return observed, expected
    return None


@dataclass(frozen=True)
class SourceCheck:
    observed_at: datetime | None
    successful: bool
    status_code: int | None
    latest_failed: bool


def source_check(observation, url, now):
    """Interpret a direct witness-source check and its separate latest error."""
    observation = observation if isinstance(observation, dict) else {}
    check = observation.get("observation_check") or observation.get("last_check") or {}
    checked = observed_time(check.get("completed_at"), now) if isinstance(check, dict) and check.get("mode") == "live" and check.get("url") == url else None
    successful = checked is not None and (check.get("status_code"), check.get("outcome")) in ((200, "present"), (404, "not_found"))
    return SourceCheck(checked, successful, check.get("status_code") if isinstance(check, dict) else None,
                       latest_check_failed(observation))


@dataclass(frozen=True)
class CaptionObservation:
    status: str
    positive: bool
    observed_at: datetime | None
    scope: str | None
    suffix: str
    selector: str | None


def caption_observations(provider, kind, receipt, now):
    """Interpret latest/prior receipts or an undated legacy caption index value."""
    checks = [(receipt, '', '/receipt')]
    if isinstance(receipt, dict) and isinstance(receipt.get('last_successful'), dict):
        checks.append((receipt['last_successful'], '|last-successful', '/receipt/last_successful'))
    observations = []
    for check, suffix, selector in checks:
        checked, scope = None, None
        if isinstance(check, dict):
            checked = observed_time(check.get('observed_at'), now)
            raw_scope = check.get('scope')
            if isinstance(raw_scope, dict) and raw_scope:
                scope = json.dumps(raw_scope, sort_keys=True, ensure_ascii=False)
            elif isinstance(raw_scope, str) and raw_scope.strip():
                scope = raw_scope
            reported = check.get('outcome') or check.get('kind')
            positive = reported in ('available', 'manual', 'auto', 'webvtt')
            status = ('error' if reported == 'error' else 'available' if positive else
                      'not_found' if reported in ('none', 'not_found') and checked and scope else 'unknown')
        else:
            positive = isinstance(kind, str) and kind in ({'manual', 'auto'} if provider == 'youtube' else {'webvtt'})
            status = 'available' if positive else 'unknown'
        observations.append(CaptionObservation(status, positive, checked, scope, suffix, selector if isinstance(check, dict) else None))
    return tuple(observations)


def latest_check_failed(record, *, live_only=False):
    """Read the latest error separately from any retained successful check."""
    check = record.get('last_check') if isinstance(record, dict) else None
    return isinstance(check, dict) and check.get('outcome') == 'error' and (not live_only or check.get('mode') == 'live')


def last_successful_caption_check(previous):
    """Select prior caption success for retention after a failed refresh."""
    successful = previous.get('last_successful') if previous.get('outcome') == 'error' else previous
    if successful and successful.get('outcome') in ('available', 'not_found'):
        return {key: value for key, value in successful.items() if key != 'last_successful'}
    return None
