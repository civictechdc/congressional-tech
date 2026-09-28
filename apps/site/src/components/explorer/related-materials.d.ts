import type { MaterialCategory, RelatedOptions } from './data-source';
export function materialCategory(record: unknown): string;
export function selectRelatedMaterials<T extends { kind: string; id: string }>(records: readonly T[], options?: RelatedOptions): { rows: T[]; categories: MaterialCategory[] };
