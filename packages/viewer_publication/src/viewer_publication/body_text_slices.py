"""Pure UTF-8 page-offset slicing and bounded head/tail window helpers for `body_text`."""
from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
import re
from typing import Any, Final

TAIL_JOINER_SINGLE_PAGE = "\n\n[... middle omitted ...]\n\n"
DOCMETA_V7_WINDOW_SPEC: Final[str] = "p12_clean_plus_p3_bidi_clean_9000"
DOCMETA_V7_WINDOW_MAX_CHARS: Final[int] = 9000

_INVISIBLE_FORMAT_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069\u200e\u200f\ufeff\u00ad]")
_COVER_ROSTER_HINT_RE = re.compile(
    r"\b(?:government publishing office|u\.s\. government printing office|"
    r"printed for the use of|committee on |hearing before|table of contents|contents)\b",
    re.IGNORECASE,
)
_GAVEL_OPENING_RE = re.compile(
    r"\b(?:came to order|met,\s*pursuant|the chair\.|mr\.\s*chairman\.|"
    r"opening statement|thank you for the opportunity)\b",
    re.IGNORECASE,
)


def strip_invisible_format_chars(text: str) -> str:
    """Strip invisible Unicode bidi controls, zero-width marks, BOM, and soft hyphens."""
    return _INVISIBLE_FORMAT_RE.sub("", text) if text else ""


def slice_pages(
    text: str,
    page_offsets: Sequence[int],
    *,
    start_page: int = 0,
    max_pages: int | None = 2,
) -> str:
    """Extract a contiguous page range `[start_page, start_page + max_pages)` in O(slice_bytes)."""
    if start_page < 0:
        raise ValueError("start_page must be >= 0")
    if max_pages is not None and max_pages <= 0:
        return ""
    if not page_offsets:
        return text if start_page == 0 else ""

    encoded = text.encode("utf-8")
    total_bytes = len(encoded)
    n_pages = len(page_offsets)
    if start_page >= n_pages:
        return ""
    start_b = int(page_offsets[start_page])
    if start_b >= total_bytes:
        return ""

    end_page = n_pages if max_pages is None else min(n_pages, start_page + max_pages)
    if end_page >= n_pages:
        end_b = total_bytes
    else:
        raw_next = int(page_offsets[end_page])
        if raw_next > total_bytes:
            end_b = total_bytes
        else:
            end_b = raw_next - 1 if raw_next > start_b and encoded[raw_next - 1 : raw_next] == b"\n" else raw_next
    return encoded[start_b:end_b].decode("utf-8", errors="replace")


