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


_PDF_TEXT_FOLD_TABLE = str.maketrans({
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
    "\u2010": "-",
    "\u2011": "-",
})


def fold_pdf_text(value: str) -> str:
    """Fold Unicode FB00-FB06 typographic ligatures and U+2010/U+2011 hyphens to ASCII.

    Preserves em-dashes (U+2014), en-dashes (U+2013), fractions, superscripts, and
    legal symbols untouched so downstream regexes match without destructive NFKC folding.
    """
    if not isinstance(value, str) or not value:
        return ""
    return value.translate(_PDF_TEXT_FOLD_TABLE)



