import {loadPublication} from './publication.ts';
import {createStableFilenameCatalog} from './catalog-v6.ts';
export {rangeFile, sourceContext, savedCopyUrl, apiReference, videoReference} from './catalog-v6.ts';

export async function createFilenameCatalog(url: string, fetcher: typeof fetch = fetch, catalogId?: string | null, reviews?: unknown, options = {}) {
  const publication = await loadPublication(url, fetcher, catalogId);
  if (publication.manifest.version !== 6) throw new Error('Unsupported filename catalog version.');
  return createStableFilenameCatalog(publication, fetcher, reviews, options);
}
