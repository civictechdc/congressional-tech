import {ArchiveReleaseChangedError, awaitShared} from './cache.ts';
import {congressPeriod, resolveCommitteeName} from '../archive/record-history.ts';

export type RelationState = 'ready' | 'missing' | 'unavailable';

const hex = (value: Uint8Array) => [...value].map(v => v.toString(16).padStart(2, '0')).join('');
const date = (value: any) => value instanceof Date ? value.toISOString().slice(0, 10) : value == null ? null : String(value).slice(0, 10);
const instant = (value: any) => value instanceof Date ? value.toISOString() : value == null ? null : String(value);
const termOverlapsCongress = (term: any, congress: number) => {
  const {start, end} = congressPeriod(congress);
  return term.start != null && term.start < end && (term.end == null || term.end > start);
};

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
  entityHasColumn: (name: string, column: string) => Promise<boolean>;
  meetingCoverage?: (eventId: string) => Promise<any[]>;
  witnessKeyMap?: (key: string) => Promise<{ key: string; status: string; successor: string | null; basis: string | null; candidates: string[] } | null>;
}

const toFilterList = (val: any): string[] =>
  val == null || val === '' ? [] : Array.isArray(val) ? val.flatMap(v => v != null && v !== '' ? [String(v)] : []) : [String(val)];

const pushMap = <K, V>(map: Map<K, V[]>, key: K, item: V) => {
  let list = map.get(key);
  if (!list) { list = []; map.set(key, list); }
  list.push(item);
};

const TRANSCRIPT_SOURCE_LABELS: Record<string, string> = {
  printed_hearing: 'Printed hearing',
  committee_transcript: 'Committee transcript',
  captions: 'Captions or subtitles',
};

export function transcriptSourceLabel(value: unknown): string {
  const source = typeof value === 'string' ? value.trim() : '';
  if (!source) return 'Source not stated';
  return Object.hasOwn(TRANSCRIPT_SOURCE_LABELS, source) ? TRANSCRIPT_SOURCE_LABELS[source] : source;
}

