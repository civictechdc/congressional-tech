// Published positional generations remain readable; new publication uses v6.
import {loadPublication} from './publication.ts';
import {createFilenameCatalog as historical} from './catalog-v5.ts';
import {createStableFilenameCatalog} from './catalog-v6.ts';
export {rangeFile, sourceContext, savedCopyUrl, apiReference, videoReference} from './catalog-v5.ts';

export async function createFilenameCatalog(url: string, fetcher: typeof fetch = fetch, catalogId?: string | null, reviews?: unknown, options = {}) {
  const publication = await loadPublication(url, fetcher, catalogId);
  return publication.manifest.version === 6
    ? createStableFilenameCatalog(publication, fetcher, reviews, options)
    : historical(url, fetcher, catalogId, reviews, {...options, publication});
}
