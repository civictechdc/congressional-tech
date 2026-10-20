import type { FilenameRecord } from '../reader/filenames/types.ts';
import { filenameDate } from './filename-rules.ts';
import { provenanceUrlKey } from './provenance.ts';

const fieldLabels: Record<string, string> = {
  body_key: 'Saved file location', filename: 'Filename', source_url: 'Publisher URL', filename_origins: 'Filename obtained from',
  media_type: 'Server-reported type', http_status: 'HTTP response', response_usable: 'Recorded usability assessment',
  response_body_complete: 'Complete response saved', response_format: 'Response format check', response_result: 'Response diagnostic',
  capture_outcome: 'Capture result', body_format: 'Detected file format', format: 'File format', extension: 'Filename extension',
  document_kind: 'Document classification', document_family: 'Classification family', document_kind_source: 'Classification evidence',
  source_id: 'Source record ID', document_id: 'Grouped document ID', congress: 'Congress from filename',
  source_congress: 'Congress from source', source_committee_name: 'Committee from source', committee_code: 'Committee code from filename',
  content_document_kind: 'Document kind from saved contents', content_congress: 'Congress from saved contents', content_citation: 'Publication citation',
  state_outcome: 'Latest fetch result', recovery: 'Recovered copy', measure_references: 'Measure', date_token_candidates: 'Possible date',
  source_page_url: 'Recorded source page', source_page_title: 'Source page title', source_link_label: 'Publisher link text',
  source_record_type: 'Source record type', source_meeting_title: 'Meeting title from source', source_chamber: 'Chamber from source',
  source_occurrences: 'Related source observations',
};

export function fieldLabel(key: string): string {
  return (fieldLabels[key] || key.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase()))
    .replace(/\b(url|id|uuid|http|pdf|xml|api)\b/gi, match => match.toUpperCase());
}

export function pretty(value: string): string {
  return value.replaceAll('_', ' ').replaceAll('-', ' ').replace(/^./, letter => letter.toUpperCase());
}

const textValues = (value: unknown): string[] => Array.isArray(value)
  ? value.filter((item): item is string => typeof item === 'string')
  : typeof value === 'string' ? [value] : [];

function pageKey(value: unknown): string | null {
  const key = provenanceUrlKey(value);
  return key && key.length > 1 && key.endsWith('/') ? key.slice(0, -1) : key;
}

function htmlRecord(row: { format?: string[] | null; media_type?: string[] | null; body_format?: string[] | null }): boolean {
  const values = [...(row.format ?? []), ...(row.media_type ?? []), ...(row.body_format ?? [])].map(value => value.split(';')[0].trim().toLowerCase());
  return !values.length || values.some(value => value === 'html' || value === 'text/html');
}

/** The captured file is the committee page when that page was recorded for this URL. */
export function sourcePageLabel(row: { source_url?: unknown; source_page_url?: unknown; source_page_title?: unknown; source_meeting_type?: unknown; source_record_type?: string[] | null; format?: string[] | null; media_type?: string[] | null; body_format?: string[] | null }): string {
  if (row.source_record_type?.includes('committee-hearing-page')) return 'Hearing page';
  if (row.source_record_type?.includes('committee-meeting-page')) return 'Meeting page';
  if (row.source_record_type?.includes('committee-page')) return 'Committee page';
  if (!htmlRecord(row)) return '';
  const file = pageKey(row.source_url);
  if (!file || !textValues(row.source_page_url).some(value => pageKey(value) === file)) return '';
  const titles = textValues(row.source_page_title).map(value => value.trim().toLowerCase());
  const types = textValues(row.source_meeting_type).map(value => value.trim().toLowerCase());
  if (titles.some(value => value === 'hearing' || value === 'field hearing') || types.includes('hearing')) return 'Hearing page';
  if (titles.some(value => value === 'meeting' || value === 'business meeting' || value === 'markup') || types.includes('meeting') || types.includes('markup')) return 'Meeting page';
  return '';
}

/** A recorded role that is not the ordinary document or source-record role. */
export function recordRoleNote(row: { record_role?: string[] | null }): string {
  const roles = row.record_role || [];
  if (roles.includes('error-response')) return 'Error response';
  if (roles.includes('capture-state')) return 'Capture state';
  return '';
}

