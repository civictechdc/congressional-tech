export interface FilenameCatalogInfo {
  catalog_id: string;
  rows: number;
  documents?: number;
  capture_records?: number;
  entries?: number;
  fields: string[];
  facets: Partial<Record<'congress' | 'document_family' | 'document_kind' | 'format', string[]>>;
  review_facets?: FilenameCatalogInfo['facets'];
  complete_body_reviews?: boolean;
  reviewed_search?: boolean;
  review_sha256?: string;
  reviewed_groups?: number;
  review_error?: string;
  recovery_sha256?: string;
  published_at?: string;
  remote_last_modified?: string;
  house_naming_version?: string;
  api_reference_groups?: number;
  downloads?: { documents?: string; filenames?: string; recoveries?: string };
}

export interface FilenameRecovery {
  recovery_status?: string;
  kind?: string;
  body_key?: string;
  recovered_url?: string;
  original_url?: string;
}

/** A catalog row. List rows, detail records, and grouped sources share these fields. */
export interface FilenameRecord {
  filename?: string | null;
  source_url?: string | null;
  source_id?: string | null;
  document_kind?: string[] | null;
  document_kind_source?: string[] | null;
  document_family?: string[] | null;
  format?: string[] | null;
  body_format?: string[] | null;
  media_type?: string[] | null;
  congress?: string[] | null;
  source_congress?: string[] | null;
  committee_code?: string[] | null;
  measure_references?: string[] | null;
  date_token_candidates?: string[] | null;
  record_role?: string[] | null;
  http_status?: Array<string | number> | null;
  response_usable?: string[] | null;
  response_body_complete?: string[] | null;
  response_format?: string[] | null;
  retained?: boolean | null;
  source_count?: number | null;
  recovery?: FilenameRecovery | null;
  body_key?: string | null;
  filename_origins?: string[] | null;
  state_outcome?: string[] | null;
  state_checked_at?: string[] | null;
  source_committee_name?: string[] | null;
  source_document_type?: string[] | null;
  source_document_type_basis?: string[] | null;
  recovered_source_url?: string[] | null;
  api_reference?: { title: string; evidence?: string } | null;
  video_reference?: { provider: string; id: string } | null;
  _row?: number;
  _review_status?: string;
  [key: string]: unknown;
}

export interface FilenameSearchResult {
  rows: FilenameRecord[];
  total: number;
  page: number;
  pages: number;
  limit: number;
}

export interface FilenameMatch {
  source_id: string;
  url?: string;
  sha256?: string;
}

export interface FilenameMatchResult {
  matches: FilenameMatch[];
  truncated: boolean;
}

export interface FilenameEntry {
  record: FilenameRecord;
  document: FilenameRecord;
  facts?: { completeness_conflict?: boolean } | null;
  filename?: string | null;
  filename_field_count?: number;
  sources: FilenameRecord[];
  catalog_id: string;
  api_reference?: FilenameRecord['api_reference'];
  video_reference?: FilenameRecord['video_reference'];
  recovery?: FilenameRecovery;
  recoveries?: FilenameRecovery[];
  origin_pending?: boolean;
  origin?: import('../../browse/provenance.ts').SourceContext;
  document_origin?: { redirects?: { original: string; final: string }[] };
  observation_count?: number;
  origin_next?: number | null;
  saved_file_url?: string | null;
  saved_file_available?: boolean;
  published_only?: boolean;
  sources_share_saved_file?: boolean;
  record_complete?: boolean;
}

export interface FilenameReview {
  status: string;
  baseline?: { document_kind?: string[] | null; document_family?: string[] | null };
  selected?: { document_kind?: string[] | null; document_family?: string[] | null };
  review?: {
    primary_forms?: string[];
    component_forms?: string[];
    body_observation?: {
      pages?: number;
      notes?: string;
      text_path?: string;
      native_text_path?: string;
      observations?: unknown[];
      page_sections?: { first_page: number; last_page: number; observed_form: string; description?: string }[];
    };
  };
  evidence?: { body?: string; text?: string; 'native-text'?: string; pages?: Record<string, string> };
}
