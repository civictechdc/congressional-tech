"""Judge retained no-longer-listed Congress.gov items in both directions against raw reads (ct-960v).

    congress_gov_retained_raw_check.py --release DIR --mirror DIR [--captures PARQUET]
        [--plant] --output OUT.json

Walks raw Congress.gov committee-meeting JSON lines from --mirror directly (never importing
repository parsers or model definitions). Orders all raw reads of each eventId by raw
(updateDate, captured_at, sha256) and checks both directions:
  1. Precision (every published no_longer_listed item):
     - witness rows (source='congress_gov', listing_status='no_longer_listed') must appear on an
       earlier raw read of that eventId and be absent from the latest raw read, with agreeing
       last_listed_on and unlisted_since / unlisted_by_record_sha;
     - meetings.document_references entries with listing_status='no_longer_listed' must appear on
       an earlier raw read of that eventId and be absent from the latest raw read;
     - meetings.unlisted_subjects entries must appear in subject_keys, appear on an earlier raw
       read of that eventId, and be absent from the latest raw read.
  2. Completeness (no silent drops when Congress.gov drops an item between reads):
     - a witness, document URL, or bill/nomination subject listed on an earlier Congress.gov read
       and absent from the latest Congress.gov read (and not merely renamed on the latest read or
       kept listed by House XML) must remain published as no_longer_listed rather than vanishing.

With --plant, mutates a copy in memory with (a) a still-listed item falsely marked no_longer_listed
and (b) a retained no_longer_listed item silently deleted, asserting both plants are flagged.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

HONORIFICS = {
    'mr', 'mrs', 'ms', 'miss', 'dr', 'hon', 'honorable', 'the', 'rev', 'reverend',
    'sen', 'senator', 'rep', 'representative', 'gen', 'general', 'adm', 'admiral',
    'col', 'colonel', 'lt', 'maj', 'capt', 'captain', 'prof', 'professor', 'esq',
    'phd', 'md', 'jr', 'sr', 'ii', 'iii', 'iv',
}


def _norm_words(text):
    folded = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode('ascii').lower()
    return [w for w in re.findall(r'[a-z0-9]+', folded) if w]


def _name_tokens(text):
    return [w for w in _norm_words(text) if w not in HONORIFICS]


def _witness_sig(name, position, organization):
    return (
        ' '.join(_name_tokens(name)),
        ' '.join(_norm_words(organization)),
        ' '.join(_norm_words(position)),
    )


def _norm_url(url):
    text = str(url or '').strip()
    if not text:
        return ''
    text = re.sub(r'^http://', 'https://', text, flags=re.I)
    return text.rstrip('/')


def _find_events(obj):
    found = []
    if isinstance(obj, dict):
        if obj.get('eventId') is not None and (
            'witnesses' in obj or 'meetingDocuments' in obj or 'witnessDocuments' in obj
            or 'relatedItems' in obj or 'meetingStatus' in obj or 'date' in obj
        ):
            found.append(obj)
        for v in obj.values():
            found.extend(_find_events(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_events(item))
    return found


def _iso_day(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date().isoformat()
    text = str(value).strip()
    return text[:10] if len(text) >= 10 and text[4] == '-' else None


def _iso_ts(value):
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    text = str(value).strip()
    if not text:
        return ''
    try:
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return text


def _raw_witness_name(w):
    if not isinstance(w, dict):
        return ''
    if w.get('name'):
        return str(w['name']).strip()
    parts = [
        str(w.get(k) or '').strip()
        for k in ('firstName', 'middleName', 'lastName', 'suffix')
    ]
    return ' '.join(p for p in parts if p)


def _extract_raw_meeting(ev):
    witnesses = []
    for w in ev.get('witnesses') or []:
        if not isinstance(w, dict):
            continue
        name = _raw_witness_name(w)
        pos = str(w.get('position') or w.get('title') or '').strip()
        org = str(w.get('organization') or '').strip()
        sig = _witness_sig(name, pos, org)
        if any(sig):
            witnesses.append({
                'name': name,
                'position': pos,
                'organization': org,
                'sig': sig,
                'name_tokens': set(_name_tokens(name)),
            })

    doc_urls = set()
    for d in ev.get('meetingDocuments') or []:
        if isinstance(d, dict) and d.get('url'):
            u = _norm_url(d['url'])
            if u:
                doc_urls.add(u)
    for d in ev.get('witnessDocuments') or []:
        if isinstance(d, dict) and d.get('url'):
            u = _norm_url(d['url'])
            if u:
                doc_urls.add(u)

    subjects = set()
    rel = ev.get('relatedItems') if isinstance(ev.get('relatedItems'), dict) else {}
    for b in rel.get('bills') or ev.get('bills') or []:
        if isinstance(b, dict) and b.get('congress') and b.get('type') and b.get('number') is not None:
            btype = re.sub(r'[^a-z0-9]', '', str(b['type']).lower())
            bnum = str(b['number']).strip()
            if bnum.isdigit():
                bnum = str(int(bnum))
            else:
                bnum = bnum.lower()
            if btype and bnum:
                subjects.add(f"{int(b['congress'])}-{btype}-{bnum}")
    for n in rel.get('nominations') or ev.get('nominations') or []:
        if isinstance(n, dict) and n.get('congress') and n.get('number') is not None:
            raw_num = str(n['number']).strip()
            if raw_num.upper().startswith('PN'):
                raw_num = raw_num[2:].strip()
            part = n.get('part')
            if '-' in raw_num and (part is None or str(part).strip() == ''):
                raw_num, part = raw_num.split('-', 1)
            num_clean = str(int(raw_num)) if raw_num.isdigit() else raw_num.lower()
            if not num_clean:
                continue
            part_suffix = ''
            if part is not None:
                part_str = str(part).strip()
                if part_str and part_str.isdigit():
                    part_int = int(part_str)
                    if part_int > 0:
                        part_suffix = f'-{part_int}'
                elif part_str and part_str not in ('0', '00'):
                    part_suffix = f'-{part_str.lower()}'
            subjects.add(f"{int(n['congress'])}-pn-{num_clean}{part_suffix}")

    return {
        'update_ts': _iso_ts(ev.get('updateDate')),
        'witnesses': witnesses,
        'doc_urls': doc_urls,
        'subjects': subjects,
    }


def _load_capture_times(captures_parquet):
    if not captures_parquet or not Path(captures_parquet).is_file():
        return {}
    pf = pq.ParquetFile(captures_parquet)
    cols = set(pf.schema_arrow.names)
    sha_col = 'body_sha256' if 'body_sha256' in cols else 'record_sha' if 'record_sha' in cols else None
    ts_col = 'captured_at' if 'captured_at' in cols else 'retrieved_at' if 'retrieved_at' in cols else None
    if not sha_col or not ts_col:
        return {}
    out = {}
    for batch in pf.iter_batches(columns=[sha_col, ts_col], batch_size=65536):
        shas = batch.column(0).to_pylist()
        tss = batch.column(1).to_pylist()
        for raw_sha, raw_ts in zip(shas, tss):
            if raw_sha is None or raw_ts is None:
                continue
            hex_sha = raw_sha.hex() if isinstance(raw_sha, (bytes, bytearray)) else str(raw_sha).lower()
            ts = _iso_ts(raw_ts)
            if not ts:
                continue
            prev = out.get(hex_sha)
            if prev is None:
                out[hex_sha] = (ts, ts)
            else:
                out[hex_sha] = (min(prev[0], ts), max(prev[1], ts))
    return out


def _read_local_body(sha, bodies_dirs):
    if not sha:
        return None
    for bdir in bodies_dirs:
        for suffix in ('.gz', '.json.gz', '.json', '.xml.gz', '.xml', ''):
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


def _load_allowed_receipt_keys(receipt_keys_json):
    if not receipt_keys_json or not Path(receipt_keys_json).is_file():
        return None
    payload = json.loads(Path(receipt_keys_json).read_text())
    if isinstance(payload, dict):
        keys = payload.get('receipt_keys') or []
    elif isinstance(payload, list):
        keys = payload
    else:
        keys = []
    return {str(k) for k in keys}


def load_raw_reads(
    mirror_dir,
    captures_parquet=None,
    *,
    bodies_dirs=None,
    receipt_keys_json=None,
    house_xml_shas=(),
    cg_observations=(),
):
    """Return {event_id_str: [ordered read dicts]} and House XML active URLs/subjects per event_id."""
    mirror = Path(mirror_dir)
    cap_times = _load_capture_times(captures_parquet)
    allowed_rks = _load_allowed_receipt_keys(receipt_keys_json)
    bdirs = [Path(d) for d in (bodies_dirs or []) if Path(d).is_dir()]
    if (mirror / 'bodies/sha256').is_dir() and (mirror / 'bodies/sha256') not in bdirs:
        bdirs.append(mirror / 'bodies/sha256')

    cg_obs_map = {str(s).lower(): _iso_ts(ts) for s, ts in cg_observations if s}
    reads_by_event = defaultdict(dict)
    house_docs = defaultdict(set)
    house_subjects = defaultdict(set)

    def _xml_active(elem):
        if (elem.get('remove-date') or '').strip():
            return False
        pub = (elem.get('publish-indicator') or '').strip().upper()
        return pub != 'N'

    def _parse_house_xml(raw_bytes):
        try:
            root = ET.fromstring(raw_bytes)
        except ET.ParseError:
            return
        if not _xml_active(root):
            return
        raw_mid = str(root.get('meeting-id') or root.get('event-id') or '').strip()
        if not raw_mid:
            ev_el = root.find('.//event-id')
            raw_mid = str(ev_el.text if ev_el is not None and ev_el.text else '').strip()
        m_ev = re.search(r'([0-9]+)$', raw_mid)
        ev_id = m_ev.group(1) if m_ev else ''
        if not ev_id:
            return
        cong_attr = str(root.get('congress-num') or '').strip()
        if not cong_attr:
            for c_path in ('meeting-details/congress', './/congress-num', './/congress'):
                c_el = root.find(c_path)
                if c_el is not None and c_el.text and c_el.text.strip().isdigit():
                    cong_attr = c_el.text.strip()
                    break

        doc_elems = []
        docs_root = root.find('meeting-documents')
        containers = [docs_root] if docs_root is not None else [root]
        for cont in containers:
            for d_el in cont.findall('meeting-document'):
                if _xml_active(d_el):
                    doc_elems.append(d_el)
            for grp in cont.findall('meeting-document-group'):
                if not _xml_active(grp):
                    continue
                for d_el in grp.findall('meeting-document'):
                    if _xml_active(d_el):
                        doc_elems.append(d_el)

        prose_bill_re = re.compile(
            r'\b(H\.?\s*R\.?|S\.?|H\.?\s*J\.?\s*Res\.?|S\.?\s*J\.?\s*Res\.?|'
            r'H\.?\s*Con\.?\s*Res\.?|S\.?\s*Con\.?\s*Res\.?|H\.?\s*Res\.?|S\.?\s*Res\.?)\s*([0-9]+)\b',
            re.I,
        )
        url_bill_re = re.compile(
            r'(?:bills-|_)(?:([0-9]{2,3}))?(hr|s|hjres|sjres|hconres|sconres|hres|sres)([0-9]+)',
            re.I,
        )

        for doc_el in doc_elems:
            files_cont = doc_el.find('files')
            f_elems = files_cont.findall('file') if files_cont is not None else doc_el.findall('file')
            for f_el in f_elems:
                if not _xml_active(f_el):
                    continue
                raw_u = (f_el.get('doc-url') or f_el.get('url') or (f_el.text or '')).strip()
                if raw_u:
                    house_docs[ev_id].add(_norm_url(raw_u))
                    for um in url_bill_re.finditer(raw_u):
                        u_cong = um.group(1) or cong_attr
                        if u_cong and u_cong.isdigit():
                            house_subjects[ev_id].add(f"{int(u_cong)}-{um.group(2).lower()}-{int(um.group(3))}")
            for url_el in doc_el.findall('.//url'):
                if url_el.text and url_el.text.strip():
                    house_docs[ev_id].add(_norm_url(url_el.text))
            if cong_attr.isdigit():
                for txt in (doc_el.findtext('legis-num') or '', doc_el.findtext('description') or ''):
                    for pm in prose_bill_re.finditer(txt):
                        btype = re.sub(r'[^a-z0-9]', '', pm.group(1).lower())
                        house_subjects[ev_id].add(f"{int(cong_attr)}-{btype}-{int(pm.group(2))}")

    for h_sha in house_xml_shas:
        h_bytes = _read_local_body(str(h_sha).lower(), bdirs)
        if h_bytes and h_bytes[:200].lstrip().startswith(b'<'):
            _parse_house_xml(h_bytes)

    events_by_sha = {}

    def _record_event_json(ev, digest, env_cap):
        ev_id = str(ev.get('eventId') or '').strip()
        if not ev_id:
            return
        ct_pair = cap_times.get(digest)
        cands = [t for t in (env_cap, *(ct_pair or ())) if t]
        prev = reads_by_event[ev_id].get(digest)
        if prev is None:
            facts = _extract_raw_meeting(ev)
            first_ft = min(cands) if cands else ''
            last_ft = max(cands) if cands else ''
            upd_day = _iso_day(facts['update_ts'])
            prev = {
                'record_sha': digest,
                'first_fetch_ts': first_ft,
                'last_fetch_ts': last_ft,
                'first_captured_at': first_ft or facts['update_ts'],
                'first_captured_day': _iso_day(first_ft) or upd_day,
                'last_captured_at': last_ft or facts['update_ts'],
                'last_captured_day': _iso_day(last_ft) or upd_day,
                'captured_at': last_ft,
                'captured_day': _iso_day(last_ft) or upd_day,
                'update_ts': facts['update_ts'],
                'witnesses': facts['witnesses'],
                'doc_urls': facts['doc_urls'],
                'subjects': facts['subjects'],
            }
            reads_by_event[ev_id][digest] = prev
            events_by_sha.setdefault(digest, set()).add(ev_id)
        elif cands:
            min_c = min(cands)
            max_c = max(cands)
            if not prev['first_fetch_ts'] or min_c < prev['first_fetch_ts']:
                prev['first_fetch_ts'] = min_c
                prev['first_captured_at'] = min_c
                prev['first_captured_day'] = _iso_day(min_c) or prev['first_captured_day']
            if not prev['last_fetch_ts'] or max_c > prev['last_fetch_ts']:
                prev['last_fetch_ts'] = max_c
                prev['last_captured_at'] = max_c
                prev['last_captured_day'] = _iso_day(max_c) or prev['last_captured_day']
                prev['captured_at'] = max_c
                prev['captured_day'] = prev['last_captured_day']

    def _record_body_sha(c_sha, env_cap):
        if c_sha in events_by_sha:
            if env_cap:
                for ev_id in events_by_sha[c_sha]:
                    _record_event_json({'eventId': ev_id}, c_sha, env_cap)
            return
        body_bytes = _read_local_body(c_sha, bdirs)
        if not body_bytes:
            return
        try:
            body_obj = json.loads(body_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        events_by_sha.setdefault(c_sha, set())
        for ev in _find_events(body_obj):
            _record_event_json(ev, c_sha, env_cap)

    receipts_root = mirror / 'receipts/congress/meetings'
    receipt_files = []
    if receipts_root.is_dir():
        for p in sorted(receipts_root.rglob('*')):
            if not p.is_file() or p.name.endswith('.qualification.json'):
                continue
            if allowed_rks is not None:
                rel_key = str(p.relative_to(mirror))
                if rel_key not in allowed_rks:
                    continue
            receipt_files.append(p)

    # Scan standalone files in bodies/sha256 ONLY for small unit-test fixtures (never 400k+ full mirrors)
    standalone_body_files = []
    if not receipt_files and (mirror / 'bodies/sha256').is_dir():
        cand = []
        for idx, p in enumerate((mirror / 'bodies/sha256').rglob('*')):
            if idx > 500:
                cand = []
                break
            if p.is_file():
                cand.append(p)
        standalone_body_files = sorted(cand)

    def _iter_raw_lines_or_xml(path: Path):
        head = b''
        with path.open('rb') as raw_fh:
            magic = raw_fh.read(2)
        open_fn = (lambda: gzip.open(path, 'rb')) if (path.suffix == '.gz' or magic == b'\x1f\x8b') else (lambda: path.open('rb'))
        try:
            with open_fn() as fh:
                head = fh.read(512)
                if head.lstrip().startswith(b'<'):
                    rest = fh.read()
                    _parse_house_xml(head + rest)
                    return
            with open_fn() as fh:
                first_chunk = head.lstrip()
                first_line = first_chunk.split(b'\n', 1)[0].rstrip() if b'\n' in first_chunk else b''
                # Multi-line pretty-printed standalone JSON file (e.g. unit-test fixture)
                if first_line.startswith(b'{') and not first_line.endswith(b'}'):
                    raw_all = fh.read()
                    try:
                        obj = json.loads(raw_all)
                    except json.JSONDecodeError:
                        obj = None
                    if obj is not None:
                        digest = sha256(raw_all).hexdigest()
                        env_cap = _iso_ts(obj.get('retrieved_at') or obj.get('captured_at') if isinstance(obj, dict) else None)
                        for ev in _find_events(obj):
                            _record_event_json(ev, digest, env_cap)
                        return
                    for raw_line in raw_all.splitlines():
                        yield raw_line.rstrip(b'\r\n')
                    return
                for raw_line in fh:
                    yield raw_line.rstrip(b'\r\n')
        except OSError:
            return

    for path in [*receipt_files, *standalone_body_files]:
        for line in _iter_raw_lines_or_xml(path) or ():
            line_stripped = line.strip()
            if not line_stripped or not line_stripped.startswith(b'{'):
                continue
            try:
                envelope = json.loads(line_stripped)
            except json.JSONDecodeError:
                continue
            if not isinstance(envelope, dict):
                continue
            env_cap = _iso_ts(
                envelope.get('retrieved_at')
                or envelope.get('captured_at')
                or envelope.get('capturedAt')
                or envelope.get('fetched_at')
            )
            caps = envelope.get('captures')
            if isinstance(caps, list) and caps:
                if envelope.get('outcome') and envelope.get('outcome') not in ('stored', 'unchanged'):
                    continue
                if envelope.get('http_status') and int(envelope['http_status']) >= 300:
                    continue
                if envelope.get('complete') is False:
                    continue
                for cap in caps:
                    if not isinstance(cap, dict) or not cap.get('sha256'):
                        continue
                    _record_body_sha(str(cap['sha256']).lower(), env_cap)
                continue

            # Assembled historical inline receipt lines have 'source_file', 'record', and captures=[].
            if isinstance(caps, list) and len(caps) == 0 and 'source_file' in envelope:
                digest = sha256(line).hexdigest()
                if cg_obs_map and digest not in cg_obs_map:
                    continue
                rec_obj = envelope.get('record') if isinstance(envelope.get('record'), dict) else envelope
                asm_cap = env_cap or _iso_ts(rec_obj.get('_retrieved_at')) or cg_obs_map.get(digest, '')
                for ev in _find_events(rec_obj):
                    _record_event_json(ev, digest, asm_cap)
                continue
            digest = sha256(line).hexdigest()
            for ev in _find_events(envelope):
                _record_event_json(ev, digest, env_cap)

    for cg_sha, cg_obs_at in cg_observations:
        _record_body_sha(str(cg_sha).lower(), _iso_ts(cg_obs_at))

    ordered = {}
    for ev_id, by_sha in reads_by_event.items():
        ordered[ev_id] = sorted(
            by_sha.values(),
            key=lambda r: (
                1 if r['update_ts'] else 0,
                r['update_ts'] or '',
                1 if r['captured_at'] else 0,
                r['captured_at'] or '',
                r['record_sha'],
            ),
        )
    return ordered, house_docs, house_subjects


def _hex(val):
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        return val.hex()
    return str(val).lower()


def _same_person_edit(dropped_w, current_witnesses):
    """True when an edited witness on the latest read shares family token + given initial and org."""
    dtoks = list(dropped_w['name_tokens'])
    if not dtoks:
        return False
    dfam = dtoks[-1]
    dinit = dtoks[0][0]
    dorg = dropped_w['sig'][1]
    for cw in current_witnesses:
        ctoks = list(cw['name_tokens'])
        if not ctoks:
            continue
        if ctoks[-1] == dfam and ctoks[0][0] == dinit:
            corg = cw['sig'][1]
            if not dorg or not corg or dorg == corg:
                return True
    return False


def evaluate(witness_rows, meeting_rows, raw_reads, house_docs=None, house_subjects=None, *, max_flags=100):
    house_docs = house_docs or {}
    house_subjects = house_subjects or {}
    flags = []
    counts = Counter()

    pub_cg_witnesses_by_event = defaultdict(list)
    for w in witness_rows:
        if w.get('source') != 'congress_gov':
            continue
        ev_id = str(w.get('event_id') or '')
        if not ev_id and str(w.get('occasion') or '').startswith('meeting:'):
            ev_id = str(w['occasion']).split(':', 1)[1]
        if ev_id:
            pub_cg_witnesses_by_event[ev_id].append(w)

    meetings_by_event = {str(m.get('event_id')): m for m in meeting_rows if m.get('event_id') is not None}
    unread_records = []

    # 1. Forward checks: every published no_longer_listed item must be backed by earlier raw read & absent from latest.
    for ev_id, w_list in sorted(pub_cg_witnesses_by_event.items()):
        reads = raw_reads.get(ev_id)
        pub_listed_counts = Counter(
            _witness_sig(w.get('name'), w.get('position'), w.get('organization'))
            for w in w_list
            if (w.get('listing_status') or 'listed') == 'listed'
        )
        seen_unlisted_ord = Counter()
        read_sig_counts = [Counter(rw['sig'] for rw in r['witnesses']) for r in (reads or [])]
        for w in w_list:
            status = w.get('listing_status') or 'listed'
            if status != 'no_longer_listed':
                continue
            counts['checked_unlisted_witnesses'] += 1
            if not reads:
                counts['unread_unlisted_witnesses'] += 1
                unread_records.append({'kind': 'witness', 'event_id': ev_id, 'witness_key': w.get('witness_key')})
                continue
            sig = _witness_sig(w.get('name'), w.get('position'), w.get('organization'))
            seen_unlisted_ord[sig] += 1
            needed_slots = pub_listed_counts[sig] + seen_unlisted_ord[sig]
            latest = reads[-1]
            latest_counts = read_sig_counts[-1]
            if latest_counts[sig] >= needed_slots:
                flags.append({
                    'kind': 'still_listed_witness_marked_removed',
                    'event_id': ev_id,
                    'witness_key': w.get('witness_key'),
                    'name': w.get('name'),
                })
                continue
            hit_indices = [i for i in range(len(reads) - 1) if read_sig_counts[i][sig] >= needed_slots]
            if not hit_indices:
                flags.append({
                    'kind': 'never_listed_witness_marked_removed',
                    'event_id': ev_id,
                    'witness_key': w.get('witness_key'),
                    'name': w.get('name'),
                })
                continue
            last_hit_idx = hit_indices[-1]
            last_hit = reads[last_hit_idx]
            first_miss_idx = next(
                (i for i in range(last_hit_idx + 1, len(reads)) if read_sig_counts[i][sig] < needed_slots),
                len(reads) - 1,
            )
            first_miss = reads[first_miss_idx]
            pub_last = _iso_day(w.get('last_listed_on'))
            pub_since = _iso_day(w.get('unlisted_since'))
            pub_unlisted_sha = _hex(w.get('unlisted_by_record_sha'))
            raw_last_day = last_hit.get('last_captured_day') or last_hit.get('captured_day')
            raw_since_day = first_miss.get('first_captured_day') or first_miss.get('captured_day')
            if raw_last_day and pub_last and pub_last != raw_last_day:
                flags.append({
                    'kind': 'witness_last_listed_date_mismatch',
                    'event_id': ev_id,
                    'witness_key': w.get('witness_key'),
                    'published': pub_last,
                    'raw': raw_last_day,
                })
            if raw_since_day and pub_since and pub_since != raw_since_day:
                flags.append({
                    'kind': 'witness_unlisted_since_mismatch',
                    'event_id': ev_id,
                    'witness_key': w.get('witness_key'),
                    'published': pub_since,
                    'raw': raw_since_day,
                })
            if pub_unlisted_sha and pub_unlisted_sha != first_miss['record_sha']:
                flags.append({
                    'kind': 'witness_unlisted_record_sha_mismatch',
                    'event_id': ev_id,
                    'witness_key': w.get('witness_key'),
                    'published': pub_unlisted_sha,
                    'raw': first_miss['record_sha'],
                })
            counts['supported_unlisted_witnesses'] += 1

    for ev_id, m in sorted(meetings_by_event.items()):
        reads = raw_reads.get(ev_id)
        for ref in m.get('document_references') or []:
            if (ref.get('listing_status') or 'listed') != 'no_longer_listed':
                continue
            counts['checked_unlisted_docs'] += 1
            if not reads:
                counts['unread_unlisted_docs'] += 1
                unread_records.append({'kind': 'document_reference', 'event_id': ev_id, 'url': ref.get('url')})
                continue
            u = _norm_url(ref.get('url'))
            latest = reads[-1]
            if u in latest['doc_urls'] or u in house_docs.get(ev_id, set()):
                flags.append({
                    'kind': 'still_listed_doc_marked_removed',
                    'event_id': ev_id,
                    'url': ref.get('url'),
                })
                continue
            hit_indices = [i for i, r in enumerate(reads[:-1]) if u in r['doc_urls']]
            if not hit_indices:
                flags.append({
                    'kind': 'never_listed_doc_marked_removed',
                    'event_id': ev_id,
                    'url': ref.get('url'),
                })
                continue
            last_hit_idx = hit_indices[-1]
            last_hit = reads[last_hit_idx]
            first_miss = next(
                (r for r in reads[last_hit_idx + 1:] if u not in r['doc_urls']),
                latest,
            )
            pub_last = _iso_day(ref.get('last_listed_on'))
            pub_since = _iso_day(ref.get('unlisted_since'))
            pub_unlisted_sha = _hex(ref.get('unlisted_by_record_sha'))
            raw_last_day = last_hit.get('last_captured_day') or last_hit.get('captured_day')
            raw_since_day = first_miss.get('first_captured_day') or first_miss.get('captured_day')
            if raw_last_day and pub_last and pub_last != raw_last_day:
                flags.append({
                    'kind': 'doc_last_listed_date_mismatch',
                    'event_id': ev_id,
                    'url': ref.get('url'),
                    'published': pub_last,
                    'raw': raw_last_day,
                })
            if raw_since_day and pub_since and pub_since != raw_since_day:
                flags.append({
                    'kind': 'doc_unlisted_since_mismatch',
                    'event_id': ev_id,
                    'url': ref.get('url'),
                    'published': pub_since,
                    'raw': raw_since_day,
                })
            if pub_unlisted_sha and pub_unlisted_sha != first_miss['record_sha']:
                flags.append({
                    'kind': 'doc_unlisted_record_sha_mismatch',
                    'event_id': ev_id,
                    'url': ref.get('url'),
                    'published': pub_unlisted_sha,
                    'raw': first_miss['record_sha'],
                })
            counts['supported_unlisted_docs'] += 1

        subj_set = {str(s).lower() for s in (m.get('subject_keys') or [])}
        for u_sub in m.get('unlisted_subjects') or []:
            sk = str(u_sub.get('subject_key') or '').lower()
            counts['checked_unlisted_subjects'] += 1
            if sk not in subj_set:
                flags.append({
                    'kind': 'unlisted_subject_missing_from_subject_keys',
                    'event_id': ev_id,
                    'subject_key': sk,
                })
                continue
            if not reads:
                counts['unread_unlisted_subjects'] += 1
                unread_records.append({'kind': 'unlisted_subject', 'event_id': ev_id, 'subject_key': sk})
                continue
            latest = reads[-1]
            if sk in latest['subjects'] or sk in house_subjects.get(ev_id, set()):
                flags.append({
                    'kind': 'still_listed_subject_marked_removed',
                    'event_id': ev_id,
                    'subject_key': sk,
                })
                continue
            hit_indices = [i for i, r in enumerate(reads[:-1]) if sk in r['subjects']]
            if not hit_indices:
                flags.append({
                    'kind': 'never_listed_subject_marked_removed',
                    'event_id': ev_id,
                    'subject_key': sk,
                })
                continue
            last_hit_idx = hit_indices[-1]
            last_hit = reads[last_hit_idx]
            first_miss = next(
                (r for r in reads[last_hit_idx + 1:] if sk not in r['subjects']),
                latest,
            )
            pub_last = _iso_day(u_sub.get('last_listed_on'))
            pub_since = _iso_day(u_sub.get('unlisted_since'))
            pub_unlisted_sha = _hex(u_sub.get('unlisted_by_record_sha'))
            raw_last_day = last_hit.get('last_captured_day') or last_hit.get('captured_day')
            raw_since_day = first_miss.get('first_captured_day') or first_miss.get('captured_day')
            if raw_last_day and pub_last and pub_last != raw_last_day:
                flags.append({
                    'kind': 'subject_last_listed_date_mismatch',
                    'event_id': ev_id,
                    'subject_key': sk,
                    'published': pub_last,
                    'raw': raw_last_day,
                })
            if raw_since_day and pub_since and pub_since != raw_since_day:
                flags.append({
                    'kind': 'subject_unlisted_since_mismatch',
                    'event_id': ev_id,
                    'subject_key': sk,
                    'published': pub_since,
                    'raw': raw_since_day,
                })
            if pub_unlisted_sha and pub_unlisted_sha != first_miss['record_sha']:
                flags.append({
                    'kind': 'subject_unlisted_record_sha_mismatch',
                    'event_id': ev_id,
                    'subject_key': sk,
                    'published': pub_unlisted_sha,
                    'raw': first_miss['record_sha'],
                })
            counts['supported_unlisted_subjects'] += 1

    # 2. Reverse checks: every dropped item across raw Congress.gov reads must stay published as no_longer_listed.
    for ev_id, reads in sorted(raw_reads.items()):
        if len(reads) < 2 or ev_id not in meetings_by_event:
            continue
        counts['multi_read_meetings_checked'] += 1
        latest = reads[-1]
        latest_w_counts = Counter(rw['sig'] for rw in latest['witnesses'])
        earlier_w_by_sig = {}
        max_earlier_w_counts = Counter()
        for r in reads[:-1]:
            rc = Counter(rw['sig'] for rw in r['witnesses'])
            for sig, cnt in rc.items():
                if cnt > max_earlier_w_counts[sig]:
                    max_earlier_w_counts[sig] = cnt
            for rw in r['witnesses']:
                earlier_w_by_sig[rw['sig']] = rw

        pub_unlisted_w_counts = Counter()
        pub_w_status = {}
        for w in pub_cg_witnesses_by_event.get(ev_id, []):
            wsig = _witness_sig(w.get('name'), w.get('position'), w.get('organization'))
            st = w.get('listing_status') or 'listed'
            pub_w_status[wsig] = st
            if st == 'no_longer_listed':
                pub_unlisted_w_counts[wsig] += 1

        for sig, rw in sorted(earlier_w_by_sig.items()):
            expected_dropped = max_earlier_w_counts[sig] - latest_w_counts[sig]
            if expected_dropped <= 0:
                continue
            if latest_w_counts[sig] == 0 and _same_person_edit(rw, latest['witnesses']):
                counts['edited_witnesses_continued'] += 1
                continue
            if pub_unlisted_w_counts[sig] < expected_dropped:
                flags.append({
                    'kind': 'dropped_witness_missing',
                    'event_id': ev_id,
                    'name': rw['name'],
                    'published_status': pub_w_status.get(sig),
                })

        m = meetings_by_event[ev_id]
        pub_doc_status = {
            _norm_url(ref.get('url')): (ref.get('listing_status') or 'listed')
            for ref in (m.get('document_references') or [])
            if ref.get('url')
        }
        earlier_docs = set().union(*(r['doc_urls'] for r in reads[:-1]))
        for u in sorted(earlier_docs - latest['doc_urls']):
            if u in house_docs.get(ev_id, set()):
                continue
            if pub_doc_status.get(u) != 'no_longer_listed':
                flags.append({
                    'kind': 'dropped_doc_missing',
                    'event_id': ev_id,
                    'url': u,
                    'published_status': pub_doc_status.get(u),
                })

        pub_unlisted_subjs = {str(u.get('subject_key') or '').lower() for u in (m.get('unlisted_subjects') or [])}
        pub_all_subjs = {str(s).lower() for s in (m.get('subject_keys') or [])}
        earlier_subjs = set().union(*(r['subjects'] for r in reads[:-1]))
        for sk in sorted(earlier_subjs - latest['subjects']):
            if sk in house_subjects.get(ev_id, set()):
                continue
            if sk not in pub_all_subjs or sk not in pub_unlisted_subjs:
                flags.append({
                    'kind': 'dropped_subject_missing',
                    'event_id': ev_id,
                    'subject_key': sk,
                    'in_subject_keys': sk in pub_all_subjs,
                    'in_unlisted_subjects': sk in pub_unlisted_subjs,
                })

    return {
        'counts': dict(counts),
        'unread_records': unread_records,
        'flag_count': len(flags),
        'flags_by_kind': dict(Counter(f['kind'] for f in flags)),
        'flags': flags if max_flags is None else flags[:max_flags],
    }


def run_plants(witness_rows, meeting_rows, raw_reads, house_docs=None, house_subjects=None):
    """Run both required plants: (1) still-listed marked removed, (2) dropped item deleted."""
    results = {}

    # Plant 1: pick a still-listed Congress.gov witness on a read meeting and mark it no_longer_listed
    target_idx = next(
        (i for i, w in enumerate(witness_rows)
         if w.get('source') == 'congress_gov'
         and (w.get('listing_status') or 'listed') == 'listed'
         and str(w.get('event_id') or '') in raw_reads
         and _witness_sig(w.get('name'), w.get('position'), w.get('organization'))
         in {rw['sig'] for rw in raw_reads[str(w.get('event_id'))][-1]['witnesses']}),
        None,
    )
    if target_idx is not None:
        w_copy = list(witness_rows)
        target_w = dict(w_copy[target_idx])
        target_w['listing_status'] = 'no_longer_listed'
        target_w['last_listed_on'] = '2025-01-01'
        target_w['unlisted_since'] = '2025-01-02'
        w_copy[target_idx] = target_w
        res1 = evaluate(w_copy, meeting_rows, raw_reads, house_docs, house_subjects, max_flags=None)
        results['still_listed_marked_removed'] = {
            'planted_witness_key': target_w.get('witness_key'),
            'caught': any(
                f['kind'] == 'still_listed_witness_marked_removed'
                and f.get('witness_key') == target_w.get('witness_key')
                for f in res1['flags']
            ),
            'flags_by_kind': res1['flags_by_kind'],
        }
    else:
        results['still_listed_marked_removed'] = {'caught': False, 'reason': 'no_eligible_target'}

    # Plant 2: delete a retained no_longer_listed Congress.gov witness (or document_reference)
    unlisted_w = next(
        (w for w in witness_rows
         if w.get('source') == 'congress_gov'
         and w.get('listing_status') == 'no_longer_listed'
         and str(w.get('event_id') or '') in raw_reads),
        None,
    )
    if unlisted_w is not None:
        w_drop = [w for w in witness_rows if w.get('witness_key') != unlisted_w.get('witness_key')]
        res2 = evaluate(w_drop, meeting_rows, raw_reads, house_docs, house_subjects, max_flags=None)
        results['dropped_item_deleted'] = {
            'planted_kind': 'witness',
            'planted_witness_key': unlisted_w.get('witness_key'),
            'event_id': str(unlisted_w.get('event_id')),
            'caught': any(
                f['kind'] == 'dropped_witness_missing'
                and f.get('event_id') == str(unlisted_w.get('event_id'))
                for f in res2['flags']
            ),
            'flags_by_kind': res2['flags_by_kind'],
        }
    else:
        # Try a no_longer_listed document_reference if no witness was unlisted in the slice
        m_copy = list(meeting_rows)
        planted_doc = None
        for m_idx, m in enumerate(m_copy):
            ev_id = str(m.get('event_id') or '')
            if ev_id not in raw_reads:
                continue
            refs = list(m.get('document_references') or [])
            idx = next((i for i, r in enumerate(refs) if r.get('listing_status') == 'no_longer_listed'), None)
            if idx is not None:
                planted_doc = (ev_id, refs[idx].get('url'))
                refs.pop(idx)
                m_copy[m_idx] = {**m, 'document_references': refs}
                break
        if planted_doc is not None:
            res2 = evaluate(witness_rows, m_copy, raw_reads, house_docs, house_subjects, max_flags=None)
            results['dropped_item_deleted'] = {
                'planted_kind': 'document_reference',
                'event_id': planted_doc[0],
                'url': planted_doc[1],
                'caught': any(
                    f['kind'] == 'dropped_doc_missing' and f.get('event_id') == planted_doc[0]
                    for f in res2['flags']
                ),
                'flags_by_kind': res2['flags_by_kind'],
            }
        else:
            results['dropped_item_deleted'] = {'caught': False, 'reason': 'no_eligible_unlisted_target'}

    return results


def _read_parquet_cols(path: Path, wanted_cols: list[str], *, filters=None) -> list[dict]:
    pf = pq.ParquetFile(path)
    present = [c for c in wanted_cols if c in pf.schema_arrow.names]
    return pq.read_table(path, columns=present, filters=filters).to_pylist()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--mirror', type=Path, required=True)
    parser.add_argument('--bodies-dir', type=Path, action='append', default=None)
    parser.add_argument('--receipt-keys-json', type=Path, default=None)
    parser.add_argument('--captures', type=Path, default=None)
    parser.add_argument('--plant', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)

    witness_rows = _read_parquet_cols(args.release / 'witnesses.parquet', [
        'witness_key', 'source', 'event_id', 'occasion', 'name', 'position', 'organization',
        'listing_status', 'last_listed_on', 'unlisted_since', 'unlisted_by_record_sha',
    ], filters=[('source', '==', 'congress_gov')])
    meeting_rows = _read_parquet_cols(args.release / 'meetings.parquet', [
        'event_id', 'document_references', 'subject_keys', 'unlisted_subjects', 'publisher_status_observations',
    ])
    house_xml_shas = set()
    cg_observations = {}
    for m in meeting_rows:
        for obs in m.get('publisher_status_observations') or []:
            r_sha = str(obs.get('record_sha') or '').lower()
            if not r_sha:
                continue
            if obs.get('source') == 'house_xml':
                house_xml_shas.add(r_sha)
            elif obs.get('source') == 'congress_gov':
                obs_ts = _iso_ts(obs.get('observed_at'))
                if r_sha not in cg_observations or (obs_ts and (not cg_observations[r_sha] or obs_ts < cg_observations[r_sha])):
                    cg_observations[r_sha] = obs_ts
    raw_reads, house_docs, house_subjects = load_raw_reads(
        args.mirror,
        args.captures,
        bodies_dirs=args.bodies_dir,
        receipt_keys_json=args.receipt_keys_json,
        house_xml_shas=sorted(house_xml_shas),
        cg_observations=sorted(cg_observations.items()),
    )

    report = evaluate(witness_rows, meeting_rows, raw_reads, house_docs, house_subjects)
    report['raw_events_read'] = len(raw_reads)
    if args.plant:
        plants = run_plants(witness_rows, meeting_rows, raw_reads, house_docs, house_subjects)
        report['plants'] = plants
        if not all(p.get('caught') for p in plants.values()):
            args.output.write_text(json.dumps(report, indent=2, default=str) + '\n')
            raise SystemExit(f"Planted case was not caught: {plants}")

    args.output.write_text(json.dumps(report, indent=2, default=str) + '\n')
    print(json.dumps({
        'raw_events_read': report['raw_events_read'],
        'counts': report['counts'],
        'flag_count': report['flag_count'],
        'plants': report.get('plants'),
    }, default=str))
    return report


if __name__ == '__main__':
    main()
