"""Bound complete archive/viewer control documents before JSON admission."""

# These ceilings bound complete control-plane documents, never catalog payloads.
# Recovery status and admission mappings have larger per-source entries; exceeding
# a supported ceiling is an explicit format/capacity decision, not partial proof.
CONTROL_LIMITS = {'manifest': 4 * 1024**2, 'accepted': 16 * 1024**2, 'recovery': 32 * 1024**2}


def bounded_control_read(stream, *, kind='manifest', declared=None, expected=None):
    limit = CONTROL_LIMITS[kind]
    if expected is not None and (type(expected) is not int or not 0 <= expected <= limit):
        raise ValueError('Unsupported ' + kind + ' expected byte length')
    if declared is not None:
        try:
            declared = int(declared)
        except (ValueError, TypeError) as error:
            raise ValueError('Invalid ' + kind + ' declared byte length') from error
        if declared < 0 or declared > limit or (expected is not None and declared != expected):
            raise ValueError('Unsupported ' + kind + ' declared byte length')
    chunks, count = [], 0
    while chunk := stream.read(min(64 * 1024, limit + 1 - count)):
        count += len(chunk)
        if count > limit or (expected is not None and count > expected):
            raise ValueError('Oversized ' + kind + ' control response')
        chunks.append(chunk)
    if (declared is not None and count != declared) or (expected is not None and count != expected):
        raise ValueError('Incomplete ' + kind + ' control response')
    return b''.join(chunks)

