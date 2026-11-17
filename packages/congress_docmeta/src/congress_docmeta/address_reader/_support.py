"""Keeplist helpers the address reader leans on, copied verbatim from keeplist-backend fb1245c2.

Only the functions the four address modules call. Sources: `keeplist_io/external_apis/shared/text.py`,
`keeplist_io/scrape/parsers/utils.py`, `keeplist_io/scrape/utils/text.py`.
"""


from __future__ import annotations

import html
import re
import unicodedata
from typing import Optional


def note_words(text: str) -> list[str]:
    """One fragment as the words to compare it on: punctuation- and case-blind.

    A flat substring test looked right and was not: the model joins a block's
    lines into one sentence, so a paste that reads "tsukemen" and "great broth"
    on two lines comes back as "tsukemen, great broth", and a comma the person
    never typed is not evidence they never said it.

    Falls back to the text's own words when stripping punctuation leaves
    nothing. A line of pure emoji is something the person wrote -- extraction
    keeps it as an addressable row on purpose ("no line vanishes") -- so an
    empty comparison key is a reason to compare on what is actually there,
    never a reason to throw the line away. The two kinds of key cannot collide:
    a fallback key has no word characters in it by construction, and every
    ordinary one has at least one.
    """

    return re.sub(r"[^\w\s]", " ", text.lower()).split() or text.lower().split()


def already_says(words: list[str], said: list[str]) -> bool:
    """Is `words` a run of whole words inside `said`?

    **Whole words, never characters.** Character containment is what read "$20"
    as already-said by "$120" and dropped the cheaper price -- not hidden, gone
    from the wire and from the committed description. ``["20"]`` is simply not
    a word of ``["120"]``, so the accident disappears at this granularity while
    the case the check exists for still lands: the schema asks the model for a
    note that is "the block's other lines", and every one of those lines then
    arrives again as a child of its own. The same granularity is what keeps
    "York" from counting as already said by "New Yorker".
    """

    width = len(words)
    return width <= len(said) and any(said[at : at + width] == words for at in range(len(said) - width + 1))


def nkey(s) -> str:
    """Fold a name down to a comparison key: NFKD, strip combining marks,
    non-alphanumerics -> space, collapse, casefold.

    Unicode-aware (uses str.isalnum() per character, not an ASCII
    [0-9a-zA-Z] class), so letters from non-Latin scripts survive; only
    punctuation, symbols, underscores, and whitespace get folded to a
    single space. An ASCII class here is a defect this codebase has met
    twice: it folded every Japanese address on a page to the same key, and
    "Straße" to "stra e"."""
    s = str(s) if s is not None else ""
    s = unicodedata.normalize("NFKD", s)
    if not s.isascii():  # combining marks only exist outside ASCII
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
    out = []
    prev_space = True  # so leading non-alnum runs don't emit a leading space
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            prev_space = False
        elif not prev_space:
            out.append(" ")
            prev_space = True
    return "".join(out).strip().casefold()


_PLACEHOLDERS = frozenset(
    {"none", "null", "nil", "nan", "n/a", "na", "undefined", "unknown", "not available", "-", "--", "?"}
)


def is_placeholder(value) -> bool:
    """True when a string says nothing while looking like it says something."""
    if not isinstance(value, str):
        return False
    return value.strip().casefold() in _PLACEHOLDERS


_LINK_TEXT_CHAR = r"(?!\n[^\S\n]*\n)[^\[\]]"


_LINK_TEXT_CONTENT = rf"(?:{_LINK_TEXT_CHAR}|\[(?:{_LINK_TEXT_CHAR})*\])*"


_ZERO_WIDTH_CHARS = re.compile("[​﻿]")


def condense_horizontal_whitespace(text: Optional[str]) -> str:
    """
    Condenses multiple consecutive whitespace characters to a single space.

    Zero-width characters are dropped first: no reader sees them, but they
    split whitespace runs and inflate character counts and density metrics.

    Args:
        text: The input string to process

    Returns:
        String with all consecutive whitespace replaced with a single space,
        or an empty string if input is None.
    """
    if not isinstance(text, str):
        return ""  # Return empty string for None or non-string input
    text = _ZERO_WIDTH_CHARS.sub("", text)
    return re.sub(r"[^\S\n]+", " ", text)


def condense_newlines(text: str) -> str:
    """
    Condenses multiple consecutive newline characters to a single newline.

    Args:
        text: The input string to process

    Returns:
        String with all consecutive newlines replaced with a single newline
    """
    return re.sub(r"\s*\n\s*.{0,2}\s*\n\s*", " ", text)


_SCRIPTLIKE_ELEMENTS = re.compile(r"<(script|style|template)\b[^>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE)


_ANY_TAG = re.compile(r"<[^>]+>")


def strip_markup(text: str) -> str:
    """Plain text from a string that may carry HTML.

    The minimal shared primitive behind two callers: the microformat
    HTMLCleaner's ``extract_text_from_html`` (which pre-cleans with bleach
    first) and the canonical projection's per-value text hygiene (which has no
    config and wants no markup at all). Code-bearing elements lose their
    content, every other tag becomes a space, and whitespace normalizes -- so
    one definition of "the text of this HTML" serves both.
    """
    if not text or not isinstance(text, str):
        return ""
    return normalize_whitespace(_ANY_TAG.sub(" ", _SCRIPTLIKE_ELEMENTS.sub(" ", text)))


def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text.

    Args:
        text: The input string to process

    Returns:
        String with normalized whitespace
    """
    text = condense_horizontal_whitespace(text)
    text = condense_newlines(text)
    return text.strip()


def unescape_html_iteratively(text: str, max_passes: int = 2) -> str:
    """Unescape HTML entities, twice by default: scraped text is often double-encoded."""
    for _ in range(max_passes):
        previous, text = text, html.unescape(text)
        if text == previous:
            break
    return text


def load_schema_vocab():
    """Keeplist reads publisher JSON-LD boxes against its schema.org vocabulary file; congressional documents
    carry no such metadata, so that file is not copied and the metadata path says so instead of guessing."""
    raise NotImplementedError("address_reader copies the prose reader only; publisher metadata is not supported")
