/** Kind words a release lists as one kind (ct-isnv), shared by the reader worker and the Document type menu. */

/** The sets from the release's schema.json (list.parquet synonyms); none for a release published before them. */
export function kindSynonymSets(schema: any): string[][] {
  const sets = (schema?.files ?? []).find((file: any) => file?.name === 'list.parquet')?.synonyms?.['document_kind[]'];
  return Array.isArray(sets) && sets.every(words => Array.isArray(words) && words.every(word => typeof word === 'string')) ? sets : [];
}

/** Each wanted kind with every word listed as the same kind, so a filter or bookmark for either word selects the set. */
export function withKindSynonyms(wanted: string[], sets: string[][]): string[] {
  return [...new Set(wanted.flatMap(kind => sets.find(words => words.includes(kind)) ?? [kind]))];
}

/** The word a set is shown under: its first, the House naming guide's word. */
export function canonicalKind(kind: string, sets: string[][]): string {
  return sets.find(words => words.includes(kind))?.[0] ?? kind;
}

/** One menu entry per kind. The summed count overstates rows carrying two words of one set (0 in the next release). */
export function mergeKindFacets(facets: {facet: string; value: string; count: number | string}[], sets: string[][]) {
  const merged = new Map<string, number>();
  for (const item of facets) {
    const value = canonicalKind(String(item.value), sets);
    merged.set(value, (merged.get(value) ?? 0) + Number(item.count));
  }
  return [...merged].map(([value, count]) => ({facet: 'document_kind', value, count}));
}
