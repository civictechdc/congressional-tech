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

The committee explorer remains at `/dashboard/` until its phase-2 consumers move.
Its six workspaces use the weekly committee publication independently of the document
archive. It retains direct file links, saved-body links, source evidence, filtering,
coverage, witnesses and issues. It no longer opens the retired filename catalog.

Pages builds run the retained explorer checks and the native archive contract before
uploading the static site. Archive releases publish separately through the engine
publisher. The removed `/filenames/` redirect and filename worker are not public routes.
