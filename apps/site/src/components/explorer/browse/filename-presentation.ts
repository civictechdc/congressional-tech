import type { FilenameRecord } from '../reader/filenames/types.ts';
import { filenameDate } from './filename-rules.ts';

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
  source_occurrences: 'Related source observations',
};

export function fieldLabel(key: string): string {
  return (fieldLabels[key] || key.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase()))
    .replace(/\b(url|id|uuid|http|pdf|xml|api)\b/gi, match => match.toUpperCase());
}

export function pretty(value: string): string {
  return value.replaceAll('_', ' ').replaceAll('-', ' ').replace(/^./, letter => letter.toUpperCase());
}

export function documentKindLabel(row: { video_reference?: unknown; api_reference?: unknown; document_kind?: string[] | null }): string {
  if (row.video_reference) return 'Video reference';
  if (row.api_reference) return 'Source/API reference';
  return row.document_kind?.map(pretty).join(' · ') || 'Unclassified';
}

export function congressLabel(values: readonly string[] | null | undefined): string {
  if (!values?.length) return '';
  return values.map(value => /^\d+$/.test(value) ? `${value}th Congress` : pretty(value)).join(' · ');
}

export function formatLabel(value: string): string {
  return value.includes('/') ? value : value.toUpperCase();
}

export function filenameIdentity(row: FilenameRecord): string {
  if (row.video_reference) return `${row.video_reference.provider} video · ${row.video_reference.id}`;
  return row.api_reference?.title || row.filename || '(No filename recorded)';
}

export function savedResponseLabel(row: FilenameRecord): string {
  if (row.recovery?.recovery_status === 'recovered') return 'Recovered';
  if (!row.retained) return 'None saved';
  if (row.record_role?.includes('error-response')) return 'Saved failed response';
  if (row.response_usable?.includes('false') || row.response_body_complete?.includes('false')) return 'Saved · needs review';
  return 'Saved';
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
