"""Parsers: text."""

import html
import re

STOP = set("the a an of and to in on for with from at by is are be as or its it this that hearing hearings "
           "subcommittee committee house u.s. us part examining examine review oversight markup meeting full".split())


def words(s):
    """Keep the substantive words shared by hearing and event title matching."""
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in STOP and len(w) > 2}


def text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()
