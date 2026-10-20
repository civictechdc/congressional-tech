import type { Navigation } from './navigation.ts';
import type { FilenameCatalogInfo } from '../reader/filenames/types.ts';
import { PAGE_SIZE } from './query-utils.ts';

function facetValues(info: FilenameCatalogInfo, key: 'congress' | 'document_family' | 'document_kind' | 'format'): string[] {
  return info.review_facets?.[key] || info.facets[key] || [];
}

export function filenameSearchParams(nav: Navigation, info: FilenameCatalogInfo): string {
  const params = new URLSearchParams();
  if (nav.q) params.set('q', nav.q);
  if (nav.field && nav.field !== 'filename') params.set('field', nav.field);
  if (nav.scope === 'capture-records' || nav.scope === 'all') params.set('scope', nav.scope);
  if (nav.retained) params.set('retained', nav.retained);
  if (nav.document_family) params.set('document_family', nav.document_family);
  if (nav.document_kind) params.set('document_kind', nav.document_kind);
  if (nav.format) params.set('format', nav.format);
  if (nav.congress !== 'all' && facetValues(info, 'congress').includes(nav.congress)) params.set('congress', nav.congress);
  if (nav.classification === 'reviewed') {
    params.set('classification', 'reviewed');
    const pin = nav.review || info.review_sha256 || '';
    if (pin) params.set('review', pin);
  }
  params.set('page', String(nav.page + 1));
  params.set('limit', String(PAGE_SIZE));
  return params.toString();
}
