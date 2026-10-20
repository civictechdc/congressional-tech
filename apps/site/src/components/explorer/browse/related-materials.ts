import type { MaterialCategory, RelatedOptions } from '../reader/types.ts';

interface MaterialLike {
  kind: string;
  id: string;
  title?: string | null;
  type?: string | null;
  document_type?: string | null;
  category?: string | null;
  details?: { type?: string | null; category?: string | null } | null;
}

export function materialCategory(record: MaterialLike): string {
  if (record.document_type) return record.document_type;
  const details = record.details || record;
  if (details.type === 'recording') return 'Recording';
  const category = details.category;
  const label = category && category !== 'unknown' ? category.replaceAll('_', ' ') : details.type === 'text' ? 'Text product' : 'Document';
  return label.charAt(0).toUpperCase() + label.slice(1);
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
