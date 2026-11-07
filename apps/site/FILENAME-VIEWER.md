# Document archive and committee explorer

The document archive is served at `/archive/`. `src/components/explorer/archive/ArchiveExplorer.tsx`
uses the archive worker and `reader/archive.ts` to open one immutable engine release.
The release pointer contains `release_id`; the reader refuses legacy viewer pointers.

The archive reader reads Parquet columns and row groups through bounded HTTP ranges.
It uses the release schema registry, checks pinned startup bytes, and loads document
sources and saved copies only when requested. Saved bodies remain in the raw archive.

`npm run test:explorer` checks the archive helpers and the retained committee reader.
`npm run contract:archive-ci` builds hand releases through the engine and checks the
actual browser. The publisher runs the maintained archive contract and canary before
flipping the release pointer. A failure leaves the previous release selected.

`npm run measure:archive` and `npm run targets:archive` maintain the archive measurement
harness and its targets. Device and live-publication gates remain owner-run steps.

Congress Explorer at `/archive/` browses documents, hearings, committees, witnesses,
members, bills, and nominations in the same immutable engine release. It provides direct
file links, saved copies, and source evidence where available. The old `/dashboard/`
route forwards event-ID and filter bookmarks to Congress Explorer. Old record UUID
links show a removal notice and a search link; they do not load a historical ID map.
Its former Coverage and Gaps views have closed. Readers can find source evidence
on individual hearing pages.

Pages builds run the explorer checks and the native archive contract before
uploading the static site. Archive releases publish separately through the engine
publisher. The removed `/filenames/` redirect and filename worker are not public routes.

Pages builds use the workflow's application revision without staging the retired
`pipeline-data/committee-explorer/public` files. The independent
`/youtube-coverage/` report still reads `public/data/youtube/youtube_event_id_report.csv`.
Retained old publications and application revisions remain rollback evidence.
