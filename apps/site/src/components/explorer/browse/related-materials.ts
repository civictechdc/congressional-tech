import type { MaterialCategory, RelatedOptions } from '../reader/types.ts';
import { listedDocumentType } from './record-presentation.ts';

interface MaterialLike {
  kind: string;
  id: string;
  title?: string | null;
  type?: string | null;
  document_type?: string | null;
  category?: string | null;
  details?: { type?: string | null; category?: string | null } | null;
}

function foldedTitle(value: string): string {
  return value.toLowerCase().replaceAll(/[“”„«»"]/g, '').replaceAll(/[‘’']/g, '').replaceAll(/[.,:;]+/g, ' ').replaceAll(/\s+/g, ' ').trim();
}

/** Keep related documents under the meeting they came from, in the order each meeting first appears. */
export function groupByMeeting<T>(records: readonly T[], meetingId: (record: T) => string): { meetingId: string; items: T[] }[] {
  const order: string[] = [];
  const groups = new Map<string, T[]>();
  for (const record of records) {
    const id = meetingId(record);
    if (!groups.has(id)) {
      order.push(id);
      groups.set(id, []);
    }
    groups.get(id)?.push(record);
  }
  return order.map(id => ({ meetingId: id, items: groups.get(id) || [] }));
}

/** One time for a meeting group when every document in it records that same time. */
export function sharedText(values: readonly string[]): string {
  const present = values.filter(Boolean);
  if (!present.length || present.some(value => value !== present[0])) return '';
  return present[0];
}

/** The meeting heading: its title, plus the shared time when every document has that time. */
export function meetingGroupLabel(title: string, sharedWhen: string): string {
  if (!title) return '';
  return sharedWhen ? `${title} · ${sharedWhen}` : title;
}

/** Drop a committee name from a meeting or subcommittee title when the reader is already on that committee. */
export function titleInContext(title: string, context: string): string {
  const prefixes = [
    context.trim(),
    context.trim().replace(/^(?:joint\s+)?(?:select\s+)?committee\s+on\s+/i, '').trim(),
  ].filter((prefix, index, list) => prefix.length >= 12 && list.indexOf(prefix) === index);
  for (const prefix of prefixes) {
    const pattern = new RegExp(`^${prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[\\s,.:–—-]*`, 'i');
    const rest = title.replace(pattern, '').trim();
    if (rest && rest !== title) return rest;
  }
  return title;
}

/** True when two recorded titles differ only by quotation marks, spacing, or a short prefix. */
export function sameRecordedTitle(left: string, right: string): boolean {
  const a = foldedTitle(left);
  const b = foldedTitle(right);
  if (!a || !b) return false;
  if (a === b) return true;
  const [shorter, longer] = a.length < b.length ? [a, b] : [b, a];
  return shorter.length >= 24 && longer.includes(shorter);
}

/** The link text for a related recording or document. A recording keeps its recorded title. */
export function relatedMaterialTitle(row: { title?: string | null; type?: string | null }, category: string, filename = ''): string {
  const title = (row.title || '').trim();
  const generic = !title || title.toLowerCase() === category.toLowerCase() || title.toLowerCase() === 'recording';
  if (row.type === 'recording') return generic ? 'Watch recording' : title;
  if (generic && filename) return filename;
  return title || filename || category || 'Untitled record';
}

const categoryNames: Record<string, string> = {
  questions_for_record: 'Questions for the record',
};

/** A recorded document category in ordinary words. */
export function recordedCategoryLabel(value: string): string {
  const named = categoryNames[value];
  if (named) return named;
  const text = value.replaceAll('_', ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function materialCategory(record: MaterialLike): string {
  if (record.document_type) return listedDocumentType(record.document_type);
  const details = record.details || record;
  if (details.type === 'recording') return 'Recording';
  const category = details.category;
  return category && category !== 'unknown' ? recordedCategoryLabel(category) : details.type === 'text' ? 'Captions or transcript' : 'Document';
}

export function selectRelatedMaterials<T extends MaterialLike>(records: readonly T[], options: Pick<RelatedOptions, 'materialType' | 'category'> = {}): { rows: T[]; categories: MaterialCategory[] } {
  const { materialType, category } = options;
  const rows = records.filter(record => record.kind === 'material' && (!materialType
    || ((record.type || record.details?.type) === 'recording') === (materialType === 'recording')));
  const counts = new Map<string, number>();
  for (const row of rows) counts.set(materialCategory(row), (counts.get(materialCategory(row)) || 0) + 1);
  const categories = [...counts].map(([label, count]) => ({ label, count })).sort((a, b) => a.label.localeCompare(b.label));
  const selected = rows.filter(row => !category || materialCategory(row) === category);
  selected.sort((a, b) => materialCategory(a).localeCompare(materialCategory(b)) || (a.title || '').localeCompare(b.title || '') || a.id.localeCompare(b.id));
  return { rows: selected, categories };
}
