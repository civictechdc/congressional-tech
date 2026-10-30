import type { Catalog } from './catalog.generated';
import type { CoverageAspect, EvidenceState } from '../browse/kinds.ts';

export type { CoverageAspect, EvidenceState } from '../browse/kinds.ts';

export interface RecordFile {
  url: string;
  label?: string | null;
  role?: string | null;
  media_type?: string | null;
  version?: string | null;
  published_at?: string | null;
  sha256?: string | null;
  saved_copy_sha256?: string | null;
  saved_filename?: string | null;
}

export interface ExplorerRecordRef {
  kind: string;
  id: string;
}

export type QueryKind = 'meeting' | 'committee_term' | 'material' | 'appearance' | 'data_issue';

export interface QueryRow extends ExplorerRecordRef {
  source_ids?: readonly string[] | null;
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
  document_type?: string | null;
  source_document_groups?: readonly string[] | null;
  status?: string | null;
  access?: 'open' | 'closed' | 'partly_closed' | 'unknown' | null;
  committee_ids?: readonly string[];
  committee_code?: string | null;
  terms?: readonly { kind: QueryKind; id: string; title: string; congress: number | null }[];
  committee_level?: 'full' | 'subcommittee' | 'unknown' | null;
  parent_committee_code?: string | null;
  parent_committee_id?: string | null;
  committee_type?: string | null;
  source_committee_type?: string | null;
  committee_types?: readonly string[] | null;
  meeting_id?: string | null;
  meeting_ids?: readonly string[];
  appearance_ids?: readonly string[];
  provider?: string | null;
  category?: string | null;
  roles?: readonly string[];
  issue_count?: number;
  selection?: 'retained_history';
  search_text?: string;
  evidence_states?: Partial<Record<CoverageAspect, EvidenceState>>;
  files?: readonly RecordFile[];
  parent?: { id?: string | null } | null;
  payload?: unknown;
  subject_kind?: string | null;
  subject_id?: string | null;
  explanation?: string | null;
  participation?: string | null;
  severity?: string | null;
  facts?: readonly { label: string; value: string }[] | null;
}

export interface BrowserRecord extends QueryRow {
  appearance_ids: readonly string[];
  source_ids: readonly string[];
  files: readonly RecordFile[];
  facts: readonly { label: string; value: string }[];
}

export type ExplorerRecord = Readonly<(NonNullable<Catalog['records']>[number] | BrowserRecord) & { kind: string; id: string }>;

export interface BrowserSourceRecord {
  kind: 'source_record';
  id: string;
  provider: string;
  url?: string | null;
  title?: string | null;
  retrieved_at?: string | null;
  imported_at?: string | null;
  source_modified_at?: string | null;
  input_snapshot_id?: string | null;
  identifier?: string | null;
  identifier_scheme?: string | null;
  identifier_value?: string | null;
  identifier_scope?: string | null;
  retained_uri?: string | null;
  retained_sha256?: string | null;
  facts?: readonly { label: string; value: string }[] | null;
  links?: readonly { group: string; label: string; href: string }[] | null;
  payload?: unknown;
}

export type ExplorerSourceRecord = Readonly<(NonNullable<Catalog['sources']>[number] | BrowserSourceRecord) & { kind: 'source_record'; id: string }>;

/** A record the reader has loaded: a catalog record, a source observation, or a Parquet row. */
export type LoadedRecord = ExplorerRecord | ExplorerSourceRecord | QueryRow;

export interface ExplorerSnapshot {
  readonly schemaVersion: string;
  readonly records: readonly ExplorerRecord[];
  readonly sources: readonly ExplorerSourceRecord[];
  readonly publication?: Readonly<Record<string, unknown>>;
}

export interface ExplorerDataSource {
  load(options?: { signal?: AbortSignal }): Promise<ExplorerSnapshot>;
}

