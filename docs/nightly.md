# The nightly, on one page

**On a normal day you do nothing.** The archive captures, builds, checks itself and publishes in
GitHub Actions. If something needs you, an issue labelled `ci-failure` opens and links here. No
issue means the night went through.

## What runs

| Step | Workflow | When (UTC) | Takes |
|---|---|---|---|
| Capture new source pages into raw storage | `capture-archive.yml` | scheduled 03:23; GitHub starts it between 10:40 and 12:10 | about 25 min |
| Ingest, build, check, publish, flip the live pointer | `archive-jobs.yml` (`publish`) | right after the capture, whatever its result | about 30 min |
| Confirm the hosted MCP serves the new release | last step of the publish job | | under 5 min |
| Open or close alert issues; flag a nightly over 30 hours old | `ci-alerts.yml` | after each run, and 14:37 | seconds |

Both production workflows check out the newest commit of main whose push validation passed, so
an untested commit never runs against production. Changes reach main through pull requests.

A stopped night publishes nothing: the live release stays exactly as it was. Raw captures are
kept either way, and the next night picks up everything that waited.

## When an issue opens

Open the run the issue links, then the failed step's log. The last lines say why.

| What you see | What it means | What to do |
|---|---|---|
| **Capture archive sources** failed | A source site or storage refused a request. Receipts already saved are kept. | Nothing, usually: the publish still runs on what was saved, and tomorrow's capture closes the issue. To retry now: `gh run rerun <run id> --failed`. |
| Publish log line starts `data-only night: the candidate differs from the live release in …` | A merged change altered the model's definition (its pull request carried a "definition change" notice). The night waits for a person to say the differences are intended. | [Write a cause record](#writing-a-cause-record). |
| Publish log line starts `data-only night:` with anything else (rows removed, more change than the new receipts explain, a live link that would open another file) | The data moved in a way the publisher will not accept by itself. | Read the listed reasons. Right: [write a cause record](#writing-a-cause-record). Wrong: leave it stopped and file a ticket; nothing was published. |
| `link rule:` … `vanish`, `not published keys`, `not checked` | The candidate would break links the live release serves. No record can pass this. | A code or data fault. File a ticket; the live release keeps serving. |
| `producer proof:` | A lake table's history does not trace to committed code, usually because something wrote to it outside the nightly. | File a ticket with the line. Do not write to production tables by hand (below). |
| `ReadTimeout`, `503`, `SlowDown`, a runner that vanished | Storage or GitHub hiccup. | `gh run rerun <run id> --failed`. |
| **Confirm the hosted MCP serves the selected release** failed | The release is live and correct; the MCP has not picked it up. | Re-run that job. Still failing: `curl https://congress-explorer-mcp.mdeeb.workers.dev/ready`, and redeploy `apps/explorer_mcp/cloudflare`. |
| **Nightly archive is stale** | No capture or publish finished in 30 hours. | Check both workflows are enabled in the Actions tab and the two switches below. Start one: `gh workflow run capture-archive.yml --ref main`. |

Each issue closes itself on the next successful run.

## Writing a cause record

The one manual step. A cause record is your signed statement that a night's differences are
right; the publisher reads it on the next run and publishes. The tool copies the stopped run's
findings into the record's shape and refuses a night no record could pass.

```
gh run download <run id> -D /tmp/night
.venv/bin/python -m viewer_publication.cause_record draft --evidence /tmp/night \
    --ticket ct-xxxx --cause "why these differences are right"
```

Add `--correction "why each live link may open its new file"` if it asks. Read the record it
wrote under `model/jobs/release-causes/`; if you edit it, run `… cause_record pin`. Open a pull
request with the record, its evidence file and `model/jobs/publish.json` and merge it once green.
Production only runs a commit main has validated, so wait for main's own validation of the merge
(about 20 minutes), then `gh workflow run archive-jobs.yml -f operation=publish --ref main`.

The record names one pair of releases. If new captures arrive before the re-run, the candidate
changes and the record no longer matches: draft it again from the newer run.

## Switches

Repository variables, under Settings → Secrets and variables → Actions:

- `ARCHIVE_CAPTURE_ENABLED`: `true` lets the capture run. Anything else pauses it.
- `ARCHIVE_NIGHTLY_DISABLED`: `true` pauses the publish. The capture keeps saving.

## Rules that keep it boring

- Merge nothing to main while a capture or publish is running (`gh run list --limit 5`).
- A pull request that changes the model's definition says so in its checks. Expect the next
  night to stop for a cause record, and merge it when you have time to write one.
- Do not write to production lake tables from a laptop. `archive-jobs.yml -f operation=backfill`
  is the path that waits its turn behind the nightly.
- Do not loosen a gate to get tonight's release out. Write the record; change the gate in its
  own pull request with its reason.

## Where things are

- Each run's evidence: the `archive-publish-evidence-<run>-<attempt>` artifact. `release-gate.json`
  is every difference from the live release; `data-only-night.json` is what the publisher
  accepted without a person.
- How the gates decide: [docs/releases/README.md](releases/README.md).
- The live release: the pointer the `ARCHIVE_POINTER_URL` variable names.
