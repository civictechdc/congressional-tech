"""Judge carried witness keys and witness_key_map against raw Congress.gov JSON and MODS XML (ct-46f3).

    witness_carry_raw_check.py --before DIR --after DIR [--mirror DIR] [--plant] --output OUT.json

Reads --before and --after witness releases directly (witnesses.parquet and witness_key_map.parquet)
and, when --mirror is supplied, walks raw Congress.gov JSON receipt lines and raw MODS XML bodies by
record_sha + 1-based source_locator (never importing repository parsers or model definitions).

Checks in both directions by raw text equality and independent identity tokens:
  1. Zero lost keys:
     - every before/witnesses.parquet witness_key is either published in after/witnesses.parquet or
       present as old_key in after/witness_key_map.parquet whose target(s) exist in after/witnesses.parquet;
     - every before/witness_key_map.parquet old_key is either republished in after/witnesses.parquet
       or carried in after/witness_key_map.parquet with valid target(s) (1-hop carry; no changed targets
       except hopped targets when the prior target itself moved).
  2. No swapped keys:
     - every witness_key carried from before to after must belong to the same publisher source and
       must agree on raw entry text (or raw family/given identity when only non-name formatting moved),
       never moving to a different witness on the occasion.
  3. Unchanged raw entry never re-keyed:
     - any before witness whose witness_key left after/witnesses.parquet is checked against raw entries
       on the same (source, occasion/package_id) in after: if an after row has identical raw entry text
       (raw JSON witness object for congress_gov, raw <witness> line for mods, or identical raw fields
       when raw bytes are not mirrored) with unambiguous 1-to-1 rank, re-keying it is flagged as
       unchanged_entry_rekeyed.

With --plant, mutates copies in memory for all 3 required plants:
  (a) swapped_keys: two witnesses on the same occasion swap witness_key;
  (b) dropped_map_row: a row in after/witness_key_map.parquet is dropped leaving a key lost;
  (c) unchanged_entry_rekeyed: an unchanged carried witness is given a new key + map row without raw change.
"""
import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

MODS_NS = '{http://www.loc.gov/mods/v3}'
LOCATOR_IDX = re.compile(r'witness\[(\d+)\]')
HONORIFICS = {
    'mr', 'mrs', 'ms', 'miss', 'dr', 'hon', 'honorable', 'the', 'rev', 'reverend',
    'sen', 'senator', 'rep', 'representative', 'gen', 'general', 'adm', 'admiral',
    'col', 'colonel', 'lt', 'maj', 'capt', 'captain', 'prof', 'professor', 'esq',
    'phd', 'md', 'jr', 'sr', 'ii', 'iii', 'iv',
}


def _hex(val):
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        return val.hex()
    return str(val).lower()


def _ws(text):
    return ' '.join(str(text or '').split())


def _alpha_words(text):
    folded = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode('ascii').lower()
    return [w for w in re.findall(r'[a-z0-9]+', folded) if w not in HONORIFICS]


