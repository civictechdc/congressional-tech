# Congressional-Tech Site Rebuild — Design Spec

**Date:** 2026-07-24
**Repo:** `civictechdc/congressional-tech`
**Status:** Approved design, pre-implementation

## Goal

Replace the current Next.js dashboard (`apps/website`) — visually weak, and it hid
its content inside a build pipeline that rotted — with a new **Astro** site that:

1. Looks like Civic Tech DC: built on the org's **Civic Premium Dark** design system.
2. Puts the **valuable content into markdown** so it is browsable directly on GitHub,
   not locked inside JSON + a JS bundle.
3. Keeps the one genuinely interactive feature — the **Congressional YouTube coverage
   dashboard** — as a client island.

## Non-goals

- No USWDS runtime dependency (we extract the design *tokens*, not the framework).
- No light/dark toggle. Civic Premium Dark is a single committed look (dark anchors,
  light content canvas).
- No CMS. Content is flat markdown in the repo.
- Not touching the other apps (`committee_youtube`, `inflation_gsheets`) or packages.

## Stack & location

- **Astro** (latest, TypeScript), static output. `apps/site/` in the monorepo, built
  alongside `apps/website` until cutover, then the Next app is deleted.
- `astro.config`: `site: 'https://civictechdc.github.io'`, `base: '/congressional-tech'`,
  `output: 'static'`.
- Islands: **React** integration for the one dashboard island only. Every other page is
  static HTML/CSS, zero client JS.
- Fonts: self-hosted **Source Sans Pro** + **Source Code Pro** woff2 via `@font-face`
  (no external font CDN — matches the design system's `--ctdc-font-sans/mono`).

## Design system implementation

Extract the `--ctdc-*` token set from the design-system docs into a single global
stylesheet (`src/styles/tokens.css`) as CSS custom properties, then build components
against the tokens only:

- **Color:** primary blue `#104378`; amber-gold accent `#eec05e`; midnight anchor
  gradient `#0b1a30`→`#061121`; light canvas `#f8f9fa`/`#ffffff`; semi-transparent
  whites for text on dark anchors.
- **Type:** the named ramp `--ctdc-text-2xs` (12px) → `--ctdc-text-4xl` (40px);
  Source Sans Pro everywhere, Source Code Pro for code.
- **Space/radius/shadow/motion:** the documented 4px space grid, radius scale
  (incl. `--ctdc-radius-pill` 20px), ambient shadows, and the single easing curve
  `cubic-bezier(0.16,1,0.3,1)` for every transition.
- **Signature treatments:** dark glass anchors (header/hero/footer) with
  `backdrop-filter: blur`; gold-thread left border on high-importance cards; pill
  buttons; hover lifts (`translateY(-3px)` / link `translateX(4px)` to gold); gold
  focus ring = active-nav underline (focus and "you are here" share the accent).
- Honor `prefers-reduced-motion` with one global guard.

## Content model (markdown)

Astro content collections in `apps/site/src/content/`:

- `themes/` — 5 files (`I`–`V`): frontmatter `{ id, title, order, focus }`.
- `proposals/` — **19 files**, one per proposal: frontmatter
  `{ id, title, theme, status: idea|active|built, effort, repo? }`; body is real
  markdown with `## Problem` and `## Solution` sections.
- `projects/` — active builds (`I.2` YouTube dashboard, `V.1` inflation calc):
  frontmatter + body describing the tool and links (`apps/committee_youtube`,
  `apps/inflation_gsheets`, live URLs).

A one-shot migration script (`scripts/migrate-content.mjs`) converts the existing
`apps/website/src/data/{proposals,project-themes,active-projects}.json` into these md
files faithfully. After migration the JSON is no longer the source of truth; the
markdown is. Browsing `src/content/proposals/` on GitHub shows all 19 proposals as
readable markdown.

## Information architecture (pages)

- `/` — dark glass hero + initiative mission; the 5 themes as gold-thread cards; a strip
  of active projects + related repos (DeltaTrack / BillTrax); contribute CTA.
- `/proposals` — all 19 grouped by theme, filter chips (theme / status), static.
- `/proposals/[id]` — rendered proposal detail (title, status/effort/theme, Problem,
  Solution), static.
- `/projects` — active projects (I.2, V.1) + the two sister repos, with links.
- `/dashboard` — the interactive YouTube-coverage viz (React island, below).
- `/contribute` — how to get involved: GitHub, Slack, devcontainer quick-start.
- Shared dark glass **nav header** (gold active underline) and **footer** (per the
  design-system footer case study: asymmetric columns, hairline dividers, back-to-top
  pill).

## Dashboard island

One React island (`client:visible`) on `/dashboard`:

- Loads `youtube_event_id_report.csv` from `public/data/youtube/` (copied from the
  current app), parses it client-side.
- Filter controls: congress number, chamber, party control.
- Views (ports of the current dashboard): coverage donut (videos with vs. missing
  event IDs), committee leaderboard (by video count / coverage), and a chamber/party
  breakdown.
- **Charts:** rebuilt as lightweight, token-styled inline **SVG** (no recharts) so the
  bundle stays small and the charts match the design system exactly. `congress_metadata.json`
  carries the congress→party/control lookup.

## Deploy & cutover

- New workflow step builds `apps/site` with Astro (`dist/`) and uploads that as the
  Pages artifact; Pages stays on the GitHub Actions source.
- Sequence so the live site never breaks:
  1. Land `apps/site` + content + dashboard; verify a full Astro build in CI (build
     only, no deploy) on the feature branch.
  2. Cutover commit: point `deploy-pages.yml` at `apps/site/dist`, deploy, verify the
     live URL (all routes 200, dashboard loads).
  3. Delete `apps/website` and its now-unused deploy wiring.

## Acceptance criteria

- `apps/site` builds clean with Astro; every route renders.
- All 19 proposals + 5 themes + 2 active projects exist as markdown in
  `src/content/` and render as styled pages.
- `/dashboard` island loads the CSV and renders the filter + charts.
- Site visually reflects Civic Premium Dark (dark anchors, light canvas, gold accent,
  tokened type/space/motion) and passes a basic a11y/contrast + `prefers-reduced-motion`
  check.
- Live Pages URL serves the new site; `apps/website` removed; no broken links.
