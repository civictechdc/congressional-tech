/** Display categories preserve native documentType; our enum supplies the fallback. */
export function materialCategory(record) {
  if (record.document_type) return record.document_type;
  const details = record.details || record;
  if (details.type === 'recording') return 'Recording';
  const category = details.category;
  const label = category && category !== 'unknown' ? category.replaceAll('_', ' ') : details.type === 'text' ? 'Text product' : 'Document';
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/** Counts describe every matching attachment before category filtering or paging. */
export function selectRelatedMaterials(records, { materialType, category } = {}) {
  const rows = records.filter(record => record.kind === 'material' && (!materialType
    || ((record.type || record.details?.type) === 'recording') === (materialType === 'recording')));
  const counts = new Map();
  for (const row of rows) {
    const label = materialCategory(row);
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  const categories = [...counts].map(([label, count]) => ({ label, count })).sort((a, b) => a.label.localeCompare(b.label));
  const selected = rows.filter(row => !category || materialCategory(row) === category);
  selected.sort((a, b) => materialCategory(a).localeCompare(materialCategory(b)) || (a.title || '').localeCompare(b.title || '') || a.id.localeCompare(b.id));
  return { rows: selected, categories };
}
