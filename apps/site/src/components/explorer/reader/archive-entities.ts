const hex = (value: Uint8Array) => [...value].map(v => v.toString(16).padStart(2, '0')).join('');
const date = (value: any) => value instanceof Date ? value.toISOString().slice(0, 10) : value == null ? null : String(value).slice(0, 10);

export interface ArchiveEntityContext {
  count: number;
  files: Map<string, any>;
  columns: Map<string, any>;
  value: (name: string, i: number) => any;
  row: (i: number) => any;
  entity: (name: string) => Promise<any[]>;
  resolve: (key: string) => Promise<number | null>;
  entry: (index: number, signal?: AbortSignal) => Promise<any>;
  versions: (index: number, signal?: AbortSignal) => Promise<any[]>;
}

export function resolveCommitteeHistoricalName(committee: any, dateOrCongress?: any): string {
  if (!committee) return '';
  const history = Array.isArray(committee.names) ? committee.names : Array.isArray(committee.histories) ? committee.histories : [];
  if (dateOrCongress != null && history.length) {
    const raw = String(dateOrCongress).trim();
    if (/^\d{1,3}$/.test(raw)) {
      const cong = Number(raw);
      for (const h of history) {
        if (h?.congress != null && Number(h.congress) === cong && h.name) return String(h.name);
      }
      const startYear = `${1789 + (cong - 1) * 2}-01-03`, endYear = `${1789 + cong * 2}-01-03`;
      for (const h of history) {
        const s = date(h?.start ?? h?.start_date), e = date(h?.end ?? h?.end_date);
        if ((!s || s < endYear) && (!e || e > startYear) && h?.name) return String(h.name);
      }
    } else {
      const target = date(dateOrCongress);
      if (target) {
        for (const h of history) {
          const s = date(h?.start ?? h?.start_date), e = date(h?.end ?? h?.end_date);
          if ((!s || target >= s) && (!e || target < e) && h?.name) return String(h.name);
        }
      }
    }
  }
  return String(committee.current_name ?? committee.name ?? history.at(-1)?.name ?? '');
}

const toFilterList = (val: any): string[] =>
  val == null || val === '' ? [] : Array.isArray(val) ? val.flatMap(v => v != null && v !== '' ? [String(v)] : []) : [String(val)];

const pushMap = <K, V>(map: Map<K, V[]>, key: K, item: V) => {
  let list = map.get(key);
  if (!list) { list = []; map.set(key, list); }
  list.push(item);
};

