# Congress Explorer 0.6.3

- **Read saved PDFs and hearing transcripts more reliably.** The reader now keeps sending PDF bytes while the decoder starts. This fixes a timeout that could stop a document or transcript before the reader could return a passage and its citation.
- **Page through member ballots with less waiting.** The database now applies the page limit during the sort. In one warmed local check against 10.6 million ballots, the first unfiltered page took 1.7 seconds, down from 4.4 seconds. Ordering, filters, and existing paging cursors are preserved.

Congress Explorer continues to use archive `5d24699ad9fa`. Archive-wide full-text search remains deferred.

**Upcoming archive input.** The team selected one USAID document recovered through ecoi.net for a future archive update. Public availability depends on verifying the attachment and its source explanation and publishing the updated archive.
