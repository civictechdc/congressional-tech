"""Judge a MODS re-read of witness name fields against the raw lines and other publishers' names (ct-rg34).

    mods_name_fields_raw_check.py --before GEN.parquet --after GEN.parquet --raw-root BODIES
        --people WITNESSES.parquet --output OUT.json [--accept REVIEWED.json] [--plant person-moved|reversed-name]

The re-read under test moves an organization out of a witness name ("American Legion" alone, or before
the person: "Vietnam Veterans of America, Richard F. Weidman, ...") and joins a surname written first to its
given name ("Torres Small, Hon. Xochitl, ..."). ``--before`` and ``--after`` are appearance generations
(appearance_records rows); only ``mods`` rows are read. ``--raw-root`` holds the retained bodies as
``<sha[:2]>/<sha>.gz``; each body's ``<witness>`` lines are read here with ElementTree. ``--people`` is a
published witnesses table: the first and last words of the names the *other* sources state (Congress.gov,
House XML, Senate pages, never MODS) are the given and family names this check knows. The rule reads
organization words, separators and titles; this check reads only which words other publishers use as
people's given and family names, and the raw line's words.

Both directions, per occurrence key (body, locator); every flag fails the check:

- an occurrence or a body on one side only (``added``, ``removed``, ``unpaired_bodies``);
- ``person_moved``: a changed name that opens with a known given name and whose words the new name lacks;
- ``name_not_in_line``: a new name with a word its raw line lacks;
- ``words_lost``: a changed occurrence that loses a word across name, position, organization and
  on_behalf_of (credentials such as "M.D." and titles such as "Hon." may go, as for every witness line);
- ``words_gained``: a changed occurrence that gains a word its raw line lacks;
- ``person_left_in_organization``: a changed occurrence left without a name whose raw line still has a
  later segment opening with a known given name;
- ``reorder_unsupported``: a new name whose words are not in the raw line in that order (a surname joined to
  its given name) and that does not open with a known given name and end with a known family name.

``--accept`` names flagged occurrences a person has read and accepted, each as ``{"body", "locator",
"flag", "reason"}``; they are reported under ``accepted`` instead of failing, and an accepted entry the run
no longer flags fails as ``stale_accept``. Listed for a person to read, without failing: ``unconfirmed`` new
names that open with no known given name; ``residual`` unchanged names that open with no known given name
on a raw line with a later segment that does. Bodies that are missing or do not parse are listed in
``not_read`` and still compared without a line.

``--plant`` writes one wrong value the rule could produce on the after side, and the check must flag it,
accepted or not: ``person-moved`` moves an unchanged person's name into the organization
(``person_moved``); ``reversed-name`` writes a joined name surname first (``reorder_unsupported``).
"""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

FIELDS = ('name', 'position', 'organization', 'on_behalf_of')
TITLES = set('the hon honorable mr mrs ms miss dr prof professor rev reverend senator sen representative rep ambassador '
             'general gen admiral adm colonel col lieutenant lt major maj captain capt sergeant sgt commander brigadier vice rear '
             'master rabbi sister pastor esq'.split())
SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv'}
FLAGS = ('added', 'removed', 'person_moved', 'name_not_in_line', 'words_lost', 'words_gained',
         'person_left_in_organization', 'reorder_unsupported')
PLANTS = {'person-moved': 'person_moved', 'reversed-name': 'reorder_unsupported'}


def words(text):
    return [w for w in re.split(r"[\s,;:()\[\]]+", text or '') if w.strip('.-\'"')]


def plain(word):
    return re.sub(r"[^a-z0-9]", '', word.lower())


def name_words(text):
    """A name's words without titles, suffixes and initials ("Hon. J. Robert Hunter Jr." -> robert hunter)."""
    return [w for w in map(plain, words(text)) if w and w not in TITLES and w not in SUFFIXES and len(w) > 1]


def opening(text):
    found = name_words(text)
    return found[0] if found else None


