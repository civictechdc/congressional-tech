"""Draft the cause record for a night the release gate stopped, from that run's own evidence.

Gate 1 needs a cause for every difference it could not explain itself (docs/nightly.md). The
record is a person's statement, so this writes none of its reasoning: it copies the stopped
run's findings into the record's shape, attaches the reason you give, keeps the gate report's
facts as pinned evidence, and pins the record in the publish spec. Read it before committing.

    gh run download <run id> -D /tmp/night
    python -m viewer_publication.cause_record draft --evidence /tmp/night --ticket ct-xxxx \\
        --cause "why these differences are right"
    python -m viewer_publication.cause_record pin        # after editing the record by hand

A link that vanishes, dangles or was never checked cannot be recorded away: the draft is run
through the gate's own verdict (release_gate.verdict) and refused here if it would not pass.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from congress_api.retention.provenance import file_pin
from viewer_publication.release_gate import CORRECTED, group_id, load_causes, verdict

ROOT = Path(__file__).resolve().parents[4]
SPEC = 'model/jobs/publish.json'


def gate_report(evidence):
    """The one gate report under a downloaded evidence folder."""
    found = sorted(Path(evidence).glob('**/release-gate.json'))
    if len(found) != 1:
        raise ValueError(f'Expected one release-gate.json under {evidence}, found {len(found)}')
    return json.loads(found[0].read_text())


def stopped_for(report):
    """Why the publisher would not pass the night by itself, else every reason the gate gave."""
    return report.get('automatic_reasons') or report.get('reasons') or []


def corrections(rule, decision, tickets):
    """One correction per link finding the gate has not proven, in the record's exact shape."""
    proven = {(p['kind'], p['key'], p['live_body']) for p in rule.get('proven_corrections', [])}
    entries = []
    for kind, (prefix, _) in CORRECTED.items():
        for answer in rule.get(prefix + 'changed_answers', []):
            if (kind, answer['key'], answer['live_body']) in proven:
                continue
            bodies = [answer['candidate_body']] if kind == 'link_key' else answer['candidate_bodies']
            entries.append(dict(kind=kind, key=answer['key'], live_body=answer['live_body'],
                                candidate_body=bodies[0] if len(bodies) == 1 else bodies, decision=decision, tickets=tickets))
    return entries


def draft(report, *, cause, tickets, correction=None, root=ROOT):
    """Write the record and its evidence under `root`, pin it, and return the record's path.

    The gate's own verdict decides whether a record can pass this night: if it would still
    refuse, nothing is written and its reasons are the error.
    """
    root = Path(root)
    if not stopped_for(report):
        raise ValueError('The release gate did not stop this run, so it needs no record')
    named = corrections(report['link_rule'], correction, tickets)
    if named and not correction:
        raise ValueError(f'{len(named)} live links would open another file; say why with --correction')
    groups = [dict(id=group_id(g), count=g['count'], disposition='explained', cause=cause, tickets=tickets) for g in report['failing']]
    record = dict(version=1, base_release_id=report['base_release'], candidate_release_id=report['candidate_release'],
                  notes=dict(identifiers=[dict(statement=cause, decision=', '.join(tickets))]),
                  **(dict(corrections=named) if named else {}), groups=groups)
    remaining, _ = verdict(report, record)
    if remaining:
        raise ValueError('No record can pass this night; the release itself is wrong:\n  ' + '\n  '.join(remaining[:10]))
    pair = f"{report['base_release'][:12]}-{report['candidate_release'][:12]}"
    evidence = Path('model/jobs/release-causes/evidence') / f'{pair}.json'
    (root / evidence).parent.mkdir(parents=True, exist_ok=True)
    (root / evidence).write_text(json.dumps(dict(
        version=1, base_release_id=report['base_release'], candidate_release_id=report['candidate_release'],
        stopped_for=stopped_for(report),
        failing_groups=[dict(id=group_id(g), count=g['count'], status=g['status']) for g in report['failing']],
        link_rule={key: value for key, value in report['link_rule'].items() if key.endswith('answers') or isinstance(value, (bool, int))},
    ), indent=1) + '\n')
    for group in groups:
        group['evidence'] = [dict(path=str(evidence), **file_pin(root / evidence))]
    path = Path('model/jobs/release-causes') / f'{pair}.json'
    (root / path).write_text(json.dumps(record, indent=1) + '\n')
    return pin_record(root, path)


def pin_record(root=ROOT, path=None):
    """Pin the record in the publish spec by its current bytes, and read it as the publisher will."""
    root = Path(root)
    spec = json.loads((root / SPEC).read_text())
    if path is None:
        if 'release_causes' not in spec:
            raise ValueError(f'{SPEC} pins no cause record to re-pin')
        path = Path('model/jobs') / spec['release_causes']['path']
    spec['release_causes'] = dict(path=str(Path(path).relative_to('model/jobs')), **file_pin(root / path))
    (root / SPEC).write_text(json.dumps(spec, indent=2) + '\n')
    load_causes(dict(path=str(root / path), **file_pin(root / path)))
    return Path(path)


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    drafting = commands.add_parser('draft', help='write and pin a record from a stopped run\'s evidence')
    drafting.add_argument('--evidence', type=Path, required=True, help='folder from `gh run download <run id>`')
    drafting.add_argument('--cause', required=True, help='why the differences are right, in a sentence or two')
    drafting.add_argument('--ticket', action='append', required=True, help='ticket id; repeat for more')
    drafting.add_argument('--correction', help='why each live link may open its new file (needed when links moved)')
    commands.add_parser('pin', help='re-pin the record after editing it by hand')
    args = parser.parse_args(argv)
    evidence = getattr(args, 'evidence', None) and args.evidence.resolve()
    os.chdir(root)  # a record's evidence pins are paths from the checkout's root
    try:
        if args.command == 'pin':
            print(f'Pinned {pin_record(root)} in {SPEC}.')
            return 0
        report = gate_report(evidence)
        path = draft(report, cause=args.cause, tickets=args.ticket, correction=args.correction, root=root)
    except ValueError as error:
        print(f'cause_record: {error}', file=sys.stderr)
        return 2
    reasons = stopped_for(report)
    print('The night stopped for:', *reasons[:5], *([f'and {len(reasons) - 5} more'] if len(reasons) > 5 else []), sep='\n  ')
    print(f"Wrote {path} with {len(report['failing'])} groups and pinned it in {SPEC}.")
    print('Read it, edit any cause that needs its own words, run `pin` again if you edited, then open a pull request.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
