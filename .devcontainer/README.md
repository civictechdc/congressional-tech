# Development container

The container uses Ubuntu 22.04, Python 3.12, Node 20, Git and the GitHub CLI.
VS Code runs `.devcontainer/post-create.sh` to install the local Python package
graph and npm workspaces. The website is Astro under `apps/site`.

Open the repository in VS Code and choose **Dev Containers: Reopen in Container**.
After setup, `~/.local/bin` contains the installed console scripts. From the
repository root:

```bash
congress-meetings --help
congress-committees --help
house-meeting-records --help
senate-meeting-records --help
meeting-inventory --help
youtube-fetch --help
youtube-analyze --help
```

Help needs no credentials. Actual Congress.gov/GovInfo collection uses
`DATA_GOV_API_KEY`; see the [package credential instructions](../packages/congress_api/README.md#credentials-and-environment).
The production mirror writes native gzip JSONL:

```bash
congress-meetings --output-path output/congress_meetings.jsonl.gz
```

It retains incomplete work for retry. Source readers and inventory use explicit
state/input paths; follow the [weekly source-reader sequence](../docs/youtube-coverage/meeting-state.md)
and [offline requirements](../docs/congress-api-contracts.md#offline-behavior).
`congress-fetch` and `congress-analyze` remain optional **legacy TinyDB exploration**
commands. They are not used by weekly CI and do not replace `congress-meetings`.

For YouTube, the bundled channel table is the default; pass `--tinydb_dir` to
choose cache storage. Use each command's help for credentials and output paths.

If console scripts are missing, rerun the post-create installation. The meeting
mirror also supports `python -m congress_api.meetings --help`; House/Senate reader
and inventory modules are console entry points, not module CLIs.

## Website and navigation

```bash
cd apps/site
npm run dev
# http://localhost:4321/congressional-tech/
```

`ct-root`, `ct-site`, `ct-youtube`, and `ct-inflation` navigate to the repository,
Astro site, committee YouTube app, and inflation app respectively.

## Validation and CI

```bash
python -m pip install -e 'packages/congress_api[test]' -e 'packages/house-naming[test]'
python -m pytest tests packages/committee_meeting/tests packages/house-naming/tests -q
```

GitHub Actions installs Python directly; it does not run collection through this
container. `update-data.yml` collects sources, `publish-explorer.yml` builds and
verifies retained data, and `deploy-pages.yml` deploys the verified publication.
See the [job and artifact inventory](../docs/congress-api-contracts.md#weekly-ci-and-publication).

Container settings live in `devcontainer.json`, OS dependencies in `Dockerfile`,
installation steps in `post-create.sh`, and navigation aliases in `bashrc`.
Rebuild the container after changing its base or features. For missing commands,
check setup output and `~/.local/bin` on `PATH`; for empty reports, check retained
inputs and acquisition receipts before refetching.
