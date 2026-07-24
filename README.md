# Congressional Tech

**Open-source tools for a more transparent Congress.**

A [Civic Tech DC](https://civictechdc.org) initiative, in partnership with the American Governance Institute, building small, practical tools that make congressional data and operations easier to find, track, and understand — for congressional staff and the public alike. Every proposal here started as a real request from people working in and around Congress.

🔗 **Live site: <https://civictechdc.github.io/congressional-tech/>** — browse the project catalog, read the proposals, and explore the committee YouTube coverage dashboard.

## What's in here

This is a [Turborepo](https://turborepo.com) monorepo using npm workspaces, in two layers.

### `apps/` — things you run or deploy

| App | What it is |
| --- | --- |
| **`site`** | The public website (Astro). Project catalog, proposals, and interactive dashboards. Deployed to GitHub Pages. |
| **`committee_youtube`** | CLI tools that scan congressional committee YouTube channels and flag videos missing the official Event ID that links them back to Congress.gov. |
| **`inflation_gsheets`** | Pulls inflation data (BLS CPI + FRED alternative measures) into CSVs that feed a Google Sheets inflation calculator. |

### `packages/` — shared Python libraries the apps build on

| Package | What it provides |
| --- | --- |
| **`congress_shared`** | Auth, config, and reference data shared across the tools. |
| **`congress_api`** | Fetch and analyze committee + event data from Congress.gov. CLIs: `congress-fetch`, `congress-analyze`. |
| **`youtube_api`** | Fetch and analyze committee YouTube data. CLIs: `youtube-fetch`, `youtube-analyze`. |
| **`committee_meeting`** | Committee meeting metadata helpers. |

## The project catalog

The work is grouped into five themes. The site renders 19 proposals (each with a problem and a proposed solution) plus the tools already shipped. The source of truth is plain markdown you can read right here on GitHub: **[`apps/site/src/content/`](apps/site/src/content)**.

| # | Theme |
| --- | --- |
| I | Enhancing Congressional Data Accessibility & Usability |
| II | Workflow Efficiency Tools for Congressional Operations |
| III | Leveraging AI for Content Enhancement & Analysis |
| IV | Predictive & Analytical Tools for Legislative Insight |
| V | Basic Utility Tools |

Two proposals are working tools today: the **Committee YouTube coverage dashboard** (I.2) and the **Google Sheets inflation calculator** (V.1).

## Sub-projects

Two sister tools built by [AgoraDMV](https://github.com/AgoraDMV), forked into this org and kept in sync with upstream daily:

- **[DeltaTrack](https://github.com/civictechdc/DeltaTrack)** — structurally diffs U.S. bill versions from GPO govinfo (added / removed / modified / moved sections), with an account-level old→new money table for appropriations. Local and zero-dependency, built for Hill staffers.
- **[BillTrax](https://github.com/civictechdc/BillTrax)** — a public legislative-intelligence platform: ingests Congress.gov data, structures bill text, tracks funding changes across versions, and adds AI summaries and topic tags.

## Getting started

**Prerequisites:** Node 20+, Python 3.12+, and [`uv`](https://docs.astral.sh/uv/) or `pip`.

### The website

```bash
cd apps/site
npm install
npm run dev      # serves http://localhost:4321/congressional-tech/
npm run build    # static output in dist/
```

Content lives as markdown under `src/content/` (themes, proposals, projects) — add or edit a `.md` file and the site picks it up.

### The Python tools

One editable install pulls the whole package graph:

```bash
pip install -e apps/committee_youtube      # brings in congress_shared, youtube_api, congress_api
# or: uv pip install -e apps/committee_youtube
```

The CLIs are then on your PATH:

```bash
youtube-fetch --help       # needs YOUTUBE_DATA_API_KEY
youtube-analyze --help
congress-fetch --help      # needs a Congress.gov API key
congress-analyze --help
```

Inflation data:

```bash
# BLS CPI index grid -> src/data/historical-cpi.csv
python apps/inflation_gsheets/src/fetch-cpi-convert-csv.py

# BLS + FRED alternative measures (+ optional Adobe/PriceStats) as YoY% -> src/data/inflation-sources.csv
python apps/inflation_gsheets/src/fetch-inflation-sources.py --aggregate
```

### Dev container

The repo ships a [dev container](https://containers.dev/) that installs the Python graph and Node dependencies for you. In VS Code, choose **Reopen in Container**.

## Automation

| Workflow | Cadence | What it does |
| --- | --- | --- |
| `deploy-pages.yml` | on push to `main` | Builds `apps/site` and deploys it to GitHub Pages. |
| `bls-cpi-update.yml` | monthly | Refreshes the CPI baseline and the multi-source inflation table. |
| `update-youtube.yml` | weekly | Refreshes committee YouTube coverage data. |

## Contributing

Come build with us. Pick a proposal from the [catalog](https://civictechdc.github.io/congressional-tech/proposals/), open an issue, or say hello in the [Civic Tech DC](https://civictechdc.org) community. Newcomers welcome.

## License

See [LICENSE](LICENSE).