def head_tail_window(
    text: str,
    page_offsets: Sequence[int],
    *,
    max_chars: int = 8000,
    head_pages: int = 2,
    tail_chars: int = 2400,
) -> str:
    """Construct a bounded head+tail document window for `DocMeta` and `corpus_quality` consumers.

    - Single-page documents (e.g. long committee HTMLs/WARCs `> max_chars`): preserves both the
      top masthead/headline/opening prose AND the bottom `tail_chars` (signers, dates, colophons).
    - Multi-page documents (PDFs & multi-page WARCs): extracts `p1..p{head_pages}` via UTF-8 byte
      offsets, and when the document has pages beyond `head_pages`, appends the last surviving
      page's tail so letter signers, witness rosters, and GPO colophons at the end of a PDF are
      never lost while keeping total output `<= max_chars`.
    """
    if max_chars <= 0 or not text:
        return ""
    eff_tail = max(0, min(tail_chars, max_chars // 3))

    # Single-page (HTML / XML / 1-page PDF)
    if len(page_offsets) <= 1:
        if len(text) <= max_chars:
            return text
        if eff_tail == 0 or max_chars <= len(TAIL_JOINER_SINGLE_PAGE) + 32:
            return text[:max_chars]
        head_budget = max_chars - eff_tail - len(TAIL_JOINER_SINGLE_PAGE)
        return f"{text[:head_budget]}{TAIL_JOINER_SINGLE_PAGE}{text[-eff_tail:]}"

    # Multi-page (PDF / multi-page WARC)
    head_txt = slice_pages(text, page_offsets, start_page=0, max_pages=head_pages)
    encoded = text.encode("utf-8")
    total_bytes = len(encoded)
    surviving_indices = [i for i, off in enumerate(page_offsets) if 0 <= int(off) < total_bytes]
    if not surviving_indices:
        return text[:max_chars]

    last_idx = surviving_indices[-1]
    if last_idx < head_pages:
        # All surviving pages are already inside head_txt
        if len(head_txt) <= max_chars:
            return head_txt
        if eff_tail == 0 or max_chars <= len(TAIL_JOINER_SINGLE_PAGE) + 32:
            return head_txt[:max_chars]
        head_budget = max_chars - eff_tail - len(TAIL_JOINER_SINGLE_PAGE)
        return f"{head_txt[:head_budget]}{TAIL_JOINER_SINGLE_PAGE}{head_txt[-eff_tail:]}"

    # Extract last surviving page text in O(last_page_bytes) without decoding middle pages
    last_page_txt = slice_pages(text, page_offsets, start_page=last_idx, max_pages=1).strip()
    if not last_page_txt or eff_tail == 0:
        return head_txt[:max_chars]

    last_slice = last_page_txt[-eff_tail:] if len(last_page_txt) > eff_tail else last_page_txt
    marker = f"\n\n[... page {last_idx + 1} tail ...]\n\n"
    if len(head_txt) + len(marker) + len(last_slice) <= max_chars:
        return f"{head_txt}{marker}{last_slice}"
    if max_chars <= len(marker) + 32:
        return head_txt[:max_chars]
    head_budget = max_chars - len(marker) - len(last_slice)
    if head_budget < 64:
        # Shrink tail proportionally on very small max_chars budgets
        last_slice = last_slice[-(max_chars // 4) :]
        head_budget = max(0, max_chars - len(marker) - len(last_slice))
    return f"{head_txt[:head_budget]}{marker}{last_slice}"


def _non_ws_len(text: str) -> int:
    return len(" ".join(text.split()))


def docmeta_v7_window(
    text: str | None,
    page_offsets: Sequence[int] = (),
    *,
    rescued_text: str | None = None,
    rescued_status: str | None = None,
    max_chars: int = DOCMETA_V7_WINDOW_MAX_CHARS,
    head_pages: int = 2,
    tail_chars: int = 2400,
    p3_head_budget: int = 6400,
    p3_slice_budget: int = 2500,
    min_substantive_head_chars: int = 80,
) -> dict[str, Any]:
    """Build the canonical DocMeta V7 `p12_clean_plus_p3_bidi_clean_9000` window.

    Guarantees:
    - Uses `rescued_text` (`ct-o7ew` Apple Vision p1-5 OCR) when `rescued_status == 'ok'`.
    - Strips invisible Unicode bidi/format characters consistently across single/multi-page text.
    - Rescues pages 3..5 (`[... p3 rescue ...]`) when p1..p2 is short or cover/roster boilerplate.
    - Appends the last surviving page's tail ONLY when the head already holds substantial prose
      (`>= min_substantive_head_chars`), preventing blank/stub-head tail-only traps.
    """
    if rescued_status == "ok":
        rescued_clean = strip_invisible_format_chars(rescued_text or "").strip()
        if rescued_clean:
            out = rescued_clean[:max_chars] if max_chars > 0 else ""
            return {
                "text": out,
                "text_window_spec": DOCMETA_V7_WINDOW_SPEC,
                "text_window_sha256": sha256(out.encode("utf-8")).hexdigest(),
                "window_source": "ocr_rescue_p15",
                "p3_rescued": False,
            }

    if text is None:
        return {
            "text": None,
            "text_window_spec": DOCMETA_V7_WINDOW_SPEC,
            "text_window_sha256": None,
            "window_source": "missing",
            "p3_rescued": False,
        }

    cleaned_full = strip_invisible_format_chars(text)
    if max_chars <= 0 or not cleaned_full:
        return {
            "text": "",
            "text_window_spec": DOCMETA_V7_WINDOW_SPEC,
            "text_window_sha256": sha256(b"").hexdigest(),
            "window_source": "body_text_ssot",
            "p3_rescued": False,
        }

    if len(page_offsets) <= 1:
        out = head_tail_window(
            cleaned_full,
            (),
            max_chars=max_chars,
            head_pages=head_pages,
            tail_chars=tail_chars,
        )[:max_chars]
        return {
            "text": out,
            "text_window_spec": DOCMETA_V7_WINDOW_SPEC,
            "text_window_sha256": sha256(out.encode("utf-8")).hexdigest(),
            "window_source": "body_text_ssot",
            "p3_rescued": False,
        }

    total_bytes = len(text.encode("utf-8"))
    surviving_indices = [i for i, off in enumerate(page_offsets) if 0 <= int(off) < total_bytes]
    if not surviving_indices:
        out = cleaned_full[:max_chars]
        return {
            "text": out,
            "text_window_spec": DOCMETA_V7_WINDOW_SPEC,
            "text_window_sha256": sha256(out.encode("utf-8")).hexdigest(),
            "window_source": "body_text_ssot",
            "p3_rescued": False,
        }

    p12_clean = strip_invisible_format_chars(
        slice_pages(text, page_offsets, start_page=0, max_pages=head_pages)
    )
    last_idx = surviving_indices[-1]

    # Rescue pages 3..5 when p1..p2 are short or cover/roster without gavel/opening prose.
    p3_rescued = False
    p3_page_idx: int | None = None
    head = p12_clean
    needs_p3_rescue = last_idx >= head_pages and (
        _non_ws_len(p12_clean) < 600
        or (_COVER_ROSTER_HINT_RE.search(p12_clean) is not None and _GAVEL_OPENING_RE.search(p12_clean) is None)
    )
    if needs_p3_rescue:
        fallback_p3: tuple[int, str] | None = None
        chosen_p3: tuple[int, str] | None = None
        for cand_idx in (i for i in surviving_indices if head_pages <= i < 5):
            cand_txt = strip_invisible_format_chars(
                slice_pages(text, page_offsets, start_page=cand_idx, max_pages=1)
            ).strip()
            if not cand_txt:
                continue
            if fallback_p3 is None:
                fallback_p3 = (cand_idx, cand_txt)
            if _non_ws_len(cand_txt) >= min_substantive_head_chars:
                chosen_p3 = (cand_idx, cand_txt)
                break
        picked = chosen_p3 or fallback_p3
        if picked is not None and picked[1][:40] not in p12_clean:
            p3_page_idx, p3_txt = picked
            marker_p3 = "\n\n[... p3 rescue ...]\n"
            head_cap = max(0, min(p3_head_budget, max_chars - len(marker_p3) - 64))
            p3_prefix = p12_clean[:head_cap].rstrip()
            rem = max(0, max_chars - len(p3_prefix) - len(marker_p3))
            p3_slice = p3_txt[: min(p3_slice_budget, rem)]
            head = f"{p3_prefix}{marker_p3}{p3_slice}" if p3_prefix else f"[... p3 rescue ...]\n{p3_txt[: max(0, max_chars - len('[... p3 rescue ...]\\n'))]}"
            p3_rescued = True

    out = head[:max_chars]
    eff_tail = max(0, min(tail_chars, max_chars // 3))
    if (
        _non_ws_len(head) >= min_substantive_head_chars
        and last_idx >= head_pages
        and last_idx != p3_page_idx
        and eff_tail > 0
    ):
        last_txt = strip_invisible_format_chars(
            slice_pages(text, page_offsets, start_page=last_idx, max_pages=1)
        ).strip()
        if last_txt:
            marker_tail = f"\n\n[... page {last_idx + 1} tail ...]\n\n"
            if p3_rescued:
                avail_tail = max_chars - len(head) - len(marker_tail)
                if avail_tail >= 200:
                    last_slice = last_txt[-min(eff_tail, avail_tail) :]
                    out = f"{head}{marker_tail}{last_slice}"
            elif len(head) + len(marker_tail) + min(len(last_txt), eff_tail) <= max_chars:
                last_slice = last_txt[-eff_tail:] if len(last_txt) > eff_tail else last_txt
                out = f"{head}{marker_tail}{last_slice}"
            elif max_chars > len(marker_tail) + 32:
                last_slice = last_txt[-eff_tail:] if len(last_txt) > eff_tail else last_txt
                head_budget = max_chars - len(marker_tail) - len(last_slice)
                if head_budget < max(64, min_substantive_head_chars):
                    last_slice = last_slice[-(max_chars // 4) :]
                    head_budget = max(0, max_chars - len(marker_tail) - len(last_slice))
                if _non_ws_len(head[:head_budget]) >= min_substantive_head_chars:
                    out = f"{head[:head_budget]}{marker_tail}{last_slice}"

    out = out[:max_chars]
    return {
        "text": out,
        "text_window_spec": DOCMETA_V7_WINDOW_SPEC,
        "text_window_sha256": sha256(out.encode("utf-8")).hexdigest(),
        "window_source": "body_text_ssot",
        "p3_rescued": p3_rescued,
    }
