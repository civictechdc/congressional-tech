"""One exact-byte lost-acknowledgment decision.

Plain callers send one PUT. A matching readback is success. A different body
re-raises the original error. This module does not import the publication client.
"""


def reconcile_lost_acknowledgment(put, read, payload):
    """Send one PUT for a plain exact-byte client and reconcile a lost acknowledgment.

    ``put`` and ``read`` take no arguments. ``read`` returns the object body.
    Returns True when ``put`` fails and that body equals ``payload``. Returns
    False when ``put`` completes. A different body re-raises the original error.
    This function does not send a second PUT. Guarded publication clients keep
    their own write path and must not call it.
    """
    try:
        put()
    except Exception as request_error:
        try:
            actual = read()
        except Exception as reconciliation_error:
            failure = RuntimeError('Write and reconciliation failed; outcome is uncertain; no request was resent')
            failure.request_error = request_error
            failure.reconciliation_error = reconciliation_error
            failure.add_note('Original request failure type: ' + type(request_error).__name__)
            failure.add_note('Reconciliation failure type: ' + type(reconciliation_error).__name__)
            raise failure from request_error
        if actual != payload:
            raise
        return True
    return False
