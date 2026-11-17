#!/usr/bin/env python3
"""Say on a pull request whether it changes what the nightly calls the model definition.

A nightly approves itself only when it was built from the live release's own definition and
pins (viewer_publication/data_only_night.py). A pull request that changes a file in the model
definition hash, or a pin in model/jobs/publish.json, makes the next nightly stop at gate 1
until a cause record is committed. That is intended, and worth knowing before the merge rather
than the morning after. This never fails the job: it writes a warning and a job summary.

    python .github/scripts/definition-change.py --base <base commit>
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def job_pins(root):
    """The committed pins the nightly compares: the model and daily specs and each producer anchor."""
    spec = json.loads((Path(root) / 'model/jobs/publish.json').read_text())
    pins = {name: spec[name]['sha256'] for name in ('model_spec', 'daily') if isinstance(spec.get(name), dict)}
    pins.update({f'producers/{name}': pin['sha256'] for name, pin in sorted(spec.get('producers', {}).items())})
    return pins


def changed(base, head):
    """Names whose value differs between two mappings, sorted."""
    return sorted(name for name in set(base) | set(head) if base.get(name) != head.get(name))


def notice(files, pins):
    """The summary lines for a pull request, or [] when the definition is untouched."""
    if not files and not pins:
        return []
    lines = ['### This pull request changes the nightly\'s model definition', '',
             'The next nightly after it merges will stop at gate 1 until a cause record is committed '
             '(`docs/releases/README.md`). To get the gate report without waiting for the schedule, merge, let '
             'validation pass, then run `gh workflow run archive-jobs.yml -f operation=publish`.', '']
    if files:
        lines += [f'Files in the definition hash ({len(files)}):', *(f'- `{name}`' for name in files[:40])]
        lines += [f'- and {len(files) - 40} more'] if len(files) > 40 else []
    if pins:
        lines += ['', f'Pins in `model/jobs/publish.json` ({len(pins)}):', *(f'- `{name}`' for name in pins)]
    return lines


def compare(base_commit):
    """(definition files, job pins) that differ between the base commit and this checkout."""
    from viewer_publication.archive_model_profile import _definition_hashes
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder) / 'base'
        subprocess.run(['git', 'worktree', 'add', '--quiet', '--detach', str(base), base_commit], cwd=ROOT, check=True)
        try:
            return changed(_definition_hashes(base), _definition_hashes(ROOT)), changed(job_pins(base), job_pins(ROOT))
        finally:
            subprocess.run(['git', 'worktree', 'remove', '--force', str(base)], cwd=ROOT, check=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--base', required=True, help='The pull request\'s base commit, already fetched')
    args = parser.parse_args(argv)
    try:
        files, pins = compare(args.base)
    except Exception as error:  # a notice must never fail the job it annotates
        # The base tree is hashed with this pull request's list of model files, so a pull request
        # that adds one cannot be compared; that is itself a change to the definition.
        print(f'::warning title=Model definition not compared::{type(error).__name__}: {error}. Treat this pull request as '
              'changing the model definition: the next nightly may stop at gate 1 for a cause record.')
        return 0
    lines = notice(files, pins)
    if not lines:
        print('The model definition and job pins are unchanged: this pull request does not stop the nightly.')
        return 0
    print(f'::warning title=Model definition changed::{len(files)} definition files and {len(pins)} job pins differ from the base; '
          'the next nightly will stop at gate 1 for a cause record.')
    print('\n'.join(lines))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as target:
            target.write('\n'.join(lines) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
