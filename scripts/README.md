# Scripts

These are the commands you run from the repository root. Shared library code lives in [`packages/corpus_recovery`](../packages/corpus_recovery/README.md) and [`packages/viewer_publication`](../packages/viewer_publication/README.md).

The repository keeps two related stores in Cloudflare R2:

- The **raw archive** holds captured congressional documents and the indexes that list them. Treat those objects as the source record.
- The **filename viewer** is the public lookup of those documents by filename. Its files live under `viewer-publications/` and are built from the archive. The viewer publisher does not rewrite raw archive keys.

Run commands with the locked environment (`uv sync --locked`, then `.venv/bin/python`). Paths below are from the repository root.

## Start here

| If you want to… | Go to |
| --- | --- |
| Check the machine and run the enrolled test lanes | [`dev.py`](#workspace) |
| Search local tk tickets by meaning, keywords or ID | [`ticket-search/`](ticket-search/README.md) |
| See whether a viewer publish can be skipped, or publish the viewer | [`publication/`](publication/README.md) |
| Add recovered committee documents to the archive and then to the viewer | [`corpus_recovery/`](corpus_recovery/README.md) |
| Time a rebuild or measure memory on a local fixture | [`measure/`](measure/README.md) |
| Look up or fetch copies from the Library of Congress Web Harvest | [`webharvest/`](webharvest/README.md) |

## Workspace

These three files stay at the top of `scripts/` because GitHub Actions runs the preflight before `uv sync`. The preflight can import only the Python standard library, so it cannot live in an installed package.

**`dev.py`** checks local prerequisites and runs one enrolled test lane from `test-suites.toml`.

```bash
python scripts/dev.py doctor
python scripts/dev.py prepare-baseline
python scripts/dev.py test production-offline
```

`doctor` reports whether the selected lane can run. `prepare-baseline` fetches one pinned historical parser commit when it is missing, then checks its hash. `inventory` lists test files that are not enrolled in any lane. `test` refuses to treat an unenrolled test as covered.

**`publication_preflight.py`** asks, with only the standard library, whether the public viewer already matches this checkout. A match lets CI skip a long install and rebuild. The answer does not authorize a write. A later publish still prepares its own attempt and checks the current remote object before replacing it.

**`viewer_release_identity.py`** is the shared fingerprint of the files and locked package versions that define one viewer release. Preflight and the publisher both use it so a publish can name the exact source it ran. It is not a command you run on its own.