def known_names(people_path):
    """Given and family names other publishers state; two letters ("us" of "U.S.") are too short to judge."""
    table = pq.read_table(people_path, columns=['source', 'name']).to_pylist()
    names = [name_words(r['name']) for r in table if r['source'] != 'mods' and r['name']]
    given = Counter(n[0] for n in names if len(n) > 1)
    family = Counter(n[-1] for n in names if len(n) > 1)
    keep = lambda counts: {word for word, n in counts.items() if len(word) > 2 and n >= 2}  # noqa: E731
    return keep(given), keep(family)


def credential(word):
    """A credential or a title, which every GPO witness line may shed from its fields."""
    bare = word.strip('.,')
    if plain(bare) in TITLES:
        return True
    return bool(re.fullmatch(r"(?:[A-Za-z]\.?){1,6}", bare)) and (bare.isupper() or '.' in bare)


def generation(path):
    rows = {}
    for row in pq.read_table(path, columns=['source', 'record_sha', 'package_id', 'appearances']).to_pylist():
        if row['source'] == 'mods':
            digest = row['record_sha'].hex() if isinstance(row['record_sha'], bytes) else row['record_sha']
            rows[digest] = (row['package_id'], {a['source_locator']: a for a in row['appearances'] or ()})
    return rows


def raw_lines(raw_root, digest):
    path = Path(raw_root) / digest[:2] / f'{digest}.gz'
    root = ET.fromstring(gzip.decompress(path.read_bytes()))
    return [''.join(el.itertext()) for el in root.iter() if el.tag.rsplit('}', 1)[-1] == 'witness']


def in_order(name, line):
    """Are the name's words in the line, in the name's order and next to each other?"""
    sequence, text = [plain(w) for w in words(name) if plain(w)], [plain(w) for w in words(line) if plain(w)]
    return any(text[i:i + len(sequence)] == sequence for i in range(len(text) - len(sequence) + 1))


def judge(before, after, raw_root, given, family):
    def person(text):
        return opening(text) in given

    out = {key: [] for key in (*FLAGS, 'unconfirmed', 'residual', 'not_read', 'bodies_only_before', 'bodies_only_after')}
    counts = Counter()
    out['bodies_only_before'] = sorted(before.keys() - after.keys())
    out['bodies_only_after'] = sorted(after.keys() - before.keys())
    for digest in sorted(before.keys() & after.keys()):
        package, old = before[digest]
        new = after[digest][1]
        try:
            lines = raw_lines(raw_root, digest)
        except (OSError, ET.ParseError, EOFError) as error:
            # Named, and still compared: with no raw line, any changed name is reported as not in its line.
            out['not_read'].append(dict(body=digest, package=package, error=type(error).__name__))
            lines = []
        counts['bodies'] += 1
        for locator in sorted(old.keys() | new.keys()):
            item = dict(package=package, body=digest, locator=locator)
            if locator not in old or locator not in new:
                out['added' if locator not in old else 'removed'].append(item)
                continue
            counts['occurrences'] += 1
            index = re.match(r"mods:witness\[(\d+)\]", locator)
            line = lines[int(index.group(1)) - 1] if index and int(index.group(1)) <= len(lines) else ''
            a, b = old[locator], new[locator]
            item.update(line=line, before={f: a.get(f) for f in FIELDS}, after={f: b.get(f) for f in FIELDS})
            if all(a.get(f) == b.get(f) for f in FIELDS):
                segments = [s for s in line.split(',')[1:] if s.strip()]
                if a.get('name') and not person(a['name']) and any(person(s) for s in segments):
                    out['residual'].append(item)
                continue
            counts['changed'] += 1
            old_name, new_name = a.get('name'), b.get('name')
            reordered = bool(new_name) and not in_order(new_name, line)
            counts['no_name' if not new_name else 'reordered' if reordered else 'name_read'] += 1
            if old_name and person(old_name) and not set(name_words(old_name)) <= set(name_words(new_name)):
                out['person_moved'].append(item)
            if new_name and not set(map(plain, words(new_name))) <= set(map(plain, words(line))):
                out['name_not_in_line'].append(item)
            if reordered and not (person(new_name) and name_words(new_name)[-1] in family):
                out['reorder_unsupported'].append(item)
            if new_name and not person(new_name):
                out['unconfirmed'].append(item)
            old_words = Counter(plain(w) for f in FIELDS for w in words(a.get(f)) if not credential(w))
            new_words = Counter(plain(w) for f in FIELDS for w in words(b.get(f)) if not credential(w))
            if old_words - new_words:
                out['words_lost'].append(dict(item, words=sorted((old_words - new_words).elements())))
            # A gained word must come from the raw line; a re-read may restore line text the old one dropped.
            gained = Counter(w for w in (new_words - old_words).elements() if w not in {plain(x) for x in words(line)})
            if gained:
                out['words_gained'].append(dict(item, words=sorted(gained.elements())))
            if not new_name and any(person(s) for s in re.split(r'[,;:]', line)[1:]):
                out['person_left_in_organization'].append(item)
    return dict(counts), out


