# Provenance and detail work

Pure provenance assembly now lives in `filename-provenance.mjs`. Redirects use
keyed deduplication; exact duplicate pages collapse across page loads, while
competing observations remain separate. URL display grouping still prefers HTTPS;
only exact recorded protocols and unambiguous edges form paths. One reverse
breadth-first pass computes distances to the file; following the first decreasing
edge preserves the previous shortest-path tie order.

The 2,000-edge fixture visits 2,001 vertices and 4,000 edges (including path
selection), reconstructs 2,000 final edges and makes zero partial-path copies.
The previous algorithm copied 1,999,000 existing path entries. It produces 2,000
path-page links and no duplicate uncovered references. Repeating every origin
page leaves these counts unchanged. New unique evidence still causes a complete
origin redraw: it can connect previously disconnected ancestors or change an
unambiguous title into competing titles, so append-only DOM updates would be wrong.
This is measured algorithmic work on a fixture, not a full-browser latency claim.

Detail initialization and release now clear the same per-detail state. Primary
saved/original links are assigned before optional provenance and review work.
Closing a detail invalidates its controller; stale network and clipboard results
cannot change a new source or a closed panel. Full metadata remains an explicit
copy request rather than startup work.

Source history renders at most 20 source buttons instead of the whole group.
The 1,001-source fixture reaches all 51 pages and selects its final source with
the pressed state and role labels intact. Page controls retain usable focus.
Technical search caches at most 2 MiB of formatted text for the current detail:
20 searches over 10 values perform 10 formats and 190 cache hits, versus 200
formats previously. Oversized values remain fully searchable and inspectable;
they are not retained in the formatting cache. Source changes and close release it.

Focused verification covers graph cycles/convergence, ambiguous titles, duplicate
and cross-protocol URLs, ancestor/redirect separation, recovered candidates,
paged-origin failure/retry, large source history, and late clipboard completion.
The existing source/review/technical stale-response and complete-value tests remain
part of the same maintained UI suite.