def _find_events(obj):
    out = []
    if isinstance(obj, dict):
        if obj.get('eventId') is not None and 'witnesses' in obj:
            out.append(obj)
        for v in obj.values():
            out.extend(_find_events(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_find_events(item))
    return out


class RawEntryStore:
    """Indexes raw Congress.gov JSON witness entries and raw MODS <witness> lines by record_sha."""

    def __init__(self, mirror_dir=None, wanted_shas=None, bodies_dirs=None):
        self.mirror = Path(mirror_dir) if mirror_dir else None
        self.bodies_dirs = [Path(d) for d in (bodies_dirs or []) if Path(d).is_dir()]
        if self.mirror and (self.mirror / 'bodies/sha256').is_dir() and (self.mirror / 'bodies/sha256') not in self.bodies_dirs:
            self.bodies_dirs.append(self.mirror / 'bodies/sha256')
        self.cg_lines = {}
        self.mods_cache = {}
        if self.mirror and self.mirror.is_dir():
            receipts_dir = self.mirror / 'receipts/congress/meetings'
            if receipts_dir.is_dir():
                for path in sorted(receipts_dir.rglob('*')):
                    if not path.is_file() or path.name.endswith('.qualification.json'):
                        continue
                    with path.open('rb') as raw_fh:
                        magic = raw_fh.read(2)
                    open_fn = (lambda p=path: gzip.open(p, 'rb')) if (path.suffix == '.gz' or magic == b'\x1f\x8b') else (lambda p=path: p.open('rb'))
                    try:
                        with open_fn() as fh:
                            for raw_line in fh:
                                line = raw_line.rstrip(b'\r\n')
                                if not line.strip():
                                    continue
                                digest = sha256(line).hexdigest()
                                if wanted_shas is None or digest in wanted_shas:
                                    self.cg_lines.setdefault(digest, line)
                    except OSError:
                        continue

    def _local_body(self, sha):
        if not sha:
            return None
        for bdir in self.bodies_dirs:
            for suffix in ('.gz', '.json.gz', '.xml.gz', '.html.gz', ''):
                p = bdir / sha[:2] / (sha + suffix)
                if p.is_file():
                    raw = p.read_bytes()
                    if suffix.endswith('.gz') or raw[:2] == b'\x1f\x8b':
                        try:
                            return gzip.decompress(raw)
                        except OSError:
                            return None
                    return raw
        return None

    def raw_entry(self, row):
        """Return (from_raw_bytes: bool, exact_raw_text: str) for a witness row."""
        sha = _hex(row.get('record_sha'))
        loc = str(row.get('source_locator') or '')
        m = LOCATOR_IDX.search(loc)
        idx = int(m.group(1)) - 1 if m and int(m.group(1)) >= 1 else None
        src = row.get('source')

        if src == 'congress_gov' and sha and idx is not None:
            raw_line = self.cg_lines.get(sha) or self._local_body(sha)
            if raw_line is not None:
                try:
                    env = json.loads(raw_line)
                    ev_id = str(row.get('event_id') or '')
                    if not ev_id and str(row.get('occasion') or '').startswith('meeting:'):
                        ev_id = str(row['occasion']).split(':', 1)[1]
                    events = _find_events(env)
                    ev = next((e for e in events if str(e.get('eventId') or '') == ev_id), events[0] if events else None)
                    if ev and isinstance(ev.get('witnesses'), list) and 0 <= idx < len(ev['witnesses']):
                        w = ev['witnesses'][idx]
                        raw_str = json.dumps(
                            {k: _ws(w.get(k)) for k in ('name', 'firstName', 'middleName', 'lastName', 'suffix', 'position', 'title', 'organization') if w.get(k)},
                            sort_keys=True,
                            ensure_ascii=False,
                        )
                        return True, raw_str
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass

        if src == 'mods' and sha and idx is not None:
            if sha not in self.mods_cache:
                body = self._local_body(sha)
                if body is not None:
                    try:
                        root = ET.fromstring(body)
                        self.mods_cache[sha] = [_ws(e.text) for e in root.iter(MODS_NS + 'witness')]
                    except ET.ParseError:
                        self.mods_cache[sha] = None
                else:
                    self.mods_cache[sha] = None
            lines = self.mods_cache[sha]
            if lines is not None and 0 <= idx < len(lines):
                return True, lines[idx]

        # Fallback raw-field tuple when mirror does not hold the historical body locally
        fallback = json.dumps(
            [_ws(row.get('name')), _ws(row.get('organization')), _ws(row.get('position'))],
            ensure_ascii=False,
        )
        return False, fallback


def _same_witness_identity(before_row, after_row, before_raw, after_raw):
    """True when carried key refers to the same witness entry (never a swapped witness)."""
    if before_raw == after_raw:
        return True
    if _hex(before_row.get('record_sha')) == _hex(after_row.get('record_sha')) and before_row.get('source_locator') == after_row.get('source_locator'):
        return True
    bn = _alpha_words(before_row.get('name'))
    an = _alpha_words(after_row.get('name'))
    if len(bn) >= 2 and len(an) >= 2:
        same_family = bn[-1] == an[-1] or bn[-1] in an[-2:] or an[-1] in bn[-2:]
        compat_given = bn[0] == an[0] or bn[0][0] == an[0][0] or bool(set(bn[:-1]) & set(an[:-1]))
        return same_family and compat_given
    if bn or an:
        return bn == an
    bo = _alpha_words(before_row.get('organization'))
    ao = _alpha_words(after_row.get('organization'))
    return bool(bo and ao and bo == ao)


def evaluate(before_witnesses, before_map, after_witnesses, after_map, raw_store, *, max_flags=100):
    flags = []
    counts = Counter()
    unread_raw_records = []
    has_raw_sources = bool(raw_store.mirror or raw_store.bodies_dirs)

    before_by_key = {r['witness_key']: r for r in before_witnesses}
    after_by_key = {r['witness_key']: r for r in after_witnesses}
    before_map_by_old = {r['old_key']: r for r in before_map}
    after_map_by_old = {r['old_key']: r for r in after_map}

    # Precompute raw texts
    before_raw = {}
    after_raw = {}
    for wk, r in sorted(before_by_key.items()):
        from_bytes, txt = raw_store.raw_entry(r)
        before_raw[wk] = txt
        if from_bytes:
            counts['before_raw_bytes_read'] += 1
        elif r.get('source') in ('congress_gov', 'mods') and has_raw_sources:
            counts['before_unread_raw_rows'] += 1
            unread_raw_records.append({'side': 'before', 'witness_key': wk, 'source': r.get('source'), 'record_sha': _hex(r.get('record_sha'))})
        else:
            counts['before_non_targeted_source_rows'] += 1
    for wk, r in sorted(after_by_key.items()):
        from_bytes, txt = raw_store.raw_entry(r)
        after_raw[wk] = txt
        if from_bytes:
            counts['after_raw_bytes_read'] += 1
        elif r.get('source') in ('congress_gov', 'mods') and has_raw_sources:
            counts['after_unread_raw_rows'] += 1
            unread_raw_records.append({'side': 'after', 'witness_key': wk, 'source': r.get('source'), 'record_sha': _hex(r.get('record_sha'))})
        else:
            counts['after_non_targeted_source_rows'] += 1

    # 1a. Every prior witness_key must be carried or mapped to live after key(s)
    for wk, b_row in sorted(before_by_key.items()):
        if wk in after_by_key:
            counts['carried_witness_keys'] += 1
            continue
        m_row = after_map_by_old.get(wk)
        if m_row is None:
            flags.append({'kind': 'lost_witness_key', 'witness_key': wk, 'source': b_row.get('source'), 'name': b_row.get('name')})
            continue
        counts['newly_mapped_witness_keys'] += 1
        status = m_row.get('status')
        if status == 'unambiguous':
            target = m_row.get('witness_key')
            if not target or target not in after_by_key:
                flags.append({'kind': 'dangling_map_target', 'old_key': wk, 'target': target})
        elif status == 'ambiguous':
            cands = m_row.get('candidate_keys') or []
            if not cands or any(c not in after_by_key for c in cands):
                flags.append({'kind': 'dangling_ambiguous_candidates', 'old_key': wk, 'candidates': list(cands)})

    # 1b. Every prior map old_key must be carried (1-hop resolved if its target moved) or republished
    for old_k, bm in sorted(before_map_by_old.items()):
        if old_k in after_by_key:
            counts['republished_map_keys'] += 1
            continue
        am = after_map_by_old.get(old_k)
        if am is None:
            flags.append({'kind': 'dropped_map_row', 'old_key': old_k, 'prior_status': bm.get('status')})
            continue
        counts['carried_map_rows'] += 1
        if bm.get('status') == 'unambiguous' and bm.get('witness_key') in after_by_key:
            if am.get('witness_key') != bm.get('witness_key'):
                flags.append({
                    'kind': 'changed_map_target',
                    'old_key': old_k,
                    'before_target': bm.get('witness_key'),
                    'after_target': am.get('witness_key'),
                })
        if am.get('status') == 'unambiguous' and am.get('witness_key') not in after_by_key:
            flags.append({'kind': 'dangling_map_target', 'old_key': old_k, 'target': am.get('witness_key')})

    # 2. Carried keys must never swap identities
    for wk in sorted(before_by_key.keys() & after_by_key.keys()):
        b_row, a_row = before_by_key[wk], after_by_key[wk]
        if b_row.get('source') != a_row.get('source'):
            flags.append({
                'kind': 'swapped_witness_key',
                'witness_key': wk,
                'why': 'source_changed',
                'before_source': b_row.get('source'),
                'after_source': a_row.get('source'),
            })
            continue
        if not _same_witness_identity(b_row, a_row, before_raw[wk], after_raw[wk]):
            flags.append({
                'kind': 'swapped_witness_key',
                'witness_key': wk,
                'why': 'identity_mismatch',
                'before_name': b_row.get('name'),
                'after_name': a_row.get('name'),
                'before_raw': before_raw[wk],
                'after_raw': after_raw[wk],
            })

    # 3. Unchanged raw entry on the same (source, scope) must keep its prior witness_key (never re-keyed)
    def _scope(r):
        return (r.get('source'), r.get('occasion') or '', r.get('package_id') or '')

    before_by_scope_raw = defaultdict(list)
    for wk, r in before_by_key.items():
        before_by_scope_raw[(_scope(r), before_raw[wk])].append(wk)

    after_by_scope_raw = defaultdict(list)
    for wk, r in after_by_key.items():
        after_by_scope_raw[(_scope(r), after_raw[wk])].append(wk)

    for wk, b_row in sorted(before_by_key.items()):
        if wk in after_by_key:
            continue
        bucket_key = (_scope(b_row), before_raw[wk])
        b_peers = before_by_scope_raw[bucket_key]
        a_peers = after_by_scope_raw.get(bucket_key, [])
        if len(b_peers) == 1 and len(a_peers) == 1 and a_peers[0] != wk:
            flags.append({
                'kind': 'unchanged_entry_rekeyed',
                'old_key': wk,
                'new_key': a_peers[0],
                'source': b_row.get('source'),
                'occasion': b_row.get('occasion'),
                'raw_text': before_raw[wk],
            })

    return {
        'counts': dict(counts),
        'unread_raw_records': unread_raw_records,
        'flag_count': len(flags),
        'flags_by_kind': dict(Counter(f['kind'] for f in flags)),
        'flags': flags if max_flags is None else flags[:max_flags],
    }


def run_plants(before_witnesses, before_map, after_witnesses, after_map, raw_store):
    """Run all 3 required ct-46f3 plants: swapped_keys, dropped_map_row, unchanged_entry_rekeyed."""
    results = {}
    carried = {r['witness_key'] for r in before_witnesses} & {r['witness_key'] for r in after_witnesses}

    # Plant 1: swap witness_key on two carried witnesses from the same occasion with distinct names
    by_occ = defaultdict(list)
    for r in after_witnesses:
        if r['witness_key'] in carried and r.get('occasion'):
            by_occ[(r.get('source'), r['occasion'])].append(r)
    swap_pair = None
    for rows in by_occ.values():
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                if set(_alpha_words(rows[i].get('name'))) and set(_alpha_words(rows[j].get('name'))):
                    if not (set(_alpha_words(rows[i].get('name'))) & set(_alpha_words(rows[j].get('name')))):
                        swap_pair = (rows[i]['witness_key'], rows[j]['witness_key'])
                        break
            if swap_pair:
                break
        if swap_pair:
            break

    if swap_pair:
        k1, k2 = swap_pair
        a_swap = [
            ({**r, 'witness_key': k2} if r['witness_key'] == k1 else ({**r, 'witness_key': k1} if r['witness_key'] == k2 else r))
            for r in after_witnesses
        ]
        res1 = evaluate(before_witnesses, before_map, a_swap, after_map, raw_store, max_flags=None)
        results['swapped_keys'] = {
            'planted_keys': list(swap_pair),
            'caught': any(f['kind'] == 'swapped_witness_key' and f.get('witness_key') in swap_pair for f in res1['flags']),
            'flags_by_kind': res1['flags_by_kind'],
        }
    else:
        results['swapped_keys'] = {'caught': False, 'reason': 'no_eligible_pair'}

    # Plant 2: drop one row from after_map (preferring a key carried from before_map or before_witnesses)
    drop_target = next(
        (m for m in after_map if m['old_key'] in {x['old_key'] for x in before_map} or m['old_key'] in {x['witness_key'] for x in before_witnesses}),
        after_map[0] if after_map else None,
    )
    if drop_target is not None:
        m_drop = [m for m in after_map if m['old_key'] != drop_target['old_key']]
        res2 = evaluate(before_witnesses, before_map, after_witnesses, m_drop, raw_store, max_flags=None)
        results['dropped_map_row'] = {
            'planted_old_key': drop_target['old_key'],
            'caught': any(
                f['kind'] in ('dropped_map_row', 'lost_witness_key')
                and (f.get('old_key') == drop_target['old_key'] or f.get('witness_key') == drop_target['old_key'])
                for f in res2['flags']
            ),
            'flags_by_kind': res2['flags_by_kind'],
        }
    else:
        results['dropped_map_row'] = {'caught': False, 'reason': 'empty_after_map'}

    # Plant 3: re-key an unchanged carried witness (minting a synthetic key + map row when raw text is identical)
    before_by_k = {r['witness_key']: r for r in before_witnesses}
    after_by_k = {r['witness_key']: r for r in after_witnesses}
    occ_counts = Counter(
        (r.get('source'), r.get('occasion') or '', r.get('package_id') or '', _ws(r.get('name')))
        for r in after_witnesses
    )
    rekey_target = next(
        (wk for wk in sorted(carried)
         if raw_store.raw_entry(before_by_k[wk])[1] == raw_store.raw_entry(after_by_k[wk])[1]
         and (before_by_k[wk].get('source'), before_by_k[wk].get('occasion') or '', before_by_k[wk].get('package_id') or '')
         == (after_by_k[wk].get('source'), after_by_k[wk].get('occasion') or '', after_by_k[wk].get('package_id') or '')
         and occ_counts[(after_by_k[wk].get('source'), after_by_k[wk].get('occasion') or '', after_by_k[wk].get('package_id') or '', _ws(after_by_k[wk].get('name')))] == 1),
        None,
    )
    if rekey_target is not None:
        fake_new_key = 'ffff0000ffff0001'
        a_rekey = [({**r, 'witness_key': fake_new_key} if r['witness_key'] == rekey_target else r) for r in after_witnesses]
        m_rekey = list(after_map) + [{
            'old_key': rekey_target,
            'witness_key': fake_new_key,
            'status': 'unambiguous',
            'basis': 'same_name',
            'candidate_keys': [],
        }]
        res3 = evaluate(before_witnesses, before_map, a_rekey, m_rekey, raw_store, max_flags=None)
        results['unchanged_entry_rekeyed'] = {
            'planted_old_key': rekey_target,
            'caught': any(f['kind'] == 'unchanged_entry_rekeyed' and f.get('old_key') == rekey_target for f in res3['flags']),
            'flags_by_kind': res3['flags_by_kind'],
        }
    else:
        results['unchanged_entry_rekeyed'] = {'caught': False, 'reason': 'no_eligible_carried_row'}

    return results


def _read_parquet_cols(path: Path, wanted_cols: list[str]) -> list[dict]:
    pf = pq.ParquetFile(path)
    present = [c for c in wanted_cols if c in pf.schema_arrow.names]
    return pq.read_table(path, columns=present).to_pylist()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--mirror', type=Path, default=None)
    parser.add_argument('--bodies-dir', type=Path, action='append', default=None)
    parser.add_argument('--plant', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)

    w_cols = ['witness_key', 'source', 'occasion', 'event_id', 'package_id', 'name', 'organization', 'position', 'record_sha', 'source_locator']
    m_cols = ['old_key', 'witness_key', 'status', 'basis', 'candidate_keys']
    before_w = _read_parquet_cols(args.before / 'witnesses.parquet', w_cols)
    before_m = _read_parquet_cols(args.before / 'witness_key_map.parquet', m_cols)
    after_w = _read_parquet_cols(args.after / 'witnesses.parquet', w_cols)
    after_m = _read_parquet_cols(args.after / 'witness_key_map.parquet', m_cols)

    wanted_shas = {_hex(r.get('record_sha')) for r in before_w + after_w if r.get('record_sha') is not None}
    raw_store = RawEntryStore(args.mirror, wanted_shas=wanted_shas, bodies_dirs=args.bodies_dir)

    report = evaluate(before_w, before_m, after_w, after_m, raw_store)
    if args.plant:
        plants = run_plants(before_w, before_m, after_w, after_m, raw_store)
        report['plants'] = plants
        if not all(p.get('caught') for p in plants.values()):
            args.output.write_text(json.dumps(report, indent=2, default=str) + '\n')
            raise SystemExit(f"Planted case was not caught: {plants}")

    args.output.write_text(json.dumps(report, indent=2, default=str) + '\n')
    print(json.dumps({
        'counts': report['counts'],
        'flag_count': report['flag_count'],
        'flags_by_kind': report['flags_by_kind'],
        'plants': report.get('plants'),
    }, default=str))
    return report


if __name__ == '__main__':
    main()