/** A file with no document form can still have a recorded role. */
export function fileRoleLabel(row: { filename?: string | null; format?: string[] | null; document_kind?: string[] | null }): string {
  if (row.document_kind?.length) return '';
  const format = (row.format ?? []).map(value => value.toLowerCase());
  const name = (row.filename ?? '').toLowerCase();
  if (format.includes('text/vtt') || name.endsWith('.vtt')) return 'Caption segment';
  if (/^(?:mods|dip|premis|mets)\.xml$/.test(name)) return 'Package metadata';
  if (/^h(?:hrg|mtg)-\d+-[a-z0-9]+-\d{8}\.xml$/.test(name)) return 'Meeting package';
  return '';
}

export function documentKindLabel(row: { video_reference?: unknown; api_reference?: unknown; document_kind?: string[] | null }): string {
  if (row.video_reference) return 'Video reference';
  if (row.api_reference) return 'Source/API reference';
  return row.document_kind?.map(pretty).join(' · ') || 'Unclassified';
}

const sourceRecordLabels: Record<string, string> = {
  hearing: 'Hearing record',
  mods: 'Package metadata',
  premis: 'Package metadata',
  'package-summary': 'Package summary',
  'collection-listing': 'Collection listing',
  'error-page': 'Error page',
  'house-cache-marker': 'Cache marker',
  'collector-artifact': 'Collector artifact',
};

/** A recorded source type when the file has no document kind. A hearing type applies only to a source record. */
export function sourceRecordLabel(row: { document_kind?: string[] | null; record_role?: string[] | null; source_record_type?: string[] | null }): string {
  if (row.document_kind?.length) return '';
  const allowHearing = Boolean(row.record_role?.includes('source-record'));
  return (row.source_record_type || []).map(value => value === 'hearing' && !allowHearing ? '' : sourceRecordLabels[value] || '').find(Boolean) || '';
}

export function recordLabel(row: Parameters<typeof documentKindLabel>[0] & Parameters<typeof sourcePageLabel>[0] & Parameters<typeof fileRoleLabel>[0] & Parameters<typeof sourceRecordLabel>[0]): string {
  if (row.video_reference) return 'Video reference';
  // A recorded source type is more specific than the generic API label. Every Congress hearing source record is an API URL.
  const source = sourceRecordLabel(row);
  if (source) return source;
  if (row.api_reference || row.document_kind?.length) return documentKindLabel(row);
  return sourcePageLabel(row) || fileRoleLabel(row) || 'Unclassified';
}

/** The source committee name, with any recorded code the name does not already contain. */
export function sourceCommitteeNote(row: { source_committee_name?: readonly string[] | null; source_committee_code?: readonly string[] | null }): { text: string; code: string } {
  const names = [...new Set((row.source_committee_name || []).map(value => value.trim()).filter(Boolean))];
  const codes = [...new Set((row.source_committee_code || []).map(value => value.trim()).filter(Boolean))];
  const folded = names.join(' ').toLowerCase();
  const extra = codes.filter(code => !folded.includes(code.toLowerCase()));
  if (names.length && extra.length) return { text: `${names.join(' · ')} · ${extra.join(' · ')}`, code: 'Committee code from the source record' };
  if (names.length) return { text: names.join(' · '), code: '' };
  if (codes.length) return { text: codes.join(' · '), code: 'Committee code' };
  return { text: '', code: '' };
}

export function congressLabel(values: readonly string[] | null | undefined): string {
  if (!values?.length) return '';
  return values.map(value => /^\d+$/.test(value) ? `${value}th Congress` : pretty(value)).join(' · ');
}

export function formatLabel(value: string): string {
  return value.includes('/') ? value : value.toUpperCase();
}

/** An HTTP status worth showing beside a saved copy. A lone 200 repeats a saved response. */
export function httpStatusNote(row: { http_status?: readonly (string | number)[] | null; retained?: boolean | null }): string {
  const statuses = (row.http_status || []).map(String).filter(Boolean);
  if (!statuses.length || (row.retained && statuses.every(value => value === '200'))) return '';
  return `HTTP ${statuses.join(' · ')}`;
}

