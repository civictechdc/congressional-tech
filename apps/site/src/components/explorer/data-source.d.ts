import type { Catalog, ReportedTime, Meeting } from './catalog.generated';

/** Domain types come from committee_meeting; serialized identities are required at the boundary. */
export interface BrowserRecord extends QueryRow {
  position?: string | null;
  organization?: string | null;
  participation?: string | null;
  explanation?: string | null;
  meeting_ids: readonly string[];
  appearance_ids: readonly string[];
  source_ids: readonly string[];
  files: readonly { url: string; label?: string | null; role?: string | null; media_type?: string | null; version?: string | null; published_at?: string | null; sha256?: string | null }[];
  facts: readonly { label: string; value: string }[];
  subject_kind?: string | null;
  subject_id?: string | null;
}
export type ExplorerRecord = Readonly<(NonNullable<Catalog['records']>[number] | BrowserRecord) & { kind: string; id: string }>;
export interface BrowserSourceRecord {
  kind: 'source_record';
  id: string;
  provider: string;
  url?: string | null;
  retrieved_at?: string | null;
  imported_at?: string | null;
  source_modified_at?: string | null;
  input_snapshot_id?: string | null;
  identifier?: string | null;
  retained_uri?: string | null;
  retained_sha256?: string | null;
  payload: unknown;
}
export type ExplorerSourceRecord = Readonly<(NonNullable<Catalog['sources']>[number] | BrowserSourceRecord) & { kind: 'source_record'; id: string }>;
export interface ExplorerSnapshot {
  readonly schemaVersion: string;
  readonly records: readonly ExplorerRecord[];
  readonly sources: readonly ExplorerSourceRecord[];
  readonly publication?: Readonly<Record<string, unknown>>;
}

/** Inject this into the UI. Loading and decoding belong to the implementation. */
export interface ExplorerDataSource {
  load(options?: { signal?: AbortSignal }): Promise<ExplorerSnapshot>;
}

export type ArtifactDecoder = (bytes: Uint8Array, context?: { schemaName: string; schemaVersion: string }) => unknown | Promise<unknown>;
export type CatalogDecoder = ArtifactDecoder;
export type Fetcher = typeof fetch;
export function decodeJson(bytes: Uint8Array): unknown;
export function decodeGzipJson(bytes: Uint8Array): Promise<unknown>;
export function normalizeCatalog(document: unknown): ExplorerSnapshot;
export function createCatalogSource(options: {
  url: string | URL;
  fetcher?: Fetcher;
  decode?: CatalogDecoder;
}): ExplorerDataSource;
export function createPublicationSource(options: {
  pointerUrl: string | URL;
  fetcher?: Fetcher;
  decoders?: Readonly<Record<string, CatalogDecoder>>;
}): ExplorerDataSource;

export interface MeetingIndexRow {
  id: string;
  title: Meeting['title'];
  congress: Meeting['congress'];
  chamber: Meeting['chamber'];
  scheduled_dates: readonly ReportedTime[];
  committee_ids: readonly string[];
  appearance_count: number;
  material_count: number;
  issue_ids: readonly string[];
}
export interface ExplorerRecordRef { kind: string; id: string }
export type QueryKind = 'meeting' | 'committee_term' | 'material' | 'appearance' | 'data_issue';
export type EvidenceState = 'observed' | 'reported' | 'curated' | 'derived' | 'inferred' | 'error' | 'blocked' | 'not_found_in_checked_scope' | 'not_applicable' | 'unknown' | 'unchecked';
export type CoverageAspect = 'recording' | 'transcript' | 'documents' | 'witnesses' | 'captions';
export interface QueryRow extends ExplorerRecordRef {
  position?: string | null;
  organization?: string | null;
  kind: QueryKind;
  title: string;
  congress: number | null;
  chamber?: string | null;
  date?: string | null;
  scheduled_at?: string | null;
  source_status?: string | null;
  meeting_status?: string | null;
  recording_url?: string | null;
  type?: string | null;
  status?: string | null;
  committee_ids?: readonly string[];
  meeting_id?: string | null;
  provider?: string | null;
  category?: string | null;
  roles?: readonly string[];
  issue_count?: number;
  selection?: 'retained_history';
  search_text?: string;
  evidence_states?: Partial<Record<CoverageAspect, EvidenceState>>;
}
export interface ExplorerQuery {
  kind?: QueryKind;
  congress?: number | 'all';
  q?: string;
  chamber?: string;
  dateFrom?: string;
  dateTo?: string;
  month?: string;
  type?: string;
  status?: string;
  committeeId?: string;
  aspect?: CoverageAspect;
  evidence?: EvidenceState;
  offset?: number;
  limit?: number;
}
export interface QueryInfo {
  default_congress: number;
  congresses: readonly number[];
  kinds: readonly {kind: QueryKind; count: number}[];
  committee_labels?: Readonly<Record<string, string>>;
}
export interface QueryResult { rows: readonly QueryRow[]; total: number; offset: number; limit: number }
export interface EvidenceCounts { unit: 'meeting'; denominator: number; states: Record<EvidenceState, number>; rule: string }
export interface CoverageGroup { key: string; label: string; denominator: number; state_breakdown: Record<CoverageAspect, EvidenceCounts> }
export interface CoverageSummary {
  state_breakdown: Record<CoverageAspect, EvidenceCounts>;
  groups: Record<'congress' | 'committee' | 'month', readonly CoverageGroup[]>;
  population: string;
  limitations: readonly string[];
}
/** For real archive browsing: inject domain queries, with storage discovery inside the reader. */
export interface ExplorerReader {
  readonly publication: Readonly<Record<string, unknown>>;
  getQueryInfo(options?: { signal?: AbortSignal }): Promise<QueryInfo>;
  search(query?: ExplorerQuery, options?: { signal?: AbortSignal }): Promise<QueryResult>;
  getRelated(ref: ExplorerRecordRef, options?: { kind?: string; offset?: number; limit?: number; signal?: AbortSignal }): Promise<{records: readonly (ExplorerRecord | ExplorerSourceRecord)[]; total: number; offset: number; limit: number}>;
  getMeetingIndex?(options?: { signal?: AbortSignal }): Promise<readonly MeetingIndexRow[]>;
  getCoverage(options: { filters: ExplorerQuery; signal?: AbortSignal }): Promise<CoverageSummary>;
  getCoverage(options?: { signal?: AbortSignal }): Promise<Readonly<Record<string, unknown>>>;
  getRecord(ref: ExplorerRecordRef, options?: { signal?: AbortSignal }): Promise<ExplorerRecord | ExplorerSourceRecord | undefined>;
  getRecords(refs: readonly ExplorerRecordRef[], options?: { signal?: AbortSignal }): Promise<readonly (ExplorerRecord | ExplorerSourceRecord | undefined)[]>;
}
export function openPublicationReader(options: {
  pointerUrl: string | URL;
  fetcher?: Fetcher;
  decoders?: Readonly<Record<string, ArtifactDecoder>>;
  signal?: AbortSignal;
}): Promise<ExplorerReader>;
