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
    except Exception:
        if read() != payload:
            raise
        return True
    return False