function formatFamily(value: string): string {
  const text = value.split(';')[0].trim().toLowerCase();
  if (text.includes('pdf')) return 'pdf';
  if (text.includes('html')) return 'html';
  if (text.includes('wordprocessingml') || text === 'docx') return 'docx';
  if (text.includes('msword') || text === 'doc') return 'doc';
  if (text.includes('spreadsheetml') || text === 'xlsx') return 'xlsx';
  if (text.includes('ms-excel') || text === 'xls') return 'xls';
  if (text.includes('presentationml') || text === 'pptx') return 'pptx';
  if (text.includes('ms-powerpoint') || text === 'ppt') return 'ppt';
  if (text === 'text/xml' || text === 'application/xml' || text === 'xml') return 'xml';
  if (text.includes('zip')) return 'zip';
  if (text.includes('json')) return 'json';
  if (text.includes('jpeg') || text === 'jpg') return 'jpeg';
  if (text.includes('png')) return 'png';
  if (text === 'text/plain' || text === 'txt') return 'text';
  return text;
}

const responseDiagnostics: Record<string, string> = {
  html_requires_document_discovery: 'Saved page needs document discovery',
  unrecognized_body: 'Unrecognized saved body',
  pdf_missing_eof: 'PDF is missing its end marker',
  empty_response: 'Empty saved response',
  challenge_html: 'Saved page is a challenge page',
  invalid_xml: 'Saved XML did not parse',
};

function responseFamily(value: string): string {
  if (value === 'zip_or_office') return 'office';
  if (value === 'legacy_office') return 'legacy-office';
  return formatFamily(value);
}

function recordedFamilies(format: readonly string[] | null | undefined): Set<string> {
  const families = new Set((format || []).map(formatFamily));
  if ([...families].some(family => family === 'docx' || family === 'xlsx' || family === 'pptx' || family === 'zip')) families.add('office');
  if ([...families].some(family => family === 'doc' || family === 'xls' || family === 'ppt')) families.add('legacy-office');
  return families;
}

const checkedBodyLabels: Record<string, string> = {
  pdf: 'Checked body includes PDF',
  xml: 'Checked body includes XML',
  rtf: 'Checked body is RTF',
  office: 'Checked body is an Office file or ZIP',
  'legacy-office': 'Checked body is a legacy Office file',
  html: 'Checked body includes HTML',
};

/** A saved-body check that the recorded format does not already state. */
export function responseCheckNote(row: Pick<FilenameRecord, 'format' | 'response_format'>): string {
  const families = recordedFamilies(row.format);
  const notes: string[] = [];
  for (const value of row.response_format || []) {
    const label = responseDiagnostics[value] || (families.has(responseFamily(value)) ? '' : checkedBodyLabels[responseFamily(value)] || '');
    if (label && !notes.includes(label)) notes.push(label);
  }
  return notes.join(' · ');
}

/** The inspected saved body when it is not the same set of formats as the recorded file. */
export function savedBodyNote(row: { format?: readonly string[] | null; body_format?: readonly string[] | null }): string {
  const body = [...new Set(row.body_format || [])];
  const format = new Set(row.format || []);
  if (!body.length || (body.length === format.size && body.every(value => format.has(value)))) return '';
  return `Saved body ${body.map(formatLabel).join(' · ')}`;
}

/** A server-reported type that is not the same kind of file as the recorded format. */
export function serverTypeNote(row: Pick<FilenameRecord, 'format' | 'media_type'>): string {
  const families = new Set((row.format || []).map(formatFamily));
  const reported = [...new Set((row.media_type || []).map(value => value.split(';')[0].trim()).filter(value => value && !families.has(formatFamily(value))))];
  return reported.length ? `Server reported ${reported.join(' · ')}` : '';
}

const kindBasisLabels: Record<string, string> = {
  source_context: 'Based on the source page',
  source_document_type: 'Based on the source document type',
  content: 'Based on the saved contents',
  recovered_filename: 'Based on the recovered filename',
  source_link_label: 'Based on the link text',
};

/** Why a document kind was chosen, when the filename was not the only basis. */
export function kindBasis(row: Pick<FilenameRecord, 'document_kind_source'>): string {
  return (row.document_kind_source || []).filter(value => value && value !== 'filename').map(value => kindBasisLabels[value] || `Based on ${pretty(value)}`).join(' · ');
}

