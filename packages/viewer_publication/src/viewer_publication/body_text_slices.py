"""Pure UTF-8 page-offset slicing and bounded head/tail window helpers for `body_text`."""
from __future__ import annotations

from collections.abc import Sequence

TAIL_JOINER_SINGLE_PAGE = "\n\n[... middle omitted ...]\n\n"


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