export function createArchiveEntities(ctx: ArchiveEntityContext) {
  const { count, files, columns, value, row, entity } = ctx;
  const invertedColumns = new Map<string, Map<string, number[]>>();

  const rowsForColumn = (colName: string, key: any): number[] => {
    if (key == null || !columns.has(colName)) return [];
    let indexMap = invertedColumns.get(colName);
    if (!indexMap) {
      indexMap = new Map<string, number[]>();
      for (let i = 0; i < count; i++) {
        const current = value(colName, i);
        const items = Array.isArray(current) ? current : current != null ? [current] : [];
        for (const item of items) if (item != null) pushMap(indexMap, String(item).toLowerCase(), i);
      }
      invertedColumns.set(colName, indexMap);
    }
    return indexMap.get(String(key).toLowerCase()) ?? [];
  };

  const uniqueInts = (items: Iterable<any>): number[] => {
    const seen = new Set<number>();
    for (const item of items) {
      const n = Number(item);
      if (Number.isSafeInteger(n) && n >= 0 && n < count) seen.add(n);
    }
    return [...seen].sort((a, b) => a - b);
  };

  const normalizeMeeting = (m: any) => {
    const eventKey = String(m.event_id ?? m.meeting_key ?? '');
    const transcriptRows = Array.isArray(m.transcripts) ? m.transcripts.map((t: any) => t?.list_row).filter((r: any) => r != null) : [];
    const listRows = uniqueInts([...(Array.isArray(m.list_rows) ? m.list_rows : []), ...rowsForColumn('meeting_keys', eventKey), ...transcriptRows]);
    const committeeObjs = Array.isArray(m.committees) ? m.committees.map((c: any) => typeof c === 'string' ? { system_code: c, committee_key: c } : { ...c, system_code: c.system_code ?? c.committee_key, committee_key: c.committee_key ?? c.system_code }) : [];
    const committeeKeys = Array.isArray(m.committee_keys) && m.committee_keys.length
      ? m.committee_keys.map((k: any) => String(k).toLowerCase())
      : committeeObjs.map((c: any) => String(c.committee_key ?? c.system_code ?? '').toLowerCase()).filter(Boolean);
    const subjectKeys = Array.isArray(m.subject_keys) ? m.subject_keys.map(String) : Array.isArray(m.measure_keys) ? m.measure_keys.map(String) : [];
    return {
      ...m, event_id: eventKey, congress: m.congress != null ? Number(m.congress) : null, session: m.session != null ? Number(m.session) : null,
      meeting_key: eventKey, meeting_date: date(m.meeting_date), committees: committeeObjs, committee_keys: committeeKeys, subject_keys: subjectKeys,
      sittings: Array.isArray(m.sittings) ? m.sittings : [],
      transcripts: Array.isArray(m.transcripts) ? m.transcripts.map((t: any) => ({ ...t, list_row: t?.list_row != null ? Number(t.list_row) : null })) : [],
      videos: Array.isArray(m.videos) ? m.videos.map((v: any) => ({ ...v, title: v?.title ?? v?.name ?? null, name: v?.name ?? v?.title ?? null })) : [],
      witnesses: Array.isArray(m.witnesses) ? m.witnesses : [], list_rows: listRows,
    };
  };

  const normalizeWitness = (w: any) => {
    const wKey = w.witness_key instanceof Uint8Array ? hex(w.witness_key) : String(w.witness_key ?? w.name_key ?? '');
    const inferredEventId = w.event_id != null ? String(w.event_id) : (typeof w.occasion === 'string' && w.occasion.startsWith('meeting:') ? w.occasion.slice(8) : null);
    const colRows = rowsForColumn('witness_keys', wKey);
    const rawAppearances = Array.isArray(w.appearances) ? w.appearances : (inferredEventId || w.occasion || w.package_id || w.page_url) ? [{
      event_id: inferredEventId, occasion: w.occasion ?? null, package_id: w.package_id ?? null, page_url: w.page_url ?? null,
      position: w.position ?? null, organization: w.organization ?? null, on_behalf_of: w.on_behalf_of ?? null, location: w.location ?? null,
      panel: w.panel ?? null, panel_order: w.panel_order != null ? Number(w.panel_order) : null, display_order: w.display_order != null ? Number(w.display_order) : null,
      witness_type: w.witness_type ?? null, testified: w.testified ?? null, list_rows: colRows,
    }] : [];
    const appearances = rawAppearances.map((a: any) => ({
      ...a, event_id: a.event_id != null ? String(a.event_id) : null, congress: a.congress != null ? Number(a.congress) : null,
      panel: a.panel != null ? (typeof a.panel === 'number' || /^\d+$/.test(String(a.panel)) ? Number(a.panel) : a.panel) : null,
      panel_order: a.panel_order != null ? Number(a.panel_order) : (typeof a.panel === 'number' || /^\d+$/.test(String(a.panel)) ? Number(a.panel) : null),
      display_order: a.display_order != null ? Number(a.display_order) : null, meeting_date: date(a.meeting_date),
      list_rows: uniqueInts(Array.isArray(a.list_rows) ? a.list_rows : []),
    }));
    const organizations = Array.isArray(w.organizations) && w.organizations.length ? w.organizations.map(String) : [...new Set([w.organization, ...appearances.map((a: any) => a.organization)].filter(Boolean).map(String))];
    const positions = Array.isArray(w.positions) && w.positions.length ? w.positions.map(String) : [...new Set([w.position, ...appearances.map((a: any) => a.position)].filter(Boolean).map(String))];
    const listRows = uniqueInts([...(Array.isArray(w.list_rows) ? w.list_rows : []), ...colRows, ...appearances.flatMap((a: any) => a.list_rows ?? [])]);
    return {
      ...w, witness_key: wKey, name_key: w.name_key ?? wKey, event_id: inferredEventId,
      panel_order: w.panel_order != null ? Number(w.panel_order) : null, display_order: w.display_order != null ? Number(w.display_order) : null,
      organization: w.organization ?? organizations[0] ?? null, organizations, position: w.position ?? positions[0] ?? null, positions,
      appearances, list_rows: listRows,
    };
  };

  const normalizeRecording = (r: any) => {
    const rawEventIds = Array.isArray(r.event_ids) ? r.event_ids : Array.isArray(r.meeting_keys) ? r.meeting_keys : [];
    const eventIds = rawEventIds.map(String), meetingKeys = Array.isArray(r.meeting_keys) ? r.meeting_keys.map(String) : eventIds;
    const tracks = (Array.isArray(r.tracks) ? r.tracks : Array.isArray(r.transcripts) ? r.transcripts : []).map((t: any) => ({
      ...t, sha256: t?.sha256 ?? (t?.body instanceof Uint8Array ? hex(t.body) : typeof t?.body === 'string' ? t.body : null),
    }));
    return { ...r, congress: r.congress != null ? Number(r.congress) : null, duration_s: r.duration_s != null ? Number(r.duration_s) : null, event_ids: eventIds, meeting_keys: meetingKeys, tracks, transcripts: Array.isArray(r.transcripts) ? r.transcripts : tracks };
  };

  const normalizeCommittee = (c: any) => {
    const key = String(c.committee_key ?? c.system_code ?? '').toLowerCase(), parentKey = c.parent_key ?? c.parent_system_code ?? null;
    const names = (Array.isArray(c.names) ? c.names : Array.isArray(c.histories) ? c.histories : []).map((n: any) => ({
      ...n, start: date(n.start ?? n.start_date), end: date(n.end ?? n.end_date), start_date: date(n.start_date ?? n.start), end_date: date(n.end_date ?? n.end),
    }));
    const currentName = String(c.current_name ?? c.name ?? names.at(-1)?.name ?? '');
    return {
      ...c, committee_key: key, system_code: String(c.system_code ?? key).toLowerCase(),
      parent_key: parentKey ? String(parentKey).toLowerCase() : null, parent_system_code: parentKey ? String(parentKey).toLowerCase() : null,
      system_codes: Array.isArray(c.system_codes) ? c.system_codes.map((s: any) => String(s).toLowerCase()) : [key].filter(Boolean),
      gpo_codes: Array.isArray(c.gpo_codes) ? c.gpo_codes : [], type: c.type ?? c.committee_type ?? null, committee_type: c.committee_type ?? c.type ?? null,
      current_name: currentName, name: String(c.name ?? currentName), names, histories: names, url: c.url ?? c.website ?? null, website: c.website ?? c.url ?? null,
      subcommittees: Array.isArray(c.subcommittees) ? c.subcommittees : [],
      doc_count: c.doc_count != null ? Number(c.doc_count) : rowsForColumn('committee_keys', key).length,
      hearing_count: c.hearing_count != null ? Number(c.hearing_count) : 0,
    };
  };

  const normalizeMember = (m: any) => {
    const bio = String(m.bioguide_id ?? '');
    const appearances = Array.isArray(m.appearances) ? m.appearances.map((a: any) => ({ ...a, meeting_date: date(a.meeting_date) })) : [];
    const listRows = uniqueInts([...(Array.isArray(m.list_rows) ? m.list_rows : []), ...rowsForColumn('bioguide_ids', bio), ...appearances.flatMap((a: any) => Array.isArray(a.list_rows) ? a.list_rows : [])]);
    return { ...m, bioguide_id: bio, terms: Array.isArray(m.terms) ? m.terms : [], committees: Array.isArray(m.committees) ? m.committees : [], appearances, list_rows: listRows };
  };

  const normalizeRoster = (r: any) => {
    const key = String(r.committee_key ?? r.system_code ?? '').toLowerCase();
    return {
      ...r, committee_key: key, system_code: key, congress: r.congress != null ? Number(r.congress) : null,
      role: r.role ?? r.title ?? 'Member', title: r.title ?? r.role ?? 'Member',
      rank_in_party: r.rank_in_party != null ? Number(r.rank_in_party) : r.rank != null ? Number(r.rank) : null,
      rank: r.rank != null ? Number(r.rank) : r.rank_in_party != null ? Number(r.rank_in_party) : null,
      start_date: date(r.start_date), end_date: date(r.end_date),
      subcommittee_keys: Array.isArray(r.subcommittee_keys) ? r.subcommittee_keys.map((s: any) => String(s).toLowerCase()) : [],
    };
  };

  const normalizeBill = (b: any) => {
    const subjectKey = String(b.subject_key ?? b.bill_id ?? ''), votes = Array.isArray(b.votes) ? b.votes : Array.isArray(b.floor_votes) ? b.floor_votes : [];
    const listRows = uniqueInts([...(Array.isArray(b.list_rows) ? b.list_rows : []), ...rowsForColumn('measure_keys', subjectKey)]);
    const activities = Array.isArray(b.committee_activities) ? b.committee_activities : [];
    const meetingKeys = Array.isArray(b.meeting_keys) ? b.meeting_keys.map(String) : [...new Set(activities.flatMap((a: any) => a.event_id != null ? [String(a.event_id)] : Array.isArray(a.meeting_keys) ? a.meeting_keys.map(String) : []))];
    return {
      ...b, kind: 'bill' as const, subject_key: subjectKey, bill_id: String(b.bill_id ?? subjectKey),
      congress: b.congress != null ? Number(b.congress) : null, bill_number: b.bill_number != null ? Number(b.bill_number) : null,
      introduced_date: date(b.introduced_date ?? b.introduced), introduced: date(b.introduced ?? b.introduced_date),
      latest_action_date: date(b.latest_action_date), status: b.status ?? b.stage ?? null, stage: b.stage ?? b.status ?? null,
      subjects: Array.isArray(b.subjects) ? b.subjects : [], laws: Array.isArray(b.laws) ? b.laws : [],
      committees: Array.isArray(b.committees) ? b.committees : [], committee_activities: activities,
      related_bills: Array.isArray(b.related_bills) ? b.related_bills : [], cbo_estimates: Array.isArray(b.cbo_estimates) ? b.cbo_estimates : [],
      amendments: Array.isArray(b.amendments) ? b.amendments : [],
      amendment_count: b.amendment_count != null ? Number(b.amendment_count) : (Array.isArray(b.amendments) ? b.amendments.length : 0),
      votes, floor_votes: Array.isArray(b.floor_votes) ? b.floor_votes : votes, meeting_keys: meetingKeys, list_rows: listRows,
    };
  };

  const normalizeNomination = (n: any) => {
    const subjectKey = String(n.subject_key ?? n.nomination_id ?? ''), votes = Array.isArray(n.votes) ? n.votes : Array.isArray(n.floor_votes) ? n.floor_votes : [];
    const transcripts = Array.isArray(n.transcripts) ? n.transcripts : [];
    const listRows = uniqueInts([...(Array.isArray(n.list_rows) ? n.list_rows : []), ...rowsForColumn('measure_keys', subjectKey), ...transcripts.map((t: any) => t?.list_row).filter((r: any) => r != null)]);
    return {
      ...n, kind: 'nomination' as const, subject_key: subjectKey, nomination_id: String(n.nomination_id ?? subjectKey),
      congress: n.congress != null ? Number(n.congress) : null, received_date: date(n.received_date ?? n.received), received: date(n.received ?? n.received_date),
      latest_action_date: date(n.latest_action_date), nominees: Array.isArray(n.nominees) ? n.nominees : [], committees: Array.isArray(n.committees) ? n.committees : [],
      transcripts, votes, floor_votes: Array.isArray(n.floor_votes) ? n.floor_votes : votes,
      meeting_keys: Array.isArray(n.meeting_keys) ? n.meeting_keys.map(String) : [], list_rows: listRows,
    };
  };

  const normalizedCache = new Map<string, Promise<any>>();
  const memoized = <T>(key: string, build: () => Promise<T>): Promise<T> => {
    if (!normalizedCache.has(key)) {
      const pending = build();
      normalizedCache.set(key, pending);
      pending.catch(() => { if (normalizedCache.get(key) === pending) normalizedCache.delete(key); });
    }
    return normalizedCache.get(key)!;
  };

  const meetingsIndex = () => memoized('meetings', async () => {
    const rows = (await entity('meetings')).map(normalizeMeeting);
    const byEventId = new Map<string, any[]>(), byDocRow = new Map<number, any[]>(), byCommitteeKey = new Map<string, any[]>(), bySubjectKey = new Map<string, any[]>();
    for (const m of rows) {
      if (m.event_id) pushMap(byEventId, String(m.event_id).toLowerCase(), m);
      for (const r of m.list_rows) pushMap(byDocRow, r, m);
      for (const ck of m.committee_keys) pushMap(byCommitteeKey, String(ck).toLowerCase(), m);
      for (const sk of m.subject_keys) pushMap(bySubjectKey, String(sk).toLowerCase(), m);
    }
    return { rows, byEventId, byDocRow, byCommitteeKey, bySubjectKey };
  });

  const recordingsIndex = () => memoized('recordings', async () => {
    const rows = (await entity('recordings')).map(normalizeRecording), byEventId = new Map<string, any[]>();
    for (const r of rows) for (const ev of r.meeting_keys) pushMap(byEventId, String(ev), r);
    return { rows, byEventId };
  });

  const committeesIndex = () => memoized('committees', async () => {
    const rows = (await entity('committees')).map(normalizeCommittee), byCode = new Map<string, any>(), subcommitteesByParent = new Map<string, any[]>();
    for (const c of rows) {
      for (const k of [c.committee_key, c.system_code, c.thomas_id, c.house_committee_id, c.senate_code, ...c.system_codes]) if (k) byCode.set(String(k).toLowerCase(), c);
      if (c.parent_key && c.committee_key !== c.parent_key) pushMap(subcommitteesByParent, c.parent_key, c);
    }
    return { rows, byCode, subcommitteesByParent };
  });

  const witnessesIndex = () => memoized('witnesses', async () => {
    const rows = (await entity('witnesses')).map(normalizeWitness);
    const byKey = new Map<string, any>(), byEventId = new Map<string, any[]>(), byBioguide = new Map<string, any[]>(), byDocRow = new Map<number, any[]>();
    for (const w of rows) {
      if (w.witness_key) byKey.set(w.witness_key.toLowerCase(), w);
      if (w.name_key) byKey.set(String(w.name_key).toLowerCase(), w);
      if (w.bioguide_id) pushMap(byBioguide, String(w.bioguide_id).toLowerCase(), w);
      for (const a of w.appearances) { const ev = String(a.event_id ?? a.meeting_key ?? ''); if (ev) pushMap(byEventId, ev, w); }
      for (const r of w.list_rows) pushMap(byDocRow, r, w);
    }
    return { rows, byKey, byEventId, byBioguide, byDocRow };
  });

  const membersIndex = () => memoized('members', async () => {
    const rows = (await entity('members')).map(normalizeMember), byBioguide = new Map<string, any>(), byDocRow = new Map<number, any[]>();
    for (const m of rows) {
      if (m.bioguide_id) byBioguide.set(m.bioguide_id.toLowerCase(), m);
      for (const r of m.list_rows) pushMap(byDocRow, r, m);
    }
    return { rows, byBioguide, byDocRow };
  });

  const rostersIndex = () => memoized('rosters', async () => {
    const rows = (await entity('rosters')).map(normalizeRoster), byCommitteeKey = new Map<string, any[]>(), byBioguide = new Map<string, any[]>();
    for (const r of rows) {
      if (r.committee_key) pushMap(byCommitteeKey, r.committee_key, r);
      for (const sk of r.subcommittee_keys) if (sk !== r.committee_key) pushMap(byCommitteeKey, sk, r);
      if (r.bioguide_id) pushMap(byBioguide, String(r.bioguide_id).toLowerCase(), r);
    }
    return { rows, byCommitteeKey, byBioguide };
  });

  const billsIndex = () => memoized('bills', async () => {
    const rows = (await entity('bills')).map(normalizeBill), byKey = new Map<string, any>(), bySponsor = new Map<string, any[]>(), byDocRow = new Map<number, any[]>();
    for (const b of rows) {
      if (b.subject_key) byKey.set(b.subject_key.toLowerCase(), b);
      if (b.bill_id) byKey.set(b.bill_id.toLowerCase(), b);
      if (b.sponsor_bioguide_id) pushMap(bySponsor, String(b.sponsor_bioguide_id).toLowerCase(), b);
      for (const r of b.list_rows) pushMap(byDocRow, r, b);
    }
    return { rows, byKey, bySponsor, byDocRow };
  });

  const nominationsIndex = () => memoized('nominations', async () => {
    const rows = (await entity('nominations')).map(normalizeNomination), byKey = new Map<string, any>(), byDocRow = new Map<number, any[]>();
    for (const n of rows) {
      for (const k of [n.subject_key, n.nomination_id, n.citation]) if (k) byKey.set(String(k).toLowerCase(), n);
      for (const r of n.list_rows) pushMap(byDocRow, r, n);
    }
    return { rows, byKey, byDocRow };
  });

  const prepareQuery = async (rawQuery: any) => {
    const query = { ...rawQuery };
    const takeWanted = (keys: string[]) => {
      const list = keys.flatMap(k => toFilterList(query[k]));
      for (const k of keys) delete query[k];
      return list;
    };
    const committeeWanted = takeWanted(['committee_keys', 'committee_key', 'committee']);
    const meetingWanted = takeWanted(['meeting_keys', 'event_id', 'hearing', 'meeting']);
    const subjectWanted = takeWanted(['measure_keys', 'subject_keys', 'subject_key', 'subject', 'bill', 'nomination']);
    const witnessWanted = takeWanted(['witness_keys', 'witness_key', 'witness']);
    const memberWanted = takeWanted(['bioguide_ids', 'bioguide_id', 'member']);

    const entitySets: Set<number>[] = [];
    if (committeeWanted.length) {
      const wantedLower = new Set(committeeWanted.map(v => v.toLowerCase())), rowSet = new Set<number>();
      for (const key of wantedLower) for (const r of rowsForColumn('committee_keys', key)) rowSet.add(r);
      if (!rowSet.size && files.has('meetings.parquet')) {
        const mIdx = await meetingsIndex();
        for (const key of wantedLower) for (const m of mIdx.byCommitteeKey.get(key) ?? []) for (const r of m.list_rows) rowSet.add(r);
      }
      entitySets.push(rowSet);
    }
    if (meetingWanted.length) {
      const wantedLower = new Set(meetingWanted.map(v => v.toLowerCase())), rowSet = new Set<number>();
      for (const key of wantedLower) for (const r of rowsForColumn('meeting_keys', key)) rowSet.add(r);
      if (files.has('meetings.parquet')) {
        const mIdx = await meetingsIndex();
        for (const key of wantedLower) for (const m of mIdx.byEventId.get(key) ?? []) for (const r of m.list_rows) rowSet.add(r);
      }
      entitySets.push(rowSet);
    }
    if (subjectWanted.length) {
      const wantedLower = new Set(subjectWanted.map(v => v.toLowerCase())), rowSet = new Set<number>();
      for (const key of wantedLower) for (const r of rowsForColumn('measure_keys', key)) rowSet.add(r);
      if (files.has('bills.parquet')) {
        const bIdx = await billsIndex();
        for (const key of wantedLower) for (const r of bIdx.byKey.get(key)?.list_rows ?? []) rowSet.add(r);
      }
      if (files.has('nominations.parquet')) {
        const nIdx = await nominationsIndex();
        for (const key of wantedLower) for (const r of nIdx.byKey.get(key)?.list_rows ?? []) rowSet.add(r);
      }
      entitySets.push(rowSet);
    }
    if (witnessWanted.length) {
      const wantedLower = new Set(witnessWanted.map(v => v.toLowerCase())), rowSet = new Set<number>();
      for (const key of wantedLower) for (const r of rowsForColumn('witness_keys', key)) rowSet.add(r);
      if (files.has('witnesses.parquet')) {
        const wIdx = await witnessesIndex();
        for (const key of wantedLower) for (const r of wIdx.byKey.get(key)?.list_rows ?? []) rowSet.add(r);
      }
      entitySets.push(rowSet);
    }
    if (memberWanted.length) {
      const wantedLower = new Set(memberWanted.map(v => v.toLowerCase())), rowSet = new Set<number>();
      for (const key of wantedLower) for (const r of rowsForColumn('bioguide_ids', key)) rowSet.add(r);
      if (files.has('members.parquet')) {
        const memIdx = await membersIndex();
        for (const key of wantedLower) for (const r of memIdx.byBioguide.get(key)?.list_rows ?? []) rowSet.add(r);
      }
      if (files.has('witnesses.parquet')) {
        const wIdx = await witnessesIndex();
        for (const key of wantedLower) for (const w of wIdx.byBioguide.get(key) ?? []) for (const r of w.list_rows) rowSet.add(r);
      }
      entitySets.push(rowSet);
    }
    let allowedRows: Set<number> | null = null;
    for (const set of entitySets) allowedRows = allowedRows === null ? set : new Set([...allowedRows].filter(r => set.has(r)));
    return { query, allowedRows };
  };

  async function getMeeting(chamberOrEventId: any, maybeEventId?: any, signal?: AbortSignal) {
    const actualSignal = maybeEventId instanceof AbortSignal ? maybeEventId : signal;
    actualSignal?.throwIfAborted();
    const hasChamber = maybeEventId !== undefined && !(maybeEventId instanceof AbortSignal);
    const chamberFilter = hasChamber ? String(chamberOrEventId ?? '').trim().toLowerCase() : null;
    const eventKey = String(hasChamber ? maybeEventId : chamberOrEventId).trim();
    if (!eventKey) return null;
    const [mIdx, recIdx, commIdx, wIdx, bIdx, nIdx] = await Promise.all([meetingsIndex(), recordingsIndex(), committeesIndex(), witnessesIndex(), billsIndex(), nominationsIndex()]);
    const found = (mIdx.byEventId.get(eventKey.toLowerCase()) ?? []).find((m: any) => !chamberFilter || String(m.chamber ?? '').toLowerCase() === chamberFilter);
    const docRows = rowsForColumn('meeting_keys', eventKey);
    if (!found && !docRows.length) return null;
    const baseMeeting = found ?? normalizeMeeting({
      event_id: eventKey, meeting_key: eventKey,
      chamber: chamberFilter ?? (docRows.length ? value('chambers', docRows[0])?.[0] ?? null : null),
      congress: docRows.length ? value('congress', docRows[0]) : null,
      title: `Hearing ${eventKey}`,
      committee_keys: docRows.length ? value('committee_keys', docRows[0]) ?? [] : [],
      subject_keys: docRows.length ? value('measure_keys', docRows[0]) ?? [] : [],
      list_rows: docRows,
    });
    const recordings = recIdx.byEventId.get(eventKey) ?? [];
    const allVideos = [...recordings, ...baseMeeting.videos.filter((v: any) => !recordings.some((r: any) => (v.video_id && r.video_id === v.video_id) || (v.url && r.url === v.url)))];
    const enrichedCommittees = (baseMeeting.committee_keys.length ? baseMeeting.committee_keys : baseMeeting.committees.map((c: any) => c.committee_key ?? c.system_code)).map((code: string) => {
      const lower = String(code ?? '').toLowerCase(), cat = commIdx.byCode.get(lower);
      const inline = baseMeeting.committees.find((c: any) => String(c.committee_key ?? c.system_code ?? '').toLowerCase() === lower);
      const resolvedName = cat ? resolveCommitteeHistoricalName(cat, baseMeeting.meeting_date ?? baseMeeting.congress) : (inline?.name ?? lower.toUpperCase());
      return { ...(cat ?? {}), ...(inline ?? {}), committee_key: lower, system_code: lower, name: inline?.name || resolvedName, resolved_name: resolvedName };
    });
    const mergedWitnesses: any[] = [], seenWitnessKeys = new Set<string>();
    for (const inlineW of baseMeeting.witnesses) {
      const wKey = String(inlineW.witness_key ?? inlineW.name_key ?? inlineW.name ?? '').toLowerCase(), catW = wIdx.byKey.get(wKey);
      const app = catW?.appearances?.find((a: any) => String(a.event_id ?? a.meeting_key ?? '') === eventKey);
      const listRows = uniqueInts([...(Array.isArray(inlineW.list_rows) ? inlineW.list_rows : []), ...(Array.isArray(app?.list_rows) ? app.list_rows : []), ...(catW ? catW.list_rows.filter((r: number) => (value('meeting_keys', r) ?? []).map(String).includes(eventKey)) : [])]);
      if (wKey) seenWitnessKeys.add(wKey);
      if (catW?.witness_key) seenWitnessKeys.add(catW.witness_key.toLowerCase());
      mergedWitnesses.push({
        ...(catW ?? {}), ...inlineW, witness_key: inlineW.witness_key ?? catW?.witness_key ?? null, bioguide_id: inlineW.bioguide_id ?? catW?.bioguide_id ?? null,
        organization: inlineW.organization ?? catW?.organization ?? null, position: inlineW.position ?? catW?.position ?? null,
        panel: inlineW.panel ?? app?.panel ?? null, panel_order: inlineW.panel_order ?? inlineW.panel ?? app?.panel ?? null,
        display_order: inlineW.display_order ?? null, list_rows: listRows, documents: listRows.map(row),
      });
    }
    for (const catW of wIdx.byEventId.get(eventKey) ?? []) {
      if (seenWitnessKeys.has(catW.witness_key.toLowerCase())) continue;
      const app = catW.appearances.find((a: any) => String(a.event_id ?? a.meeting_key ?? '') === eventKey);
      const listRows = uniqueInts([...(Array.isArray(app?.list_rows) ? app.list_rows : []), ...catW.list_rows.filter((r: number) => (value('meeting_keys', r) ?? []).map(String).includes(eventKey))]);
      mergedWitnesses.push({
        ...catW, ...(app ?? {}), witness_key: catW.witness_key, name: catW.name,
        organization: app?.organization ?? catW.organization, position: app?.position ?? catW.position,
        panel: app?.panel ?? catW.panel ?? null, panel_order: app?.panel_order ?? app?.panel ?? null,
        list_rows: listRows, documents: listRows.map(row),
      });
    }
    mergedWitnesses.sort((a, b) => {
      const pa = Number(a.panel_order ?? a.panel ?? 999), pb = Number(b.panel_order ?? b.panel ?? 999);
      if (Number.isFinite(pa) && Number.isFinite(pb) && pa !== pb) return pa - pb;
      const da = Number(a.display_order ?? 999), db = Number(b.display_order ?? 999);
      if (Number.isFinite(da) && Number.isFinite(db) && da !== db) return da - db;
      return String(a.name ?? '').localeCompare(String(b.name ?? ''));
    });
    const allSubjectKeys = [...new Set([...baseMeeting.subject_keys, ...baseMeeting.list_rows.flatMap((r: number) => value('measure_keys', r) ?? [])].map(String).filter(Boolean))];
    const subjects = allSubjectKeys.map(sk => {
      const lower = sk.toLowerCase();
      return bIdx.byKey.get(lower) ?? nIdx.byKey.get(lower) ?? { kind: /^(?:\d+-)?pn-/i.test(sk) ? 'nomination' : 'bill', subject_key: sk, title: null, list_rows: rowsForColumn('measure_keys', sk) };
    });
    return { ...baseMeeting, subject_keys: allSubjectKeys, subjects, committees: enrichedCommittees, recordings, videos: allVideos, witnesses: mergedWitnesses, documents: baseMeeting.list_rows.map(row) };
  }

  async function getCommittee(committeeKey: string, options: any = {}, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const clean = String(committeeKey ?? '').trim().toLowerCase();
    if (!clean) return null;
    const [commIdx, rostIdx, mIdx] = await Promise.all([committeesIndex(), rostersIndex(), meetingsIndex()]);
    const found = commIdx.byCode.get(clean), canonicalKey = found?.committee_key ?? clean;
    const subcommittees = commIdx.subcommitteesByParent.get(canonicalKey) ?? [];
    const explicitSubs = Array.isArray(found?.subcommittees) && found.subcommittees.length ? found.subcommittees : subcommittees;
    const relatedKeys = new Set([canonicalKey, ...subcommittees.map((s: any) => s.committee_key)]);
    const docRows = uniqueInts([...relatedKeys].flatMap(k => rowsForColumn('committee_keys', k)));
    const seenMeetingEvents = new Set<string>(), normMeetings: any[] = [];
    for (const k of relatedKeys) for (const m of mIdx.byCommitteeKey.get(k) ?? []) {
      const ev = String(m.event_id);
      if (!seenMeetingEvents.has(ev)) { seenMeetingEvents.add(ev); normMeetings.push(m); }
    }
    normMeetings.sort((a: any, b: any) => (b.meeting_date ?? '').localeCompare(a.meeting_date ?? '') || String(b.event_id).localeCompare(String(a.event_id)));
    const normRosters = [...(rostIdx.byCommitteeKey.get(canonicalKey) ?? [])].sort((a: any, b: any) =>
      (Number(b.congress ?? 0) - Number(a.congress ?? 0))
      || ((a.majority === true ? 0 : a.majority === false ? 1 : 2) - (b.majority === true ? 0 : b.majority === false ? 1 : 2))
      || ((a.rank_in_party ?? 999) - (b.rank_in_party ?? 999))
      || String(a.name ?? '').localeCompare(String(b.name ?? '')));
    const congresses = [...new Set(normRosters.map((r: any) => r.congress).filter((c: any) => c != null))].sort((a: any, b: any) => b - a);
    const activeCongress = options?.congress != null && options.congress !== '' ? Number(options.congress) : (congresses[0] ?? null);
    const activeRoster = activeCongress != null ? normRosters.filter((r: any) => r.congress === activeCongress) : normRosters;
    const parent = found?.parent_key ? commIdx.byCode.get(found.parent_key) ?? null : null;
    if (!found && !docRows.length && !normMeetings.length && !normRosters.length) return null;
    const base = found ?? normalizeCommittee({ committee_key: canonicalKey, system_code: canonicalKey, name: canonicalKey.toUpperCase(), current_name: canonicalKey.toUpperCase() });
    const resolvedName = resolveCommitteeHistoricalName(base, options?.date ?? options?.congress);
    return {
      ...base, resolved_name: resolvedName || base.current_name, parent, subcommittees: explicitSubs, roster: activeRoster,
      all_rosters: normRosters, roster_congresses: congresses, active_congress: activeCongress,
      hearings: normMeetings, hearing_count: base.hearing_count || normMeetings.length,
      doc_count: docRows.length || base.doc_count, list_rows: docRows, documents: docRows.slice(0, 100).map(row),
    };
  }

  async function getWitness(witnessKey: string, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const clean = String(witnessKey ?? '').trim().toLowerCase();
    if (!clean) return null;
    const [wIdx, mIdx, memIdx] = await Promise.all([witnessesIndex(), meetingsIndex(), membersIndex()]);
    let found = wIdx.byKey.get(clean);
    if (!found) {
      const matchingMeetings = mIdx.rows.filter((m: any) => m.witnesses.some((w: any) => String(w.witness_key ?? w.name_key ?? w.name ?? '').toLowerCase() === clean));
      const colRows = rowsForColumn('witness_keys', clean);
      if (!matchingMeetings.length && !colRows.length) return null;
      const sampleW = matchingMeetings[0]?.witnesses?.find((w: any) => String(w.witness_key ?? w.name_key ?? w.name ?? '').toLowerCase() === clean) ?? {};
      found = normalizeWitness({
        ...sampleW, witness_key: sampleW.witness_key ?? witnessKey, name: sampleW.name ?? witnessKey,
        appearances: matchingMeetings.map((m: any) => ({
          event_id: m.event_id, chamber: m.chamber, congress: m.congress, meeting_date: m.meeting_date, title: m.title,
          list_rows: m.list_rows.filter((r: number) => (value('witness_keys', r) ?? []).map((k: any) => String(k).toLowerCase()).includes(clean)),
        })),
        list_rows: colRows,
      });
    }
    const enrichedAppearances = found.appearances.map((a: any) => {
      const m = (mIdx.byEventId.get(String(a.event_id ?? a.meeting_key ?? '').toLowerCase()) ?? [])[0];
      return {
        ...(m ? { title: m.title, meeting_date: m.meeting_date, chamber: m.chamber, congress: m.congress, committee_keys: m.committee_keys } : {}),
        ...a, meeting_title: a.title ?? m?.title ?? null, committee_keys: a.committee_keys ?? m?.committee_keys ?? [],
      };
    });
    const member = found.bioguide_id ? memIdx.byBioguide.get(String(found.bioguide_id).toLowerCase()) ?? null : null;
    return { ...found, appearances: enrichedAppearances, hearings: enrichedAppearances, member, documents: found.list_rows.map(row) };
  }

  async function getMember(bioguideId: string, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const clean = String(bioguideId ?? '').trim().toLowerCase();
    if (!clean) return null;
    const [memIdx, rostIdx, wIdx, mIdx, bIdx] = await Promise.all([membersIndex(), rostersIndex(), witnessesIndex(), meetingsIndex(), billsIndex()]);
    const found = memIdx.byBioguide.get(clean), rosterEntries = rostIdx.byBioguide.get(clean) ?? [], witnessRecords = wIdx.byBioguide.get(clean) ?? [], sponsoredBills = bIdx.bySponsor.get(clean) ?? [], colRows = rowsForColumn('bioguide_ids', clean);
    if (!found && !rosterEntries.length && !witnessRecords.length && !colRows.length && !sponsoredBills.length) return null;
    const base = found ?? normalizeMember({
      bioguide_id: bioguideId.toUpperCase(), name: rosterEntries[0]?.name ?? witnessRecords[0]?.name ?? bioguideId.toUpperCase(),
      party: rosterEntries[0]?.party ?? null, state: rosterEntries[0]?.state ?? null,
      committees: rosterEntries.map((r: any) => ({ committee_key: r.committee_key, system_code: r.system_code, congress: r.congress, role: r.role, rank_in_party: r.rank_in_party })),
      appearances: witnessRecords.flatMap((w: any) => w.appearances),
      list_rows: uniqueInts([...colRows, ...witnessRecords.flatMap((w: any) => w.list_rows)]),
    });
    const allListRows = uniqueInts([...base.list_rows, ...witnessRecords.flatMap((w: any) => w.list_rows)]);
    const seenEvents = new Set<string>(), hearings: any[] = [];
    for (const app of [...base.appearances, ...witnessRecords.flatMap((w: any) => w.appearances)]) {
      const ev = String(app.event_id ?? app.meeting_key ?? '');
      if (ev && seenEvents.has(ev)) continue;
      if (ev) seenEvents.add(ev);
      const m = (mIdx.byEventId.get(ev.toLowerCase()) ?? [])[0];
      hearings.push({ ...(m ?? {}), ...app, title: app.title ?? m?.title ?? null });
    }
    return { ...base, roster_entries: rosterEntries, witness_records: witnessRecords, sponsored_bills: sponsoredBills, hearings, list_rows: allListRows, documents: allListRows.map(row) };
  }

  const resolveSubjectRecord = async (subjectKey: string, indexLoader: () => Promise<{ byKey: Map<string, any> }>, signal?: AbortSignal) => {
    signal?.throwIfAborted();
    const clean = String(subjectKey ?? '').trim().toLowerCase();
    if (!clean) return null;
    const [sIdx, mIdx] = await Promise.all([indexLoader(), meetingsIndex()]);
    const found = sIdx.byKey.get(clean);
    if (!found) return null;
    const canonical = found.subject_key.toLowerCase(), seenEvents = new Set<string>(), normMeetings: any[] = [];
    for (const m of [...(mIdx.bySubjectKey.get(canonical) ?? []), ...(mIdx.bySubjectKey.get(clean) ?? [])]) {
      const ev = String(m.event_id);
      if (!seenEvents.has(ev)) { seenEvents.add(ev); normMeetings.push(m); }
    }
    for (const ev of found.meeting_keys) {
      const m = (mIdx.byEventId.get(String(ev).toLowerCase()) ?? [])[0];
      if (m && !seenEvents.has(String(m.event_id))) { seenEvents.add(String(m.event_id)); normMeetings.push(m); }
    }
    const meetingKeys = [...new Set([...found.meeting_keys, ...normMeetings.map((m: any) => String(m.event_id))])];
    return { ...found, meeting_keys: meetingKeys, hearings: normMeetings, documents: found.list_rows.map(row) };
  };

  const getBill = (subjectKey: string, signal?: AbortSignal) => resolveSubjectRecord(subjectKey, billsIndex, signal);
  const getNomination = (subjectKey: string, signal?: AbortSignal) => resolveSubjectRecord(subjectKey, nominationsIndex, signal);

  async function getSubject(subjectKey: string, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const clean = String(subjectKey ?? '').trim();
    if (!clean) return null;
    const bill = await getBill(clean, signal);
    if (bill) return bill;
    const nomination = await getNomination(clean, signal);
    if (nomination) return nomination;
    const lower = clean.toLowerCase(), docRows = rowsForColumn('measure_keys', lower), mIdx = await meetingsIndex();
    const seenEvents = new Set<string>(), hearings: any[] = [];
    for (const m of [...(mIdx.bySubjectKey.get(lower) ?? []), ...docRows.flatMap(r => mIdx.byDocRow.get(r) ?? [])]) {
      const ev = String(m.event_id);
      if (!seenEvents.has(ev)) { seenEvents.add(ev); hearings.push(m); }
    }
    if (!docRows.length && !hearings.length) return null;
    const isNom = /^(?:\d+-)?pn-/i.test(clean), congMatch = /^(\d+)-/.exec(clean);
    return {
      kind: isNom ? ('nomination' as const) : ('bill' as const), subject_key: clean,
      bill_id: isNom ? undefined : clean, nomination_id: isNom ? clean : undefined,
      congress: congMatch ? Number(congMatch[1]) : (docRows.length ? value('congress', docRows[0]) : null),
      title: null, status: null, committees: [...new Set(docRows.flatMap(r => value('committee_keys', r) ?? []))],
      committee_activities: [], cbo_estimates: [], votes: [], floor_votes: [], amendments: [], amendment_count: 0,
      related_bills: [], nominees: [], meeting_keys: hearings.map((m: any) => String(m.event_id)), hearings,
      list_rows: docRows, documents: docRows.map(row),
    };
  }

  async function listEntities(kind: string, options: any = {}, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const offset = Math.max(0, Number(options.offset) || 0), limit = Math.min(1000, Math.max(1, Number(options.limit) || 100));
    const text = String(options.q ?? options.text ?? '').trim().toLowerCase();
    const rawCong = options.congress, congressFilter = rawCong != null && rawCong !== '' && rawCong !== 'all' ? Number(rawCong) : null;
    const chamberFilter = options.chamber && options.chamber !== 'all' ? String(options.chamber).toLowerCase() : null;
    const committeeFilter = options.committee ? String(options.committee).toLowerCase() : null;
    let items: any[] = [];
    switch (kind) {
      case 'meetings': items = (await meetingsIndex()).rows; break;
      case 'witnesses': items = (await witnessesIndex()).rows; break;
      case 'recordings': items = (await recordingsIndex()).rows; break;
      case 'committees': items = (await committeesIndex()).rows; break;
      case 'members': items = (await membersIndex()).rows; break;
      case 'rosters': items = (await rostersIndex()).rows; break;
      case 'bills': items = (await billsIndex()).rows; break;
      case 'nominations': items = (await nominationsIndex()).rows; break;
      case 'subjects': {
        const [bIdx, nIdx] = await Promise.all([billsIndex(), nominationsIndex()]);
        items = [...bIdx.rows, ...nIdx.rows];
        break;
      }
      default: throw new Error(`Unknown archive entity kind: ${kind}`);
    }
    const filtered = items.filter((item: any) => {
      if (congressFilter != null) {
        if (item.congress != null) { if (Number(item.congress) !== congressFilter) return false; }
        else if (Array.isArray(item.terms) && item.terms.length) { if (!item.terms.some((t: any) => Number(t?.congress) === congressFilter)) return false; }
        else if (Array.isArray(item.appearances) && item.appearances.some((a: any) => a?.congress != null)) { if (!item.appearances.some((a: any) => Number(a?.congress) === congressFilter)) return false; }
      }
      if (chamberFilter) {
        if (item.chamber) { if (String(item.chamber).toLowerCase() !== chamberFilter) return false; }
        else if (Array.isArray(item.terms) && item.terms.length && !item.terms.some((t: any) => String(t?.chamber ?? '').toLowerCase() === chamberFilter)) return false;
      }
      if (committeeFilter) {
        const keys = [
          item.committee_key, item.system_code, item.parent_key,
          ...(Array.isArray(item.committee_keys) ? item.committee_keys : []),
          ...(Array.isArray(item.committees) ? item.committees.map((c: any) => typeof c === 'string' ? c : (c?.committee_key ?? c?.system_code)) : []),
          ...(Array.isArray(item.appearances) ? item.appearances.flatMap((a: any) => Array.isArray(a?.committee_keys) ? a.committee_keys : []) : []),
        ].filter(Boolean).map((k: any) => String(k).toLowerCase());
        if (!keys.includes(committeeFilter)) return false;
      }
      if (text) {
        const hay = [
          item.title, item.short_title, item.description, item.name, item.current_name, item.organization,
          ...(Array.isArray(item.organizations) ? item.organizations : []), item.position, ...(Array.isArray(item.positions) ? item.positions : []),
          item.subject_key, item.bill_id, item.nomination_id, item.citation, item.bioguide_id, item.committee_key, item.event_id,
          item.sponsor_name, item.policy_area, item.state, item.party,
        ].filter(Boolean).join(' ').toLowerCase();
        if (!hay.includes(text)) return false;
      }
      return true;
    });
    return { total: filtered.length, rows: filtered.slice(offset, offset + limit), offset, next: offset + limit < filtered.length ? offset + limit : null };
  }

  async function openDocument(indexOrKey: number | string, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const index = typeof indexOrKey === 'string' && !/^\d+$/.test(indexOrKey) ? await ctx.resolve(indexOrKey) : Number(indexOrKey);
    if (index === null || !Number.isSafeInteger(index) || index < 0 || index >= count) throw new Error('Archive document not found.');
    const [entry, versions, mIdx, recIdx, commIdx, wIdx, memIdx, bIdx, nIdx] = await Promise.all([
      ctx.entry(index, signal), ctx.versions(index, signal), meetingsIndex(), recordingsIndex(), committeesIndex(), witnessesIndex(), membersIndex(), billsIndex(), nominationsIndex(),
    ]);
    const doc = entry.document, seenMeetingEvents = new Set<string>(), docMeetings: any[] = [];
    const addMeeting = (m: any) => {
      const ev = String(m.event_id);
      if (!seenMeetingEvents.has(ev)) { seenMeetingEvents.add(ev); docMeetings.push({ ...m, recordings: recIdx.byEventId.get(ev) ?? [] }); }
    };
    for (const mk of doc.meeting_keys ?? []) for (const m of mIdx.byEventId.get(String(mk).toLowerCase()) ?? []) addMeeting(m);
    for (const m of mIdx.byDocRow.get(index) ?? []) addMeeting(m);

    const docCommitteeKeys = new Set([...(doc.committee_keys ?? []).map((k: any) => String(k).toLowerCase()), ...docMeetings.flatMap((m: any) => (m.committee_keys ?? []).map((k: any) => String(k).toLowerCase()))]);
    const seenCommitteeKeys = new Set<string>(), docCommittees: any[] = [];
    for (const ck of docCommitteeKeys) {
      const c = commIdx.byCode.get(ck);
      if (c && !seenCommitteeKeys.has(c.committee_key)) {
        seenCommitteeKeys.add(c.committee_key);
        docCommittees.push({ ...c, resolved_name: resolveCommitteeHistoricalName(c, doc.document_date ?? doc.congress) });
      }
    }

    const docSubjectKeys = new Set([...(doc.measure_keys ?? []).map((k: any) => String(k).toLowerCase()), ...docMeetings.flatMap((m: any) => (m.subject_keys ?? []).map((k: any) => String(k).toLowerCase()))]);
    const seenSubjects = new Set<string>(), docSubjects: any[] = [];
    const addSubject = (s: any) => { if (s && !seenSubjects.has(String(s.subject_key).toLowerCase())) { seenSubjects.add(String(s.subject_key).toLowerCase()); docSubjects.push(s); } };
    for (const sk of docSubjectKeys) addSubject(bIdx.byKey.get(sk));
    for (const b of bIdx.byDocRow.get(index) ?? []) addSubject(b);
    for (const sk of docSubjectKeys) addSubject(nIdx.byKey.get(sk));
    for (const n of nIdx.byDocRow.get(index) ?? []) addSubject(n);

    const seenWitnesses = new Set<string>(), docWitnesses: any[] = [];
    const addWitness = (w: any) => { if (w && !seenWitnesses.has(String(w.witness_key).toLowerCase())) { seenWitnesses.add(String(w.witness_key).toLowerCase()); docWitnesses.push(w); } };
    for (const wk of doc.witness_keys ?? []) addWitness(wIdx.byKey.get(String(wk).toLowerCase()));
    for (const w of wIdx.byDocRow.get(index) ?? []) addWitness(w);

    const seenMembers = new Set<string>(), docMembers: any[] = [];
    const addMember = (m: any) => { if (m && !seenMembers.has(String(m.bioguide_id).toLowerCase())) { seenMembers.add(String(m.bioguide_id).toLowerCase()); docMembers.push(m); } };
    for (const bio of doc.bioguide_ids ?? []) addMember(memIdx.byBioguide.get(String(bio).toLowerCase()));
    for (const m of memIdx.byDocRow.get(index) ?? []) addMember(m);

    return { ...entry, versions, meetings: docMeetings, committees: docCommittees, subjects: docSubjects, witnesses: docWitnesses, members: docMembers };
  }

  return { prepareQuery, getMeeting, getCommittee, getWitness, getMember, getBill, getNomination, getSubject, listEntities, openDocument };
}