function reading(value: string): string {
  return value.toLowerCase().replaceAll(/[-_]/g, ' ').replaceAll(/\s+/g, ' ').trim();
}

/** Source-page document types that the catalog kind does not already state. */
export function sourceDocumentTypeNote(row: Pick<FilenameRecord, 'document_kind' | 'source_document_type'>): string {
  const kinds = (row.document_kind || []).map(reading).filter(Boolean);
  const extras = (row.source_document_type || []).map(value => value.trim()).filter(value => {
    const text = reading(value);
    if (!text) return false;
    if (kinds.length && text.length <= 3) return false;
    return !kinds.some(kind => kind === text || kind.includes(text) || text.includes(kind));
  });
  return [...new Set(extras.map(pretty))].join(' · ');
}

/** Whether those source-page types were recorded or inferred. */
export function sourceDocumentBasis(row: Pick<FilenameRecord, 'source_document_type_basis'>): string {
  const basis = (row.source_document_type_basis || []).filter(Boolean);
  const inferred = basis.filter(value => /inference|parser|fallback/.test(value));
  if (inferred.length && inferred.length === basis.length) return 'Inferred from the source page';
  if (inferred.length) return 'Includes an inferred reading';
  return basis.length ? 'Recorded on the source page' : '';
}

/** A saved-contents kind that differs from the catalog kind. */
export function contentKindNote(row: Pick<FilenameRecord, 'document_kind' | 'content_document_kind'>): string {
  const kinds = new Set((row.document_kind || []).map(reading));
  const extras = [...new Set((row.content_document_kind || []).map(value => value.trim()).filter(value => {
    const text = reading(value);
    return text && !kinds.has(text);
  }))];
  return extras.length ? `Saved contents read as ${extras.map(pretty).join(' · ')}` : '';
}

/** The day the capture state was last checked. */
export function checkedAtNote(row: Pick<FilenameRecord, 'state_checked_at'>): string {
  const day = String(row.state_checked_at?.[0] || '').slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(day) ? `Checked ${day}` : '';
}

/** The day a response was retrieved, when that day is not the check day. */
export function retrievedAtNote(row: Pick<FilenameRecord, 'state_checked_at' | 'state_retrieved_at'>): string {
  const retrieved = String(row.state_retrieved_at?.[0] || '').slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(retrieved)) return '';
  const checked = String(row.state_checked_at?.[0] || '').slice(0, 10);
  return checked === retrieved ? '' : `Retrieved ${retrieved}`;
}

/** Congress read from the saved contents when the filename and source record do not already state it. */
export function contentCongressNote(row: Pick<FilenameRecord, 'congress' | 'source_congress' | 'content_congress'>): string {
  const known = new Set([...(row.congress || []), ...(row.source_congress || [])]);
  const extras = [...new Set((row.content_congress || []).filter(value => value && !known.has(String(value))))];
  if (!extras.length || !known.size) return '';
  return `Saved contents record ${congressLabel(extras)}`;
}

/** Congress to show when neither the filename nor the source record has one. */
export function contentCongressLabel(row: Pick<FilenameRecord, 'congress' | 'source_congress' | 'content_congress'>): string {
  if (row.congress?.length || row.source_congress?.length) return '';
  return congressLabel(row.content_congress);
}

function httpUrl(value: string | null | undefined): string {
  if (!value) return '';
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : '';
  } catch { return ''; }
}

/** A recovered address when the captured source URL is empty. */
export function recoveredSourceUrl(row: Pick<FilenameRecord, 'source_url' | 'recovered_source_url'>): string {
  if (row.source_url) return '';
  return (row.recovered_source_url || []).map(httpUrl).find(Boolean) || '';
}

export function recoveredSourceHost(row: Pick<FilenameRecord, 'source_url' | 'recovered_source_url'>): string {
  const url = recoveredSourceUrl(row);
  if (!url) return '';
  return `Recovered from ${new URL(url).hostname.replace(/^www\./, '')}`;
}

export function filenameIdentity(row: FilenameRecord): string {
  if (row.video_reference) return `${row.video_reference.provider} video · ${row.video_reference.id}`;
  return row.api_reference?.title || row.filename || '(No filename recorded)';
}