/** The labelled sources of a meeting's transcripts (ct-1i4q), in the order the release lists them. */
export function transcriptSourceLabels(transcripts: unknown): string[] {
  if (!Array.isArray(transcripts)) return [];
  const labels = transcripts.map((t: any) => transcriptSourceLabel(t?.source));
  return [...new Set(labels)];
}

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
    const eventKey = String(m.event_id ?? '');
    const mDate = date(m.meeting_date);
    const transcriptRows = Array.isArray(m.transcripts) ? m.transcripts.map((t: any) => t?.list_row).filter((r: any) => r != null) : [];
    const listRows = uniqueInts([...rowsForColumn('meeting_keys', eventKey), ...transcriptRows]);
    const committeeObjs = (m.committees ?? []).map((c: any) => ({ ...c, committee_key: c.system_code }));
    const committeeKeys = committeeObjs.flatMap((c: any) => c.system_code == null ? [] : [String(c.system_code).toLowerCase()]);
    const subjectKeys = (m.subject_keys ?? []).map(String);
    const rawSittings = Array.isArray(m.sittings) ? m.sittings : [];
    const sittings = rawSittings.map((s: any) => {
      const start = instant(s.start), end = instant(s.end);
      const bldgRoom = [s?.building, s?.room].filter(Boolean).join(' ');
      const place = s.place ?? ([bldgRoom, s.address].filter(Boolean).join(', ') || null);
      return { ...s, start, end, place };
    });
    return {
      ...m, event_id: eventKey, congress: m.congress == null ? null : Number(m.congress), session: m.session != null ? Number(m.session) : null,
      meeting_key: eventKey, meeting_date: mDate, committees: committeeObjs, committee_keys: committeeKeys, subject_keys: subjectKeys,
      transcript_sources: transcriptSourceLabels(m.transcripts),
      sittings,
      transcripts: Array.isArray(m.transcripts) ? m.transcripts.map((t: any) => ({ ...t, list_row: t?.list_row != null ? Number(t.list_row) : null })) : [],
      videos: (m.videos ?? []).map((v: any) => ({ ...v, title: v.name ?? null })),
      witnesses: [], list_rows: listRows,
    };
  };

  const normalizeWitness = (w: any) => {
    const wKey = String(w.witness_key ?? '');
    const eventId = w.event_id == null ? null : String(w.event_id);
    const colRows = rowsForColumn('witness_keys', wKey);
    const appearances = (eventId || w.occasion || w.package_id || w.page_url) ? [{
      event_id: eventId, occasion: w.occasion ?? null, package_id: w.package_id ?? null, page_url: w.page_url ?? null,
      position: w.position ?? null, organization: w.organization ?? null, on_behalf_of: w.on_behalf_of ?? null, location: w.location ?? null,
      panel: w.panel ?? null, panel_order: w.panel_order != null ? Number(w.panel_order) : null, display_order: w.display_order != null ? Number(w.display_order) : null,
      witness_type: w.witness_type ?? null, testified: w.testified ?? null, list_rows: colRows,
    }] : [];
    return {
      ...w, witness_key: wKey, event_id: eventId,
      panel_order: w.panel_order != null ? Number(w.panel_order) : null, display_order: w.display_order != null ? Number(w.display_order) : null,
      organizations: w.organization == null ? [] : [w.organization], positions: w.position == null ? [] : [w.position],
      appearances, list_rows: colRows,
    };
  };

  const normalizeRecording = (r: any) => {
    const eventIds = (r.event_ids ?? []).map(String);
    const tracks = (r.tracks ?? []).map((t: any) => ({
      ...t, sha256: t.body instanceof Uint8Array ? hex(t.body) : null,
    }));
    return { ...r, event_ids: eventIds, meeting_keys: eventIds, tracks, transcripts: tracks };
  };

  const normalizeCommittee = (c: any) => {
    const key = String(c.system_code ?? '').toLowerCase(), parentKey = c.parent_system_code ?? null;
    const names = (c.names ?? []).map((n: any) => ({
      ...n, start: date(n.start), end: date(n.end),
    }));
    const currentName = c.name ?? '';
    const docRows = rowsForColumn('committee_keys', key);
    return {
      ...c, committee_key: key, system_code: key,
      parent_key: parentKey ? String(parentKey).toLowerCase() : null, parent_system_code: parentKey ? String(parentKey).toLowerCase() : null,
      type: c.committee_type ?? null,
      current_name: currentName, names, url: c.website ?? null,
      list_rows: docRows,
      doc_count: docRows.length,
    };
  };

  const normalizeMember = (m: any) => {
    const bio = String(m.bioguide_id ?? '');
    const terms = (Array.isArray(m.terms) ? m.terms : []).map((t: any) => {
      const start = date(t.start), end = date(t.end);
      return { ...t, start, end, start_year: start ? Number(start.slice(0, 4)) : null,
        end_year: end ? Number(end.slice(0, 4)) : null };
    });
    const latestTerm = terms[0];
    const listRows = rowsForColumn('bioguide_ids', bio);
    return {
      ...m,
      bioguide_id: bio,
      party: latestTerm?.party ?? null,
      state: latestTerm?.state ?? null,
      district: latestTerm?.district == null ? null : Number(latestTerm.district),
      chamber: latestTerm?.chamber ?? null,
      terms,
      appearances: [],
      list_rows: listRows,
    };
  };

  const normalizeRoster = (r: any) => {
    const key = String(r.system_code ?? '').toLowerCase();
    return {
      ...r, committee_key: key, system_code: key, congress: r.congress != null ? Number(r.congress) : null,
      role: r.title ?? null, rank_in_party: r.rank == null ? null : Number(r.rank),
      rank: r.rank == null ? null : Number(r.rank),
    };
  };

  const normalizeBill = (b: any) => {
    const subjectKey = String(b.bill_id ?? ''), votes = b.floor_votes ?? [];
    const listRows = rowsForColumn('measure_keys', subjectKey);
    const activities = Array.isArray(b.committee_activities) ? b.committee_activities : [];
    const parsedCong = /^(\d+)-/.exec(subjectKey)?.[1];
    const cboEstimates = (Array.isArray(b.cbo_estimates) ? b.cbo_estimates : []).map((c: any) => ({
      ...c,
      date: date(c.date), title: c.description ?? null,
      url: c.publication_id ? `https://www.cbo.gov/publication/${c.publication_id}` : null,
    }));
    const amendments = (Array.isArray(b.amendments) ? b.amendments : []).map((a: any) => ({
      ...a,
      amendment_id: a?.amendment_id ?? null,
      sponsor_bioguide_id: a?.sponsor_bioguide_id ?? null,
      date: date(a.latest_action_date),
    }));
    return {
      ...b, kind: 'bill' as const, subject_key: subjectKey,
      congress: parsedCong ? Number(parsedCong) : null,
      introduced_date: date(b.introduced), introduced: date(b.introduced),
      latest_action_date: date(b.latest_action_date), status: b.stage ?? null,
      committees: Array.isArray(b.committees) ? b.committees : [], committee_activities: activities,
      related_bills: Array.isArray(b.related_bills) ? b.related_bills : [], cbo_estimates: cboEstimates,
      amendments,
      amendment_count: amendments.length,
      votes, meeting_keys: [], list_rows: listRows,
    };
  };

  const normalizeNomination = (n: any) => {
    const subjectKey = String(n.nomination_id ?? ''), votes = n.floor_votes ?? [];
    const transcripts = Array.isArray(n.transcripts) ? n.transcripts : [];
    const listRows = rowsForColumn('measure_keys', subjectKey);
    const parsedCong = /^(\d+)-/.exec(subjectKey)?.[1];
    return {
      ...n, kind: 'nomination' as const, subject_key: subjectKey,
      congress: parsedCong ? Number(parsedCong) : null,
      received_date: date(n.received), received: date(n.received),
      latest_action_date: date(n.latest_action_date), nominees: null, committees: Array.isArray(n.committees) ? n.committees : [],
      committee_activities: n.committee_activities ?? null,
      transcripts, votes, meeting_keys: [], list_rows: listRows,
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

  const optional = async <T>(name: string, load: () => Promise<T>, signal?: AbortSignal) => {
    if (!files.has(name + '.parquet')) return { state: 'missing' as const, data: null };
    try {
      return { state: 'ready' as const, data: await awaitShared(load(), signal) };
    } catch (error) {
      signal?.throwIfAborted();
      if (error instanceof ArchiveReleaseChangedError) throw error;
      return { state: 'unavailable' as const, data: null };
    }
  };

  const sortSubjects = (a: any, b: any) =>
    String(b.latest_action_date ?? b.introduced_date ?? b.received_date ?? '').localeCompare(String(a.latest_action_date ?? a.introduced_date ?? a.received_date ?? ''))
    || ((b.congress ?? 0) - (a.congress ?? 0))
    || (b.list_rows.length - a.list_rows.length)
    || String(a.subject_key ?? '').localeCompare(String(b.subject_key ?? ''));

  const meetingsIndex = () => memoized('meetings', async () => {
    const rows = (await entity('meetings')).map(normalizeMeeting);
    rows.sort((a: any, b: any) => String(b.meeting_date ?? '').localeCompare(String(a.meeting_date ?? '')) || String(b.event_id ?? '').localeCompare(String(a.event_id ?? '')));
    const byEventId = new Map<string, any[]>(), byDocRow = new Map<number, any[]>(), byCommitteeKey = new Map<string, any[]>(), bySubjectKey = new Map<string, any[]>();
    for (const m of rows) {
      if (m.event_id) pushMap(byEventId, String(m.event_id).toLowerCase(), m);
      for (const r of m.list_rows) pushMap(byDocRow, r, m);
      for (const ck of m.committee_keys) pushMap(byCommitteeKey, String(ck).toLowerCase(), m);
      for (const sk of m.subject_keys) pushMap(bySubjectKey, String(sk).toLowerCase(), m);
    }
    return { rows, byEventId, byDocRow, byCommitteeKey, bySubjectKey };
  });

  const videosIndex = () => memoized('videos', async () => new Map<string, any>(
    (await entity('videos')).map(v => [v.video_key, {
      ...v, duration_seconds: v.duration_seconds == null ? null : Number(v.duration_seconds),
    }]),
  ));

  const recordingsIndex = () => memoized('recordings', async () => {
    const rows = (await entity('recordings')).map(normalizeRecording), byEventId = new Map<string, any[]>();
    for (const r of rows) for (const ev of r.meeting_keys) pushMap(byEventId, String(ev), r);
    return { rows, byEventId };
  });

  const withVideoDuration = (recording: any, videos: Map<string, any> | null) => ({
    ...recording, duration_seconds: videos?.get(recording.video_key)?.duration_seconds ?? null,
  });

  const recordingMatchesIndex = () => memoized('recording_matches', async () => {
    if (!await ctx.entityHasColumn('recording_matches', 'meeting_links')) {
      throw new Error('Archive recording_matches is missing meeting_links.');
    }
    const rows = await entity('recording_matches');
    const byEventId = new Map<string, any[]>();
    for (const observation of rows) {
      if (!Array.isArray(observation.meeting_links)) {
        throw new Error('Archive recording_matches meeting_links must be a list.');
      }
      for (const link of observation.meeting_links) {
        pushMap(byEventId, String(link.event_id), { ...observation, meeting_link: link });
      }
    }
    return { byEventId };
  });

  const committeesIndex = () => memoized('committees', async () => {
    const rows = (await entity('committees')).map(normalizeCommittee), byCode = new Map<string, any>(), subcommitteesByParent = new Map<string, any[]>();
    rows.sort((a: any, b: any) =>
      (Number(Boolean(b.is_current)) - Number(Boolean(a.is_current)))
      || ((b.list_rows?.length ?? b.doc_count ?? 0) - (a.list_rows?.length ?? a.doc_count ?? 0))
      || String(a.name ?? '').localeCompare(String(b.name ?? '')));
    for (const c of rows) {
      byCode.set(c.system_code, c);
      if (c.parent_key && c.committee_key !== c.parent_key) pushMap(subcommitteesByParent, c.parent_key, c);
    }
    return { rows, byCode, subcommitteesByParent };
  });

  const witnessesIndex = () => memoized('witnesses', async () => {
    const rows = (await entity('witnesses')).map(normalizeWitness);
    rows.sort((a: any, b: any) => (b.list_rows.length - a.list_rows.length) || (b.appearances.length - a.appearances.length) || String(a.name ?? '').localeCompare(String(b.name ?? '')));
    const byKey = new Map<string, any>(), byEventId = new Map<string, any[]>(), byBioguide = new Map<string, any[]>(), byDocRow = new Map<number, any[]>();
    const currentRows = rows.filter(w => w.superseded_by == null);
    for (const w of rows) {
      if (w.witness_key) byKey.set(w.witness_key.toLowerCase(), w);
      if (w.bioguide_id) pushMap(byBioguide, String(w.bioguide_id).toLowerCase(), w);
      for (const ev of new Set(w.appearances.map((a: any) => String(a.event_id ?? '')))) {
        if (ev) pushMap(byEventId, String(ev), w);
      }
      for (const r of w.list_rows) pushMap(byDocRow, r, w);
    }
    return { rows, currentRows, byKey, byEventId, byBioguide, byDocRow };
  });

  const membersIndex = () => memoized('members', async () => {
    const rows = (await entity('members')).map(normalizeMember), byBioguide = new Map<string, any>(), byDocRow = new Map<number, any[]>();
    rows.sort((a: any, b: any) => (b.list_rows.length - a.list_rows.length) || (b.appearances.length - a.appearances.length) || String(a.name ?? '').localeCompare(String(b.name ?? '')));
    for (const m of rows) {
      if (m.bioguide_id) byBioguide.set(m.bioguide_id.toLowerCase(), m);
      for (const r of m.list_rows) pushMap(byDocRow, r, m);
    }
    return { rows, byBioguide, byDocRow };
  });

  const rostersIndex = () => memoized('rosters', async () => {
    const rows = (await entity('rosters')).map(normalizeRoster), byCommitteeKey = new Map<string, any[]>(), byBioguide = new Map<string, any[]>();
    for (const r of rows) {
      pushMap(byCommitteeKey, r.system_code, r);
      if (r.bioguide_id) pushMap(byBioguide, String(r.bioguide_id).toLowerCase(), r);
    }
    return { rows, byCommitteeKey, byBioguide };
  });

  const billsIndex = () => memoized('bills', async () => {
    const [rawBills, memIdx] = await Promise.all([
      entity('bills'),
      files.has('members.parquet') ? membersIndex().catch(() => ({ byBioguide: new Map() })) : Promise.resolve({ byBioguide: new Map() }),
    ]);
    const rows = rawBills.map(raw => {
      const b = normalizeBill(raw);
      const sponsorBio = b.sponsor_bioguide_id ? String(b.sponsor_bioguide_id).toLowerCase() : '';
      const mem = sponsorBio ? memIdx.byBioguide.get(sponsorBio) : null;
      const amendments = b.amendments.map((a: any) => {
        const abio = a.sponsor_bioguide_id ? String(a.sponsor_bioguide_id).toLowerCase() : '';
        const amem = abio ? memIdx.byBioguide.get(abio) : null;
        return { ...a, sponsor_name: a.sponsor_name ?? amem?.name ?? null };
      });
      return {
        ...b,
        sponsor_name: b.sponsor_name ?? mem?.name ?? null,
        sponsor_party: b.sponsor_party ?? mem?.party ?? null,
        sponsor_state: b.sponsor_state ?? mem?.state ?? null,
        amendments,
      };
    });
    rows.sort(sortSubjects);
    const byKey = new Map<string, any>(), bySponsor = new Map<string, any[]>(), byDocRow = new Map<number, any[]>();
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
    rows.sort(sortSubjects);
    for (const n of rows) {
      byKey.set(n.nomination_id.toLowerCase(), n);
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
    const [mIdx, recordings, committees, witnesses, bills, nominations, coverage, matches, videos] = await Promise.all([
      awaitShared(meetingsIndex(), actualSignal),
      optional('recordings', recordingsIndex, actualSignal),
      optional('committees', committeesIndex, actualSignal),
      optional('witnesses', witnessesIndex, actualSignal),
      optional('bills', billsIndex, actualSignal),
      optional('nominations', nominationsIndex, actualSignal),
      optional('meeting_coverage', () => ctx.meetingCoverage!(eventKey), actualSignal),
      optional('recording_matches', recordingMatchesIndex, actualSignal),
      optional('videos', videosIndex, actualSignal),
    ]);
    const { data: recIdx } = recordings, { data: commIdx } = committees, { data: wIdx } = witnesses;
    const { data: bIdx } = bills, { data: nIdx } = nominations;
    const candidates = mIdx.byEventId.get(eventKey.toLowerCase()) ?? [];
    const found = candidates.find((m: any) => !chamberFilter || String(m.chamber ?? '').toLowerCase() === chamberFilter);
    if (candidates.length && !found) return null;
    const docRows = rowsForColumn('meeting_keys', eventKey);
    if (!found && !docRows.length) return null;
    const baseMeeting = found ?? normalizeMeeting({
      event_id: eventKey,
      chamber: null, chamber_basis: 'meeting_detail_missing',
      congress: null,
      title: `Hearing ${eventKey}`,
      committees: (docRows.length ? value('committee_keys', docRows[0]) ?? [] : []).map((system_code: string) => ({system_code})),
      subject_keys: docRows.length ? value('measure_keys', docRows[0]) ?? [] : [],
    });
    const recRows = (recIdx?.byEventId.get(eventKey) ?? []).map(r => withVideoDuration(r, videos.data));
    const seenVideoKeys = new Set<string>();
    const dedupedVideos: any[] = [];
    for (const v of baseMeeting.videos) {
      const vk = String(v.video_key || v.url || '');
      if (vk && seenVideoKeys.has(vk)) continue;
      if (vk) seenVideoKeys.add(vk);
      dedupedVideos.push(withVideoDuration(v, videos.data));
    }
    const sameRecording = (a: any, b: any) => a.video_key && b.video_key
      ? a.video_key === b.video_key
      : Boolean(a.url && a.url === b.url);
    const joined = new Set<any>();
    const publisherVideos = dedupedVideos.filter(v => !recRows.some(r => r.url && sameRecording(v, r))).map(v => {
      const captionRow = v.video_key && recRows.find(r => !r.url && r.video_key === v.video_key);
      if (!captionRow) return v;
      joined.add(captionRow);
      return { ...v, tracks: captionRow.tracks };
    });
    const allVideos = [
      ...recRows.filter(r => !joined.has(r)),
      ...publisherVideos,
    ];
    const enrichedCommittees = baseMeeting.committees.map((inline: any) => {
      const lower = inline.system_code == null ? null : String(inline.system_code).toLowerCase();
      const cat = lower == null ? null : commIdx?.byCode.get(lower);
      const resolvedName = cat ? resolveCommitteeName(cat, baseMeeting.meeting_date ?? baseMeeting.congress) : lower?.toUpperCase() ?? null;
      return { ...(cat ?? {}), ...inline, committee_key: lower, system_code: lower, name: resolvedName, resolved_name: resolvedName };
    });
    const mergedWitnesses: any[] = [];
    for (const catW of wIdx?.byEventId.get(eventKey) ?? []) {
      if (catW.superseded_by != null) continue;
      for (const app of catW.appearances) {
        if (String(app.event_id ?? '') !== eventKey) continue;
        const listRows = uniqueInts([...app.list_rows, ...catW.list_rows.filter((r: number) => (value('meeting_keys', r) ?? []).map(String).includes(eventKey))]);
        mergedWitnesses.push({
          ...catW, ...app, witness_key: catW.witness_key, name: catW.name,
          organization: app.organization ?? catW.organization, position: app.position ?? catW.position,
          panel: app.panel ?? null, panel_order: app.panel_order ?? null,
          list_rows: listRows, documents: listRows.map(row),
        });
      }
    }
    mergedWitnesses.sort((a, b) => {
      const pa = Number(a.panel_order ?? 999), pb = Number(b.panel_order ?? 999);
      if (Number.isFinite(pa) && Number.isFinite(pb) && pa !== pb) return pa - pb;
      const da = Number(a.display_order ?? 999), db = Number(b.display_order ?? 999);
      if (Number.isFinite(da) && Number.isFinite(db) && da !== db) return da - db;
      return String(a.name ?? '').localeCompare(String(b.name ?? ''));
    });
    const allSubjectKeys = [...new Set([...baseMeeting.subject_keys, ...baseMeeting.list_rows.flatMap((r: number) => value('measure_keys', r) ?? [])].map(String).filter(Boolean))];
    const subjects = allSubjectKeys.map(sk => {
      const lower = sk.toLowerCase();
      return bIdx?.byKey.get(lower) ?? nIdx?.byKey.get(lower) ?? { kind: /^(?:\d+-)?pn-/i.test(sk) ? 'nomination' : 'bill', subject_key: sk, title: null, list_rows: rowsForColumn('measure_keys', sk) };
    });
    return {
      ...baseMeeting, subject_keys: allSubjectKeys, subjects, committees: enrichedCommittees,
      recordings: recRows, videos: allVideos, witnesses: mergedWitnesses, documents: baseMeeting.list_rows.map(row),
      relation_states: { recordings: recordings.state, committees: committees.state, witnesses: witnesses.state,
        bills: bills.state, nominations: nominations.state, coverage: coverage.state, videos: videos.state },
      recording_observations: matches.data?.byEventId.get(eventKey) ?? [],
      recording_associations_state: matches.state,
      coverage: Object.fromEntries((coverage.data ?? []).map(item => [item.aspect, item.state])),
    };
  }

  async function getCommittee(committeeKey: string, options: any = {}, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const clean = String(committeeKey ?? '').trim().toLowerCase();
    if (!clean) return null;
    const [commIdx, rostIdx, mIdx, memIdx] = await Promise.all([
      committeesIndex(),
      rostersIndex(),
      meetingsIndex(),
      files.has('members.parquet') ? membersIndex().catch(() => ({ byBioguide: new Map() })) : Promise.resolve({ byBioguide: new Map() }),
    ]);
    const found = commIdx.byCode.get(clean), canonicalKey = found?.committee_key ?? clean;
    const subcommittees = commIdx.subcommitteesByParent.get(canonicalKey) ?? [];
    const relatedKeys = new Set([canonicalKey, ...subcommittees.map((s: any) => s.committee_key)]);
    const docRows = uniqueInts([...relatedKeys].flatMap(k => rowsForColumn('committee_keys', k)));
    docRows.sort((a, b) => String(value('document_date', b) ?? '').localeCompare(String(value('document_date', a) ?? '')) || a - b);
    const seenMeetingEvents = new Set<string>(), normMeetings: any[] = [];
    for (const k of relatedKeys) for (const m of mIdx.byCommitteeKey.get(k) ?? []) {
      const ev = String(m.event_id);
      if (!seenMeetingEvents.has(ev)) { seenMeetingEvents.add(ev); normMeetings.push(m); }
    }
    normMeetings.sort((a: any, b: any) => (b.meeting_date ?? '').localeCompare(a.meeting_date ?? '') || String(b.event_id).localeCompare(String(a.event_id)));
    const rawRosters = (rostIdx.byCommitteeKey.get(canonicalKey) ?? []).map((r: any) => {
      const mem = memIdx.byBioguide.get(String(r.bioguide_id).toLowerCase());
      const term = mem?.terms?.find((t: any) => termOverlapsCongress(t, r.congress));
      return { ...r, name: mem?.name ?? r.bioguide_id, state: term?.state ?? null };
    });
    const chairByCongress = new Map<any, string>();
    for (const r of rawRosters) {
      const roleStr = String(r.role ?? r.title ?? '');
      if (r.party && /chair/i.test(roleStr) && !/vice|sub|ranking/i.test(roleStr)) {
        chairByCongress.set(r.congress, r.party);
      }
    }
    const normRosters = rawRosters.map((r: any) => {
      const chairParty = chairByCongress.get(r.congress);
      const majority = chairParty && r.party ? r.party === chairParty : null;
      return { ...r, majority };
    }).sort((a: any, b: any) =>
      (Number(b.congress ?? 0) - Number(a.congress ?? 0))
      || ((a.majority === true ? 0 : a.majority === false ? 1 : 2) - (b.majority === true ? 0 : b.majority === false ? 1 : 2))
      || ((a.rank_in_party ?? 999) - (b.rank_in_party ?? 999))
      || String(a.name ?? '').localeCompare(String(b.name ?? '')));
    const congresses = [...new Set(normRosters.map((r: any) => r.congress).filter((c: any) => c != null))].sort((a: any, b: any) => b - a);
    const activeCongress = options?.congress != null && options.congress !== '' ? Number(options.congress) : (congresses[0] ?? null);
    const activeRoster = activeCongress != null ? normRosters.filter((r: any) => r.congress === activeCongress) : normRosters;
    const parent = found?.parent_key ? commIdx.byCode.get(found.parent_key) ?? null : null;
    if (!found && !docRows.length && !normMeetings.length && !normRosters.length) return null;
    const base = found ?? normalizeCommittee({ system_code: canonicalKey, name: canonicalKey.toUpperCase() });
    const resolvedName = resolveCommitteeName(base, options?.date ?? options?.congress);
    return {
      ...base, resolved_name: resolvedName || base.current_name, parent, subcommittees, roster: activeRoster,
      all_rosters: normRosters, roster_congresses: congresses, active_congress: activeCongress,
      hearings: normMeetings, hearing_count: normMeetings.length,
      doc_count: docRows.length, list_rows: docRows, documents: docRows.slice(0, 100).map(row),
    };
  }

  async function getWitness(witnessKey: string, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const clean = String(witnessKey ?? '').trim().toLowerCase();
    if (!clean) return null;
    const [wIdx, mIdx, memIdx] = await Promise.all([witnessesIndex(), meetingsIndex(), membersIndex()]);
    let found = wIdx.byKey.get(clean);
    let redirectedFrom: string | null = null;
    if (!found && ctx.witnessKeyMap) {
      const mapped = await ctx.witnessKeyMap(clean);
      if (mapped && !mapped.successor) return { witness_key: clean, retired: mapped };
      if (mapped) {
        found = wIdx.byKey.get(mapped.successor!.toLowerCase());
        if (!found) throw new Error('Witness key map successor is not published.');
        redirectedFrom = clean;
      }
    }
    if (!found) {
      const colRows = rowsForColumn('witness_keys', clean);
      if (!colRows.length) return null;
      found = {
        ...normalizeWitness({ witness_key: witnessKey, name: null }),
        list_rows: colRows,
      };
    }
    const enrichedAppearances = found.appearances.map((a: any) => {
      const m = (mIdx.byEventId.get(String(a.event_id ?? '').toLowerCase()) ?? [])[0];
      return {
        ...(m ? { title: m.title, meeting_date: m.meeting_date, chamber: m.chamber, congress: m.congress, committee_keys: m.committee_keys } : {}),
        ...a, meeting_title: a.title ?? m?.title ?? null, committee_keys: a.committee_keys ?? m?.committee_keys ?? [],
      };
    });
    const member = found.bioguide_id ? memIdx.byBioguide.get(String(found.bioguide_id).toLowerCase()) ?? null : null;
    return { ...found, appearances: enrichedAppearances, hearings: enrichedAppearances, member, documents: found.list_rows.map(row), redirected_from: redirectedFrom };
  }

  async function getMember(bioguideId: string, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const clean = String(bioguideId ?? '').trim().toLowerCase();
    if (!clean) return null;
    const [memIdx, rostIdx, wIdx, mIdx, bIdx, commIdx] = await Promise.all([membersIndex(), rostersIndex(), witnessesIndex(), meetingsIndex(), billsIndex(), committeesIndex()]);
    const witnessRecords = (wIdx.byBioguide.get(clean) ?? []).filter(w => w.superseded_by == null);
    const found = memIdx.byBioguide.get(clean), rawRosterEntries = rostIdx.byBioguide.get(clean) ?? [], sponsoredBills = bIdx.bySponsor.get(clean) ?? [], colRows = rowsForColumn('bioguide_ids', clean);
    if (!found && !rawRosterEntries.length && !witnessRecords.length && !colRows.length && !sponsoredBills.length) return null;
    const rosterEntries = rawRosterEntries.map((r: any) => {
      const c = commIdx.byCode.get(r.committee_key);
      return { ...r, name: c?.name ?? null };
    });
    const base = found ?? normalizeMember({
      bioguide_id: bioguideId.toUpperCase(), name: witnessRecords[0]?.name ?? bioguideId.toUpperCase(),
      terms: [],
    });
    const allListRows = uniqueInts([...base.list_rows, ...witnessRecords.flatMap((w: any) => w.list_rows)]);
    const seenEvents = new Set<string>(), hearings: any[] = [];
    for (const app of [...base.appearances, ...witnessRecords.flatMap((w: any) => w.appearances)]) {
      const ev = String(app.event_id ?? '');
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
    const sIdx = await awaitShared(indexLoader(), signal);
    const found = sIdx.byKey.get(clean);
    if (!found) return null;
    const { data: mIdx } = await optional('meetings', meetingsIndex, signal);
    const canonical = found.subject_key.toLowerCase(), seenEvents = new Set<string>(), normMeetings: any[] = [];
    for (const m of [...(mIdx?.bySubjectKey.get(canonical) ?? []), ...(mIdx?.bySubjectKey.get(clean) ?? [])]) {
      const ev = String(m.event_id);
      if (!seenEvents.has(ev)) { seenEvents.add(ev); normMeetings.push(m); }
    }
    for (const ev of found.meeting_keys) {
      const m = mIdx?.byEventId.get(String(ev).toLowerCase())?.[0];
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
    const isNom = /^(?:\d+-)?pn[- ]?\d/i.test(clean);
    if (!isNom) {
      const bill = await getBill(clean, signal);
      if (bill) return bill;
    }
    const nomination = await getNomination(clean, signal);
    if (nomination) return nomination;
    const lower = clean.toLowerCase(), docRows = rowsForColumn('measure_keys', lower);
    const { data: mIdx } = await optional('meetings', meetingsIndex, signal);
    const seenEvents = new Set<string>(), hearings: any[] = [];
    for (const m of [...(mIdx?.bySubjectKey.get(lower) ?? []), ...docRows.flatMap(r => mIdx?.byDocRow.get(r) ?? [])]) {
      const ev = String(m.event_id);
      if (!seenEvents.has(ev)) { seenEvents.add(ev); hearings.push(m); }
    }
    if (!docRows.length && !hearings.length) return null;
    const congMatch = /^(\d+)-/.exec(clean);
    return {
      kind: isNom ? ('nomination' as const) : ('bill' as const), subject_key: clean,
      bill_id: isNom ? undefined : clean, nomination_id: isNom ? clean : undefined,
      congress: congMatch ? Number(congMatch[1]) : (docRows.length ? value('congress', docRows[0]) : null),
      title: null, status: null, committees: [...new Set(docRows.flatMap(r => value('committee_keys', r) ?? []))],
      cbo_estimates: [], votes: [], floor_votes: [], amendments: [], amendment_count: 0,
      related_bills: [], nominees: null, meeting_keys: hearings.map((m: any) => String(m.event_id)), hearings,
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
      case 'witnesses': items = (await witnessesIndex()).currentRows; break;
      case 'recordings': {
        const [recordings, videos] = await Promise.all([recordingsIndex(), optional('videos', videosIndex, signal)]);
        items = recordings.rows.map(r => withVideoDuration(r, videos.data));
        break;
      }
      case 'committees': items = (await committeesIndex()).rows; break;
      case 'members': items = (await membersIndex()).rows; break;
      case 'rosters': items = (await rostersIndex()).rows; break;
      case 'bills': items = (await billsIndex()).rows; break;
      case 'nominations': items = (await nominationsIndex()).rows; break;
      case 'subjects': {
        const [bIdx, nIdx] = await Promise.all([billsIndex(), nominationsIndex()]);
        items = [...bIdx.rows, ...nIdx.rows].sort(sortSubjects);
        break;
      }
      default: throw new Error(`Unknown archive entity kind: ${kind}`);
    }
    const relatedMeetings = new Map<any, any[]>();
    const filterByMeeting = (kind === 'witnesses' || kind === 'recordings') && Boolean(congressFilter || chamberFilter || committeeFilter);
    if (filterByMeeting) {
      const meetings = await awaitShared(meetingsIndex(), signal);
      for (const item of items) {
        const eventIds = kind === 'witnesses' ? [item.event_id] : item.event_ids;
        relatedMeetings.set(item, eventIds.flatMap((event: any) => meetings.byEventId.get(String(event).toLowerCase()) ?? []));
      }
    }
    const [memberRosters, memberCommittee] = await Promise.all([
      kind === 'members' && committeeFilter
        ? awaitShared(rostersIndex(), signal).then(index => index.byBioguide) : null,
      kind === 'members' && committeeFilter && chamberFilter
        ? awaitShared(committeesIndex(), signal).then(index => index.byCode.get(committeeFilter)) : null,
    ]);
    const filtered = items.filter((item: any) => {
      if (filterByMeeting) {
        if (!relatedMeetings.get(item)!.some(meeting =>
          (congressFilter == null || meeting.congress === congressFilter)
          && (!chamberFilter || meeting.chamber === chamberFilter)
          && (!committeeFilter || meeting.committee_keys.includes(committeeFilter)))) return false;
      } else if (kind === 'members') {
        if ((congressFilter != null || chamberFilter) && !item.terms.some((term: any) =>
          (congressFilter == null || termOverlapsCongress(term, congressFilter))
          && (!chamberFilter || term.chamber === chamberFilter))) return false;
      } else {
        if (congressFilter != null && kind !== 'committees' && item.congress !== congressFilter) return false;
        if (chamberFilter && item.chamber !== chamberFilter) return false;
      }
      if (memberRosters) {
        if (chamberFilter && memberCommittee?.chamber !== chamberFilter
          && !(memberCommittee?.chamber === 'joint' && ['house', 'senate'].includes(chamberFilter))) return false;
        const assignments = memberRosters.get(item.bioguide_id.toLowerCase()) ?? [];
        if (!assignments.some((assignment: any) => assignment.system_code === committeeFilter
          && (congressFilter == null || assignment.congress === congressFilter)
          && (!chamberFilter || item.terms.some((term: any) => term.chamber === chamberFilter
            && termOverlapsCongress(term, assignment.congress))))) return false;
      } else if (committeeFilter && !filterByMeeting) {
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
          item.subject_key, item.bill_id, item.nomination_id, item.bioguide_id, item.committee_key, item.event_id,
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
    const [entry, versions, meetings, recordings, committees, witnesses, members, bills, nominations] = await Promise.all([
      ctx.entry(index, signal), ctx.versions(index, signal),
      optional('meetings', meetingsIndex, signal), optional('recordings', recordingsIndex, signal),
      optional('committees', committeesIndex, signal), optional('witnesses', witnessesIndex, signal),
      optional('members', membersIndex, signal), optional('bills', billsIndex, signal),
      optional('nominations', nominationsIndex, signal),
    ]);
    const { data: mIdx } = meetings, { data: recIdx } = recordings, { data: commIdx } = committees;
    const { data: wIdx } = witnesses, { data: memIdx } = members, { data: bIdx } = bills, { data: nIdx } = nominations;
    const doc = entry.document, seenMeetingEvents = new Set<string>(), docMeetings: any[] = [];
    const addMeeting = (m: any) => {
      const ev = String(m.event_id);
      if (!seenMeetingEvents.has(ev)) { seenMeetingEvents.add(ev); docMeetings.push({ ...m, recordings: recIdx?.byEventId.get(ev) ?? [] }); }
    };
    for (const mk of doc.meeting_keys ?? []) for (const m of mIdx?.byEventId.get(String(mk).toLowerCase()) ?? []) addMeeting(m);
    for (const m of mIdx?.byDocRow.get(index) ?? []) addMeeting(m);

    const docCommitteeKeys = new Set([...(doc.committee_keys ?? []).map((k: any) => String(k).toLowerCase()), ...docMeetings.flatMap((m: any) => (m.committee_keys ?? []).map((k: any) => String(k).toLowerCase()))]);
    const seenCommitteeKeys = new Set<string>(), docCommittees: any[] = [];
    for (const ck of docCommitteeKeys) {
      const c = commIdx?.byCode.get(ck);
      if (c && !seenCommitteeKeys.has(c.committee_key)) {
        seenCommitteeKeys.add(c.committee_key);
        docCommittees.push({ ...c, resolved_name: resolveCommitteeName(c, doc.document_date ?? doc.congress) });
      }
    }

    const docSubjectKeys = new Set([...(doc.measure_keys ?? []).map((k: any) => String(k).toLowerCase()), ...docMeetings.flatMap((m: any) => (m.subject_keys ?? []).map((k: any) => String(k).toLowerCase()))]);
    const seenSubjects = new Set<string>(), docSubjects: any[] = [];
    const addSubject = (s: any) => { if (s && !seenSubjects.has(String(s.subject_key).toLowerCase())) { seenSubjects.add(String(s.subject_key).toLowerCase()); docSubjects.push(s); } };
    for (const sk of docSubjectKeys) addSubject(bIdx?.byKey.get(sk));
    for (const b of bIdx?.byDocRow.get(index) ?? []) addSubject(b);
    for (const sk of docSubjectKeys) addSubject(nIdx?.byKey.get(sk));
    for (const n of nIdx?.byDocRow.get(index) ?? []) addSubject(n);

    const seenWitnesses = new Set<string>(), docWitnesses: any[] = [];
    const addWitness = (w: any) => {
      const visited = new Set<string>();
      while (w?.superseded_by != null) {
        const successor = String(w.superseded_by).toLowerCase();
        if (visited.has(successor)) return;
        visited.add(successor);
        w = wIdx?.byKey.get(successor);
      }
      if (!w) return;
      const key = String(w.witness_key).toLowerCase();
      if (!seenWitnesses.has(key)) { seenWitnesses.add(key); docWitnesses.push(w); }
    };
    for (const wk of doc.witness_keys ?? []) addWitness(wIdx?.byKey.get(String(wk).toLowerCase()));
    for (const w of wIdx?.byDocRow.get(index) ?? []) addWitness(w);

    const seenMembers = new Set<string>(), docMembers: any[] = [];
    const addMember = (m: any) => { if (m && !seenMembers.has(String(m.bioguide_id).toLowerCase())) { seenMembers.add(String(m.bioguide_id).toLowerCase()); docMembers.push(m); } };
    for (const bio of doc.bioguide_ids ?? []) addMember(memIdx?.byBioguide.get(String(bio).toLowerCase()));
    for (const m of memIdx?.byDocRow.get(index) ?? []) addMember(m);

    return {
      ...entry, versions, meetings: docMeetings, committees: docCommittees, subjects: docSubjects,
      witnesses: docWitnesses, members: docMembers,
      relation_states: { meetings: meetings.state, recordings: recordings.state, committees: committees.state,
        witnesses: witnesses.state, members: members.state, bills: bills.state, nominations: nominations.state },
    };
  }

  return { prepareQuery, getMeeting, getCommittee, getWitness, getMember, getBill, getNomination, getSubject, listEntities, openDocument };
}
