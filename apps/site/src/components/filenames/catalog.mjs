// Published positional generations are read-only; all new publication uses v6.
import {loadPublication} from './publication.mjs';
import {createFilenameCatalog as historical} from './catalog-v5.mjs';
import {createStableFilenameCatalog} from './catalog-v6.mjs';
export {rangeFile, sourceContext, savedCopyUrl, apiReference, videoReference} from './catalog-v5.mjs';

export async function createFilenameCatalog(url, fetcher = fetch, catalogId, reviews, options = {}) {
  const publication = await loadPublication(url, fetcher, catalogId);
  return publication.manifest.version === 6
    ? createStableFilenameCatalog(publication, fetcher, reviews, options)
    : historical(url, fetcher, catalogId, reviews, {...options, publication});
}