/** The 64-character content hash recorded in a saved-copy key or a bare digest. */
export function contentHash(value: string | null | undefined): string {
  return /[a-f0-9]{64}/i.exec(value || '')?.[0].toLowerCase() || '';
}

/** A saved filename whose first segment is a content hash. */
export function contentAddressedFilename(identity: string): { hash: string; name: string } | null {
  const match = /^([a-f0-9]{64})\.(.+)$/i.exec(identity);
  return match ? { hash: match[1], name: match[2] } : null;
}

/** Usability or completeness readings that a plain “Saved” line would hide. */
export function responseQualityNotes(row: Pick<FilenameRecord, 'response_usable' | 'response_body_complete'>): string[] {
  const notes: string[] = [];
  const usable = new Set(row.response_usable || []);
  const complete = new Set(row.response_body_complete || []);
  if (usable.has('false') && usable.has('true')) notes.push('Usability readings disagree');
  else if (usable.has('false')) notes.push('Saved response marked unusable');
  if (complete.has('false') && complete.has('true')) notes.push('Completeness readings disagree');
  else if (complete.has('false')) notes.push('Incomplete saved response');
  return notes;
}

export function savedResponseLabel(row: FilenameRecord): string {
  const quality = row.retained || row.recovery?.recovery_status === 'recovered' ? responseQualityNotes(row) : [];
  if (row.recovery?.recovery_status === 'recovered') return ['Recovered', ...quality].join(' · ');
  if (!row.retained) return 'None saved';
  if (row.record_role?.includes('error-response')) return ['Saved failed response', ...quality].join(' · ');
  return ['Saved', ...quality].join(' · ');
}

const quietOutcomes = new Set(['saved', 'retained']);
const outcomeLabels: Record<string, string> = {
  http_error: 'HTTP error',
  html: 'HTML response',
  retry_later: 'Retry later',
  pending: 'Fetch pending',
  excluded_probe: 'Excluded probe',
  request_failed: 'Request failed',
  size_limit: 'Over the size limit',
  unverified: 'Unverified fetch',
  no_explicit_download_or_pdf_embed: 'No download or PDF embed',
  invalid_document: 'Invalid document',
  timeout: 'Timed out',
  empty: 'Empty response',
  resource_limit: 'Resource limit',
  excluded_media: 'Excluded media',
  repaired_url: 'Repaired URL',
  excluded_scope: 'Outside the captured scope',
};

/** Fetch results that the saved-copy line does not already state. */
export function captureNotes(row: Pick<FilenameRecord, 'capture_outcome' | 'state_outcome' | 'http_status' | 'format'>): string[] {
  const http = (row.http_status || []).some(value => value !== '' && value != null);
  const htmlFormat = (row.format || []).some(value => value.toLowerCase().includes('html'));
  const notes: string[] = [];
  for (const value of [...(row.capture_outcome || []), ...(row.state_outcome || [])]) {
    if (quietOutcomes.has(value)) continue;
    if (value === 'http_error' && http) continue;
    if (value === 'html' && htmlFormat) continue;
    const label = outcomeLabels[value] || pretty(value);
    if (label && !notes.includes(label)) notes.push(label);
  }
  return notes;
}

export function congressWarning(values: readonly string[] | null | undefined, source: readonly string[] | null | undefined = []): string {
  const items = [...new Set(values ?? [])];
  const recorded = [...(source ?? [])];
  const maxCongress = Math.floor((new Date().getFullYear() - 1789) / 2) + 1;
  const anomalous = items.filter(value => !/^\d+$/.test(value) || Number(value) < 1 || Number(value) > maxCongress + 1);
  const notes: string[] = [];
  if (anomalous.length) notes.push(`Outside the historical/current range: ${anomalous.join(', ')}.`);
  if (items.length > 1) notes.push('Competing filename readings; no Congress has been selected.');
  if (items.length && recorded.length && !items.some(value => recorded.includes(value))) notes.push(`Source context instead records Congress ${recorded.join(' · ')}.`);
  return notes.join(' ');
}

