"""Congress.gov parent committee codes and the aliases used for committee recordings."""
ALIAS = {"jjec00": "jsec00", "hlvc00": "hsgo00", "hlfd00": "hsju00", "hlqj00": "hsju00"}


def parent_code(code):
    parent = code[:4] + "00"
    return ALIAS.get(parent, parent)


def codes_of(meeting):
    return list(dict.fromkeys(parent_code(c["systemCode"]) for c in meeting.get("committees", [])))
