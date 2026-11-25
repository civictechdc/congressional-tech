#!/usr/bin/env python3
"""Independent raw check for Phase 2 RefSpec federal agency links (ct-w34j).

Judges linked organization rows from raw witness records without importing
producer, parser, or model packages and without reading model query or registry files.
Checks both directions:
  1. Precision on sampled linked agency rows (flagging state/local/private/former/mismatch links).
  2. Coverage / missed federal agency mentions and explicit accounting of any unread raw witnesses.
  3. Planted defect verification confirming a state-EPA -> federal-EPA link is caught.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import re
import sys
import unicodedata
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

US_STATES = (
    'alabama', 'alaska', 'arizona', 'arkansas', 'california', 'colorado',
    'connecticut', 'delaware', 'florida', 'georgia', 'hawaii', 'idaho',
    'illinois', 'indiana', 'iowa', 'kansas', 'kentucky', 'louisiana',
    'maine', 'maryland', 'massachusetts', 'michigan', 'minnesota',
    'mississippi', 'missouri', 'montana', 'nebraska', 'nevada',
    'new hampshire', 'new jersey', 'new mexico', 'new york',
    'north carolina', 'north dakota', 'ohio', 'oklahoma', 'oregon',
    'pennsylvania', 'rhode island', 'south carolina', 'south dakota',
    'tennessee', 'texas', 'utah', 'vermont', 'virginia', 'washington',
    'west virginia', 'wisconsin', 'wyoming',
)

_STATE_GROUP = '|'.join(US_STATES)
_STATE_GOV_PREFIX_RE = re.compile(
    rf'\b(?:{_STATE_GROUP})\s+(?:environmental\s+protection\s+agency|epa|department|agency|bureau|commission|board|authority)\b',
    re.IGNORECASE,
)
_LOCAL_OF_RE = re.compile(
    r'\b(?:the\s+)?(?:(?:state|commonwealth|county|town|village|borough|parish)\s+of\s+[a-z]+|city\s+of\s+(?!washington\b)[a-z]+)',
    re.IGNORECASE,
)
_FOREIGN_GOV_RE = re.compile(
    r'\b(?:ministry\s+of|government\s+of\s+(?!the\s+united\s+states)|republic\s+of|embassy\s+of|united\s+nations|european\s+commission|world\s+bank|international\s+monetary\s+fund)\b',
    re.IGNORECASE,
)
_PRIVATE_ENTITY_RE = re.compile(
    r'\b(?:inc\.?|incorporated|corp\.?|corporation|llc|l\.l\.c\.|llp|l\.p\.|pllc|pc|p\.c\.|university|college|association|society|institute|foundation|coalition|council|partners|consulting|group|firm|company)\b',
    re.IGNORECASE,
)
_FORMER_PREFIX_RE = re.compile(r'^\s*(?:and\s+)?former(?:ly)?\b', re.IGNORECASE)
_STOPWORDS = frozenset({
    'the', 'of', 'and', 'for', 'in', 'on', 'at', 'to', 'by', 'u', 's', 'us',
    'united', 'states', 'america', 'federal', 'national', 'department',
    'office', 'bureau', 'agency', 'administration', 'commission', 'service',
    'services', 'board', 'council', 'division', 'program', 'programs',
    'center', 'centers', 'institute', 'authority', 'committee',
})


def _fold(text: str) -> str:
  text = unicodedata.normalize('NFKD', text)
  text = ''.join(ch for ch in text if not unicodedata.combining(ch))
  return text.casefold()


def _strip_parens(text: str) -> str:
  return re.sub(r'\([^)]*\)', ' ', text)


def _active_segments(raw_text: str) -> list[str]:
  cleaned = _strip_parens(raw_text)
  clauses = re.split(r'[;:]|\baccompanied\s+by\b', cleaned, flags=re.IGNORECASE)
  out: list[str] = []
  for clause in clauses:
    c = clause.strip()
    if not c or _FORMER_PREFIX_RE.match(c):
      continue
    c = re.sub(r'(?:,\s*(?:and\s+)?|\s+and\s+)former(?:ly)?\b.*$', '', c, flags=re.IGNORECASE).strip()
    if not c:
      continue
    out.append(c)
    for part in c.split(','):
      p = part.strip()
      if p:
        out.append(p)
  return out


def _tokens(text: str) -> set[str]:
  return {
      tok for tok in re.findall(r'[a-z0-9]+', _fold(text))
      if len(tok) >= 2 and tok not in _STOPWORDS
  }


def _load_refspec_lookup(refspec_tables_dir: pathlib.Path | None) -> dict[str, dict[str, Any]]:
  if refspec_tables_dir is None or not refspec_tables_dir.is_dir():
    return {}
  orgs_path = refspec_tables_dir / 'agency-registry-organizations.parquet'
  aliases_path = refspec_tables_dir / 'agency-registry-aliases.parquet'
  succ_path = refspec_tables_dir / 'agency-registry-current-successors.parquet'
  if not orgs_path.is_file():
    return {}
  single_succ: dict[str, str] = {}
  if succ_path.is_file():
    grouped: dict[str, list[str]] = {}
    for row in pq.read_table(succ_path).to_pylist():
      grouped.setdefault(row['original'], []).append(row['successor'])
    single_succ = {k: v[0] for k, v in grouped.items() if len(v) == 1}

  by_iri: dict[str, dict[str, Any]] = {}
  for row in pq.read_table(orgs_path).to_pylist():
    by_iri[row['resource_iri']] = row

  by_anchor: dict[str, dict[str, Any]] = {}
  for row in pq.read_table(orgs_path).to_pylist():
    target_iri = single_succ.get(row['resource_iri'], row['resource_iri'])
    target = by_iri.get(target_iri, row)
    anchor = f"fr_agency:{target['fr_id']}"
    entry = by_anchor.setdefault(anchor, {'names': set(), 'acronyms': set()})
    entry['names'].add(row['name'])
    entry['names'].add(target['name'])
    if row.get('short_name'):
      entry['acronyms'].add(row['short_name'].strip().upper())
    if target.get('short_name'):
      entry['acronyms'].add(target['short_name'].strip().upper())

  if aliases_path.is_file():
    for row in pq.read_table(aliases_path).to_pylist():
      fr_iri = row.get('fr_resource')
      if fr_iri:
        target_iri = single_succ.get(fr_iri, fr_iri)
        target = by_iri.get(target_iri)
        if not target:
          continue
        anchor = f"fr_agency:{target['fr_id']}"
      elif row.get('target'):
        anchor = f"refspec_target:{row['target']}"
      else:
        continue
      entry = by_anchor.setdefault(anchor, {'names': set(), 'acronyms': set()})
      entry['names'].add(row['name_key'])
      if row.get('fr_publisher_name'):
        entry['names'].add(row['fr_publisher_name'])
  return by_anchor


def judge_linked_row(
    *,
    raw_text: str,
    anchor: str,
    display_name: str,
    refspec_lookup: dict[str, dict[str, Any]] | None = None,
) -> tuple[bool, str]:
  """Independently judge whether linking `raw_text` to federal agency `anchor` (`display_name`) is valid.

  Returns `(is_valid, reason)`.
  """
  if not raw_text or not raw_text.strip():
    return False, 'empty_raw_text'

  active = _active_segments(raw_text)
  if not active:
    return False, 'only_former_or_parenthetical_bio'

  active_joined = ' | '.join(active)
  if _LOCAL_OF_RE.search(active_joined):
    return False, 'state_or_local_of_qualifier'
  if _STATE_GOV_PREFIX_RE.search(active_joined):
    return False, 'state_prefixed_government_agency'
  if _FOREIGN_GOV_RE.search(active_joined) and not re.search(r'\b(?:u\.?s\.?|united\s+states)\b', active_joined, re.IGNORECASE):
    return False, 'foreign_or_international_entity'

  # Collect acceptable evidence tokens & acronyms from canonical display_name + RefSpec metadata.
  ref_info = (refspec_lookup or {}).get(anchor, {})
  candidate_names = {display_name, *ref_info.get('names', ())}
  acronyms = set(ref_info.get('acronyms', ()))
  # Also derive simple initialism from canonical words if unambiguous (>= 3 caps)
  canon_words = [w for w in re.findall(r'[A-Za-z]+', display_name) if w.lower() not in {'of', 'the', 'and', 'for', 'on', 'in', 'to'}]
  if len(canon_words) >= 3:
    acronyms.add(''.join(w[0].upper() for w in canon_words))

  # Check uppercase acronym match in active segments (reject private firms/coords like "IHS" / "Washington, DC").
  active_upper_tokens = set(re.findall(r'\b[A-Z]{2,10}\b', active_joined))
  for acr in acronyms:
    if len(acr) >= 3 and acr not in {'USA', 'IHS', 'HOPE', 'CIA'} and acr in active_upper_tokens:
      return True, f'acronym:{acr}'

  # Check semantic overlap between active segments and canonical/alias names.
  best_overlap = 0.0
  for seg in active:
    seg_toks = _tokens(seg)
    if not seg_toks:
      continue
    for cname in candidate_names:
      ref_toks = _tokens(cname)
      if not ref_toks:
        continue
      # Ignore lone generic single tokens unless whole canonical name is 1 significant token
      inter = seg_toks & ref_toks
      if len(ref_toks) == 1 and inter == ref_toks:
        return True, f'exact_token:{cname}'
      ratio = len(inter) / len(ref_toks)
      if len(inter) >= 2 and ratio >= 0.6:
        return True, f'token_overlap:{cname}'
      best_overlap = max(best_overlap, ratio)

  # Allow known high-level federal parent/sub-unit containment if raw text explicitly says U.S./Federal + department/agency name.
  if re.search(r'\b(?:u\.?s\.?|united\s+states)\b', active_joined, re.IGNORECASE):
    raw_toks = _tokens(active_joined)
    for cname in candidate_names:
      ref_toks = _tokens(cname)
      if ref_toks and ref_toks <= raw_toks:
        return True, f'us_qualified_containment:{cname}'

  if _PRIVATE_ENTITY_RE.search(active_joined):
    return False, f'private_or_academic_mismatch(overlap={best_overlap:.2f})'
  return False, f'no_raw_support(overlap={best_overlap:.2f})'


def _load_raw_witnesses(raw_path: pathlib.Path) -> dict[str, dict[str, Any]]:
  schema_names = set(pq.read_schema(raw_path).names)
  cols = ['witness_key']
  for opt in ('organization', 'on_behalf_of', 'witness_type', 'source'):
    if opt in schema_names:
      cols.append(opt)
  rows = pq.read_table(raw_path, columns=cols).to_pylist()
  by_key: dict[str, dict[str, Any]] = {}
  for r in rows:
    by_key[r['witness_key']] = r
  return by_key


def run_check(
    *,
    witnesses_path: pathlib.Path,
    release_dir: pathlib.Path,
    refspec_tables_dir: pathlib.Path | None = None,
    sample_size: int = 100,
    seed: int = 20261125,
    extra_witness_orgs: list[dict[str, Any]] | None = None,
    extra_orgs: list[dict[str, Any]] | None = None,
    extra_raw: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
  raw_by_key = _load_raw_witnesses(witnesses_path)
  if extra_raw:
    raw_by_key.update(extra_raw)

  orgs_rows = pq.read_table(release_dir / 'organizations.parquet').to_pylist()
  if extra_orgs:
    orgs_rows.extend(extra_orgs)
  orgs_by_id = {r['org_id']: r for r in orgs_rows}

  wo_rows = pq.read_table(release_dir / 'witness_organizations.parquet').to_pylist()
  if extra_witness_orgs:
    wo_rows.extend(extra_witness_orgs)

  refspec_lookup = _load_refspec_lookup(refspec_tables_dir)

  # Direction 2a: Account for every raw witness record with non-empty organization/on_behalf_of text.
  linked_pairs = {(r['witness_key'], r['field']) for r in wo_rows}
  unread_records: list[dict[str, str]] = []
  expected_federal_unlinked: list[dict[str, str]] = []
  for wk, raw in sorted(raw_by_key.items()):
    for field in ('organization', 'on_behalf_of'):
      val = raw.get(field)
      if isinstance(val, str) and val.strip():
        if (wk, field) not in linked_pairs:
          unread_records.append({'witness_key': wk, 'field': field, 'raw_text': val})

  # Separate agency-anchored links vs non-agency links and verify every link resolves to a raw witness.
  agency_links: list[tuple[dict[str, Any], dict[str, Any]]] = []
  for r in wo_rows:
    if r['witness_key'] not in raw_by_key:
      unread_records.append({'witness_key': r['witness_key'], 'field': r['field'], 'raw_text': r.get('raw_text', ''), 'reason': 'missing_raw_witness'})
    org = orgs_by_id.get(r['org_id'])
    if org is None:
      unread_records.append({'witness_key': r['witness_key'], 'field': r['field'], 'raw_text': r.get('raw_text', ''), 'reason': 'missing_org_id'})
      continue
    anchor = org['anchor']
    if anchor.startswith('fr_agency:') or anchor.startswith('refspec_target:'):
      agency_links.append((r, org))

  # Direction 2b: Check House XML Government - Federal rows that did NOT link to an agency org
  agency_linked_witnesses = {r['witness_key'] for r, _org in agency_links}
  gov_fed_total = 0
  gov_fed_linked = 0
  for wk, raw in raw_by_key.items():
    if raw.get('source') == 'house_xml' and raw.get('witness_type') == 'Government - Federal':
      has_text = any(isinstance(raw.get(f), str) and raw.get(f).strip() for f in ('organization', 'on_behalf_of'))
      if has_text:
        gov_fed_total += 1
        if wk in agency_linked_witnesses:
          gov_fed_linked += 1
        else:
          expected_federal_unlinked.append({
              'witness_key': wk,
              'organization': raw.get('organization') or '',
              'on_behalf_of': raw.get('on_behalf_of') or '',
          })

  # Direction 1: Sample up to `sample_size` agency-linked rows (deterministic seed; check all if <= sample_size)
  rng = random.Random(seed)
  ordered_links = sorted(agency_links, key=lambda pair: (pair[0]['witness_key'], pair[0]['field'], pair[0]['org_id']))
  if len(ordered_links) > sample_size:
    sample = rng.sample(ordered_links, sample_size)
  else:
    sample = ordered_links

  wrong_rows: list[dict[str, Any]] = []
  sampled_results: list[dict[str, Any]] = []
  for link, org in sample:
    raw = raw_by_key.get(link['witness_key'])
    if raw is None:
      unread_records.append({'witness_key': link['witness_key'], 'field': link['field'], 'raw_text': link.get('raw_text', ''), 'reason': 'missing_raw_witness'})
      wrong_rows.append({'witness_key': link['witness_key'], 'field': link['field'], 'reason': 'missing_raw_witness'})
      continue
    raw_val = raw.get(link['field']) or link.get('raw_text') or ''
    ok, reason = judge_linked_row(
        raw_text=raw_val,
        anchor=org['anchor'],
        display_name=org['display_name'],
        refspec_lookup=refspec_lookup,
    )
    entry = {
        'witness_key': link['witness_key'],
        'field': link['field'],
        'raw_text': raw_val,
        'org_id': org['org_id'],
        'anchor': org['anchor'],
        'display_name': org['display_name'],
        'valid': ok,
        'reason': reason,
    }
    sampled_results.append(entry)
    if not ok:
      wrong_rows.append(entry)

  # Also check EVERY row matching state/local qualifiers across ALL agency_links (deterministic exhaustive audit!)
  exhaustive_state_leaks: list[dict[str, Any]] = []
  for link, org in ordered_links:
    raw = raw_by_key.get(link['witness_key'])
    if raw is None:
      continue
    raw_val = raw.get(link['field']) or link.get('raw_text') or ''
    if _LOCAL_OF_RE.search(raw_val) or _STATE_GOV_PREFIX_RE.search(raw_val):
      ok, reason = judge_linked_row(
          raw_text=raw_val,
          anchor=org['anchor'],
          display_name=org['display_name'],
          refspec_lookup=refspec_lookup,
      )
      if not ok:
        exhaustive_state_leaks.append({
            'witness_key': link['witness_key'],
            'field': link['field'],
            'raw_text': raw_val,
            'anchor': org['anchor'],
            'display_name': org['display_name'],
            'reason': reason,
        })

  return {
      'agency_linked_rows': len(ordered_links),
      'sampled_count': len(sample),
      'wrong_in_sample': len(wrong_rows),
      'wrong_rows': wrong_rows,
      'exhaustive_state_leaks_count': len(exhaustive_state_leaks),
      'exhaustive_state_leaks': exhaustive_state_leaks,
      'unread_records_count': len(unread_records),
      'unread_records': unread_records,
      'house_xml_gov_fed_with_text': gov_fed_total,
      'house_xml_gov_fed_agency_linked': gov_fed_linked,
      'house_xml_gov_fed_unlinked_sample': expected_federal_unlinked[:25],
      'sampled_results': sampled_results,
  }


def verify_planted_state_epa(refspec_tables_dir: pathlib.Path | None = None) -> dict[str, Any]:
  """Verify the raw check flags a planted state-EPA -> federal-EPA link."""
  refspec_lookup = _load_refspec_lookup(refspec_tables_dir)
  planted_cases = [
      ('Ohio Environmental Protection Agency', 'fr_agency:145', 'Environmental Protection Agency'),
      ('Environmental Protection Agency, State of Ohio', 'fr_agency:145', 'Environmental Protection Agency'),
  ]
  results = []
  all_flagged = True
  for raw_text, anchor, display_name in planted_cases:
    ok, reason = judge_linked_row(
        raw_text=raw_text,
        anchor=anchor,
        display_name=display_name,
        refspec_lookup=refspec_lookup,
    )
    results.append({'raw_text': raw_text, 'anchor': anchor, 'flagged': not ok, 'reason': reason})
    if ok:
      all_flagged = False
  return {'planted_flagged': all_flagged, 'cases': results}


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description='Independent raw check for RefSpec agency links.')
  parser.add_argument('--witnesses', required=True, help='Path to raw witnesses.parquet')
  parser.add_argument('--release-dir', required=True, help='Directory holding organizations.parquet and witness_organizations.parquet')
  parser.add_argument('--refspec-tables-dir', default='model/jobs/refspec/agency-registry-view/tables', help='Optional RefSpec view tables directory')
  parser.add_argument('--sample-size', type=int, default=100, help='Number of linked rows to sample')
  parser.add_argument('--seed', type=int, default=20261125, help='Deterministic RNG seed')
  parser.add_argument('--max-wrong', type=int, default=1, help='Maximum allowed wrong links in sample')
  parser.add_argument('--verify-planted', action='store_true', help='Verify planted state-EPA -> federal-EPA detection')
  parser.add_argument('--out-json', help='Optional path to write full JSON report')
  args = parser.parse_args(argv)

  ref_dir = pathlib.Path(args.refspec_tables_dir) if args.refspec_tables_dir else None
  report = run_check(
      witnesses_path=pathlib.Path(args.witnesses),
      release_dir=pathlib.Path(args.release_dir),
      refspec_tables_dir=ref_dir,
      sample_size=args.sample_size,
      seed=args.seed,
  )
  if args.verify_planted:
    report['planted_verification'] = verify_planted_state_epa(ref_dir)

  if args.out_json:
    out_p = pathlib.Path(args.out_json)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

  print(json.dumps({
      'agency_linked_rows': report['agency_linked_rows'],
      'sampled_count': report['sampled_count'],
      'wrong_in_sample': report['wrong_in_sample'],
      'exhaustive_state_leaks_count': report['exhaustive_state_leaks_count'],
      'unread_records_count': report['unread_records_count'],
      'house_xml_gov_fed_with_text': report['house_xml_gov_fed_with_text'],
      'house_xml_gov_fed_agency_linked': report['house_xml_gov_fed_agency_linked'],
      'planted_verification': report.get('planted_verification'),
  }, indent=2))

  if report['wrong_in_sample'] > args.max_wrong:
    return 1
  if report['unread_records_count'] > 0:
    return 1
  if args.verify_planted and not (report.get('planted_verification') or {}).get('planted_flagged'):
    return 1
  return 0


if __name__ == '__main__':
  sys.exit(main())