export function measureLabel(value: string): string {
  const match = /^(hconres|sconres|hjres|sjres|hres|sres|hr|s)(\d+)$/i.exec(value);
  if (!match) return value;
  if (match[2].length > 5) return `${value} · Needs review`;
  const names: Record<string, [string, string]> = {
    hr: ['H.R.', 'House bill'], s: ['S.', 'Senate bill'], hres: ['H.Res.', 'House resolution'], sres: ['S.Res.', 'Senate resolution'],
    hjres: ['H.J.Res.', 'House joint resolution'], sjres: ['S.J.Res.', 'Senate joint resolution'],
    hconres: ['H.Con.Res.', 'House concurrent resolution'], sconres: ['S.Con.Res.', 'Senate concurrent resolution'],
  };
  const [prefix, name] = names[match[1].toLowerCase()];
  return `${prefix} ${match[2]} — ${name}`;
}

function wordingValue(values: readonly string[] | null | undefined): string {
  return distinctText(values).map(wordingText).join(' · ');
}

function wordingText(value: string): string {
  const known: Record<string, string> = { rankingmember: 'Ranking member', 'truth-in-testimony': 'Truth in testimony' };
  const recorded = known[value.toLowerCase()];
  if (recorded) return recorded;
  if (value === value.toUpperCase() && /[A-Z]/.test(value)) return value.charAt(0) + value.slice(1).toLowerCase();
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function distinctText(values: readonly string[] | null | undefined): string[] {
  return [...new Set((values || []).map(value => value.trim()).filter(Boolean))];
}

const storedReadingLabels = [
  ['amendment_marker_label', 'Amendment marker'],
  ['citation_marker_label', 'Citation'],
  ['publication_code_label', 'Publication code'],
  ['local_code_token_label', 'Local code'],
  ['version_token_label', 'Version'],
] as const;

/** Stored filename readings whose words are not already the code in the filename. */
export function filenameReadings(row: {
  package_family?: readonly string[] | null;
  package_family_label?: readonly string[] | null;
  document_token_label?: readonly string[] | null;
  document_type?: readonly string[] | null;
  amendment_marker_label?: readonly string[] | null;
  citation_marker_label?: readonly string[] | null;
  publication_code_label?: readonly string[] | null;
  local_code_token_label?: readonly string[] | null;
  revision_marker_label?: readonly string[] | null;
  revision_number?: readonly string[] | null;
  version_token_label?: readonly string[] | null;
  meeting_wording_label?: readonly string[] | null;
  draft_label?: readonly string[] | null;
  enbloc_marker_label?: readonly string[] | null;
  nomination_wording_label?: readonly string[] | null;
  committee_token_label?: readonly string[] | null;
  subcommittee_token_label?: readonly string[] | null;
  scope_token_label?: readonly string[] | null;
  degree_token_label?: readonly string[] | null;
  document_abbreviation_label?: readonly string[] | null;
  document_abbreviation?: readonly string[] | null;
  collection_token_label?: readonly string[] | null;
  qualifier_wording?: readonly string[] | null;
  document_wording?: readonly string[] | null;
  subject_role_wording?: readonly string[] | null;
  context_role_wording?: readonly string[] | null;
  relation_wording?: readonly string[] | null;
}): { label: string; value: string }[] {
  const readings: { label: string; value: string }[] = [];
  const labels = distinctText(row.package_family_label);
  const codes = distinctText(row.package_family).filter(code => !labels.some(label => label.toLowerCase().includes(code.toLowerCase())));
  if (labels.length) readings.push({ label: 'Package', value: [...labels, ...codes].join(' · ') });
  const tokenLabels = distinctText(row.document_token_label);
  const tokens = distinctText(row.document_type).filter(token => !tokenLabels.some(label => label.toLowerCase().includes(token.toLowerCase())));
  if (tokenLabels.length) readings.push({ label: 'Filename token', value: [...tokenLabels, ...tokens].join(' · ') });
  const shown = readings.map(reading => reading.value);
  const revision = distinctText(row.revision_marker_label);
  const revisionNumbers = distinctText(row.revision_number);
  if (revision.length) {
    const value = revision.map((label, index) => {
      const number = revisionNumbers[index] || (revision.length === 1 ? revisionNumbers[0] : '');
      return number && !label.includes(number) ? `${label} ${number}` : label;
    }).join(' · ');
    if (!shown.some(earlier => earlier.toLowerCase().includes(value.toLowerCase()))) {
      readings.push({ label: 'Revision', value });
      shown.push(value);
    }
  }
  const abbreviation = distinctText(row.document_abbreviation_label).map((label, index) => {
    const code = distinctText(row.document_abbreviation)[index] || (distinctText(row.document_abbreviation_label).length === 1 ? distinctText(row.document_abbreviation)[0] : '');
    return code && !label.toLowerCase().includes(code.toLowerCase()) ? `${label} (${code})` : label;
  }).join(' · ');
  const named: [string, string][] = [
    ['Meeting wording', distinctText(row.meeting_wording_label).join(' · ')],
    ['Draft', distinctText(row.draft_label).join(' · ')],
    ['En bloc', distinctText(row.enbloc_marker_label).join(' · ')],
    ['Nomination', distinctText(row.nomination_wording_label).join(' · ')],
    ['Committee', distinctText(row.committee_token_label).join(' · ')],
    ['Subcommittee', distinctText(row.subcommittee_token_label).join(' · ')],
    ['Stage', distinctText(row.scope_token_label).join(' · ')],
    ['Amendment degree', distinctText(row.degree_token_label).join(' · ')],
    ['Abbreviation', abbreviation],
    ['Collection', distinctText(row.collection_token_label).join(' · ')],
    ['Mark', wordingValue(row.qualifier_wording)],
    ['Wording', wordingValue(row.document_wording)],
    ['Role', wordingValue(row.subject_role_wording)],
    ['Context', wordingValue(row.context_role_wording)],
    ['Relation', wordingValue(row.relation_wording)],
  ];
  for (const [label, value] of named) {
    if (!value || shown.some(earlier => earlier.toLowerCase() === value.toLowerCase())) continue;
    readings.push({ label, value });
    shown.push(value);
  }
  for (const [field, label] of storedReadingLabels) {
    const value = distinctText(row[field]).filter(item => !shown.some(earlier => earlier.toLowerCase().includes(item.toLowerCase()))).join(' · ');
    if (!value) continue;
    readings.push({ label, value });
    shown.push(value);
  }
  return readings;
}

export function filenameClues(row: FilenameRecord): string[] {
  const warning = congressWarning(row.congress, row.source_congress);
  return [
    row.congress?.length ? `Filename Congress ${row.congress.join(' · ')}${warning ? ' · Needs review' : ''}` : '',
    row.committee_code?.length ? `Committee ${row.committee_code.join(' · ')}` : '',
    row.measure_references?.map(measureLabel).join(' · ') || '',
    row.date_token_candidates?.map(filenameDate).join(' · ') || '',
  ].filter(Boolean);
}

export function reviewStatusLabel(status: string | undefined): string {
  if (status === 'candidate_applied') return 'Assistant-reviewed category';
  if (status === 'annotation_only_unsupported_forms') return 'Review notes; original category';
  return '';
}

function readableLines(value: unknown, prefix = ''): string[] {
  if (Array.isArray(value)) {
    if (value.every(item => item == null || typeof item !== 'object')) {
      const text = value.filter(item => item != null && item !== '').map(String).join(' · ');
      return text ? [prefix ? `${prefix}: ${text}` : text] : [];
    }
    return value.flatMap((item, index) => readableLines(item, [prefix, String(index + 1)].filter(Boolean).join(' ')));
  }
  if (value && typeof value === 'object') {
    const lines: string[] = [];
    for (const [key, item] of Object.entries(value)) {
      const path = [prefix, key.replaceAll('_', ' ')].filter(Boolean).join(' · ');
      if (item && typeof item === 'object') lines.push(...readableLines(item, path));
      else if (item != null && item !== '') lines.push(`${path}: ${item}`);
    }
    return lines;
  }
  return value == null || value === '' ? [] : [prefix ? `${prefix}: ${value}` : String(value)];
}

/** Recorded objects and lists as labeled lines, keeping every scalar value. */
export function readableValue(value: unknown): string {
  if (value == null || value === '') return '';
  if (typeof value !== 'object') return String(value);
  return readableLines(value).join('\n');
}
