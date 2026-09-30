"""Congress.gov parent committee codes and the aliases used for committee recordings."""


ALIAS = {"jjec00": "jsec00", "hlvc00": "hsgo00", "hlfd00": "hsju00", "hlqj00": "hsju00"}


def native_parent(code):
    """Full-committee systemCode with no recording-channel alias applied."""
    return code[:4] + "00"


def parent_code(code):
    """Parent code for channel/catalog mapping (select committees share a tracked channel)."""
    parent = native_parent(code)
    return ALIAS.get(parent, parent)


def codes_of(meeting):
    """Aliased parent codes for YouTube/Senate channel lookup and cross-source catalog keys."""
    return list(dict.fromkeys(parent_code(c["systemCode"]) for c in meeting.get("committees", [])))


def occupancy_codes_of(meeting):
    """Native parent codes for day-occupancy and uniqueness (aliases must not collide)."""
    return list(dict.fromkeys(native_parent(c["systemCode"]) for c in meeting.get("committees", [])))