def plant(kind, before, after, given, family):
    """Write one wrong value the rule could produce on the after side."""
    for digest in sorted(before.keys() & after.keys()):
        for locator, a in sorted(before[digest][1].items()):
            b = after[digest][1].get(locator)
            parts = name_words(b.get('name') if b else None)
            if kind == 'person-moved' and b == a and parts and parts[0] in given:
                wrong = dict(b, name=None, organization=', '.join(filter(None, (b['name'], b.get('organization')))))
            elif (kind == 'reversed-name' and b and b != a and len(parts) > 1 and parts[0] in given
                  and parts[-1] in family and parts[-1] not in given):
                given_part, surname = b['name'].rsplit(' ', 1)
                wrong = dict(b, name=f'{surname} {given_part}')
            else:
                continue
            after[digest][1][locator] = wrong
            return dict(kind=kind, body=digest, locator=locator, name=b['name'], planted=wrong['name'])
    raise SystemExit(f'no occurrence to plant {kind} on')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--before', required=True, type=Path)
    parser.add_argument('--after', required=True, type=Path)
    parser.add_argument('--raw-root', required=True, type=Path)
    parser.add_argument('--people', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--accept', type=Path)
    parser.add_argument('--plant', choices=sorted(PLANTS))
    args = parser.parse_args(argv)
    given, family = known_names(args.people)
    before, after = generation(args.before), generation(args.after)
    planted = plant(args.plant, before, after, given, family) if args.plant else None
    counts, out = judge(before, after, args.raw_root, given, family)
    accepts = json.loads(args.accept.read_text()) if args.accept else []
    reviewed = {(a['body'], a['locator'], a['flag']): a for a in accepts}
    out['accepted'], seen = [], set()
    for flag in FLAGS:
        kept = []
        for item in out[flag]:
            key = (item['body'], item['locator'], flag)
            if key in reviewed and not (planted and (item['body'], item['locator']) == (planted['body'], planted['locator'])):
                seen.add(key)
                out['accepted'].append(dict(item, flag=flag, reason=reviewed[key]['reason']))
            else:
                kept.append(item)
        out[flag] = kept
    out['stale_accept'] = [a for key, a in reviewed.items() if key not in seen]
    failed = {flag: len(out[flag]) for flag in (*FLAGS, 'stale_accept') if out[flag]}
    if out['bodies_only_before'] or out['bodies_only_after']:
        failed['unpaired_bodies'] = len(out['bodies_only_before']) + len(out['bodies_only_after'])
    if planted:
        planted['flagged'] = any(i['body'] == planted['body'] and i['locator'] == planted['locator']
                                 for i in out[PLANTS[planted['kind']]])
    result = dict(status='failed' if failed else 'passed', failed=failed, counts=counts, known_given_names=len(given),
                  known_family_names=len(family), sizes={k: len(v) for k, v in out.items()}, planted=planted, **out)
    args.output.write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps(dict(status=result['status'], failed=failed, counts=counts, sizes=result['sizes'], planted=planted)))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