export type ArtifactDecoder = (bytes: Uint8Array, context?: { schemaName: string; schemaVersion: string }) => unknown | Promise<unknown>;
export type Fetcher = typeof fetch;

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
  category?: string;
  severity?: string;
  participation?: string;
  provider?: string;
  history?: '' | 'current' | 'retained';
  access?: string;
  committeeId?: string;
  committeeLevel?: 'full';
  committeeType?: string;
  aspect?: string;
  evidence?: string;
  sort?: '' | 'record' | 'date' | 'congress' | 'kind';
  direction?: '' | 'asc' | 'desc';
  offset?: number;
  limit?: number;
}

export interface QueryInfo {
  supported_filters?: readonly ('committeeLevel' | 'committeeType' | 'access')[];
  default_congress: number;
  congresses: readonly number[];
  kinds: readonly { kind: QueryKind; count: number }[];
  committee_labels?: Readonly<Record<string, string>>;
  query_columns?: readonly string[];
  partitions?: readonly { kind: string; congress?: number; path: string }[];
  storage?: string;
}

export interface QueryResult {
  rows: readonly QueryRow[];
  total: number;
  offset: number;
  limit: number;
}

export interface MaterialCategory {
  label: string;
  count: number;
}

export interface RelatedOptions {
  kind?: string;
  materialType?: 'document' | 'recording';
  category?: string;
  offset?: number;
  limit?: number;
  signal?: AbortSignal;
}

export interface RelatedResult {
  records: readonly LoadedRecord[];
  total: number;
  offset: number;
  limit: number;
  categories?: readonly MaterialCategory[];
}

export interface EvidenceCounts {
  unit: 'meeting';
  denominator: number;
  states: Record<EvidenceState, number>;
  rule: string;
}

export interface CoverageGroup {
  key: string;
  label: string;
  denominator: number;
  state_breakdown: Record<CoverageAspect, EvidenceCounts>;
}

export interface CoverageSummary {
  state_breakdown: Record<CoverageAspect, EvidenceCounts>;
  groups: Record<'congress' | 'committee' | 'month', readonly CoverageGroup[]>;
  population: string;
  limitations: readonly string[];
}

export interface ExplorerReader {
  readonly publication: Readonly<Record<string, unknown>>;
  getQueryInfo(options?: { signal?: AbortSignal }): Promise<QueryInfo>;
  search(query?: ExplorerQuery, options?: { signal?: AbortSignal }): Promise<QueryResult>;
  getRelated(ref: ExplorerRecordRef, options?: RelatedOptions): Promise<RelatedResult>;
  getCoverage(options: { filters: ExplorerQuery; signal?: AbortSignal }): Promise<CoverageSummary>;
  getRecord(ref: ExplorerRecordRef, options?: { signal?: AbortSignal }): Promise<LoadedRecord | undefined>;
  getRecords(refs: readonly ExplorerRecordRef[], options?: { signal?: AbortSignal }): Promise<readonly (LoadedRecord | undefined)[]>;
  listWitnesses(meetingIds: readonly string[], options?: { signal?: AbortSignal }): Promise<readonly { meeting_id: string; title: string }[]>;
  listMaterialCounts?(meetingIds: readonly string[], options?: { signal?: AbortSignal }): Promise<ReadonlyMap<string, { recordings: number; documents: number }>>;
}

export interface ArtifactPart {
  path: string;
  role?: string;
  schema_name: string;
  schema_version: string;
  media_type?: string;
  byte_size: number;
  record_count: number;
  sha256?: string;
}

export interface PublicationHandle {
  manifest: Record<string, unknown> & { partitions: ArtifactPart[]; publication_id: string; schema_version: string };
  manifestUrl: URL;
  select(role: string, schemaName: string): ArtifactPart;
  readPartition(part: ArtifactPart, signal?: AbortSignal): Promise<unknown>;
}

export interface OpenReaderOptions {
  pointerUrl: string | URL;
  fetcher?: Fetcher;
  decoders?: Readonly<Record<string, ArtifactDecoder>>;
  signal?: AbortSignal;
}
