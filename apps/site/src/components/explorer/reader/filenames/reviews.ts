// @ts-nocheck
import {withVerifiedJson} from './startup.ts';

export const reviewStartupPolicy = Object.freeze({deadlineMs: 15_000, maxBytes: 16 * 1024 * 1024});

/**
 * Assistant findings, published once, placed on the current catalog version.
 * A viewer publication with a review binding supplies this version's positions
 * for each review whose document, members and body are unchanged; withdrawn
 * reviews keep the original categories. Without a binding, the reviews apply
 * only to the exact catalog pair they were exported from.
 */
export async function loadReviews(descriptor, manifest, fetcher, manifestUrl, configuredPolicy = {}) {
  const empty = {groups: new Map(), sources: new Map(), info: {}};
  const bound = manifest.files?.review_binding;
  if (!descriptor || (!bound && descriptor.catalog_id !== manifest.info.catalog_id)) return empty;
  const policy = {...reviewStartupPolicy, ...configuredPolicy};
  try {
    return await withVerifiedJson(policy, 'Document reviews', async verified => {
      let placement = null;
      if (bound) {
        const binding = await verified(fetcher, new URL(bound.path, manifestUrl).href, bound.sha256, bound.bytes, 'document review binding');
        if (binding.version !== (manifest.version === 6 ? 2 : 1) || binding.review_sha256 !== descriptor.review_sha256 || binding.catalog_id !== manifest.info.catalog_id) {
          throw new Error('Document review binding belongs to a different publication.');
        }
        placement = new Map(binding.rows.map(row => [row.index, row]));
      }
      const data = await verified(fetcher, descriptor.url, descriptor.sha256, descriptor.bytes, 'document review publication');
      if (data.version !== 1 || data.review_sha256 !== descriptor.review_sha256 || (!placement && (data.catalog_id !== manifest.info.catalog_id ||
          ['filenames','documents'].some(name => data.baseline[name] !== manifest.source_manifest?.files[name]?.sha256)))) {
        throw new Error('Document reviews belong to a different catalog pair.');
      }
      const groups = new Map(), sources = new Map(), facets = {};
      for (const [index, row] of data.rows.entries()) {
        if (placement) {
          const place = placement.get(index);
          if (!place) continue;
          if (manifest.version === 6 && place.document_id !== row.document_id) throw new Error('Reviewed document stable identity differs.');
          row.group = manifest.version === 6 ? place.document_id : place.group;
          row.sources = manifest.version === 6 ? place.source_ids : place.sources;
        }
        if ((manifest.version === 6 ? typeof row.group !== 'string' || !row.group :
            !Number.isInteger(row.group) || row.group < 0 || row.group >= manifest.info.entries) || groups.has(row.group) ||
            !['candidate_applied','annotation_only_unsupported_forms'].includes(row.status) || !row.sources.length) throw new Error('Invalid reviewed group.');
        if (row.status === 'annotation_only_unsupported_forms' && JSON.stringify(row.baseline) !== JSON.stringify(row.selected)) throw new Error('Unsupported forms changed catalog categories.');
        for (const field of ['document_kind','document_family','document_kind_source']) {
          for (const value of [row.baseline[field], row.selected[field]]) if (value != null && (!Array.isArray(value) || value.some(item => typeof item !== 'string'))) throw new Error('Invalid reviewed classification.');
        }
        for (const source of row.sources) {
          if ((manifest.version === 6 ? !/^[a-f0-9]{64}$/.test(source) :
              !Number.isInteger(source) || source < 0 || source >= manifest.info.rows) || sources.has(source)) throw new Error('Invalid reviewed source.');
          sources.set(source, row);
        }
        const links = {...row.evidence, pages: {...row.evidence.pages}};
        const evidenceUrl = path => {
          if (!/^evidence\/[a-f0-9]{64}\.(pdf|png|txt)$/.test(path) || !data.files[path]) throw new Error('Invalid review evidence link.');
          return new URL(path, descriptor.url).href;
        };
        for (const key of Object.keys(links)) if (key !== 'pages') links[key] = evidenceUrl(links[key]);
        if (Object.keys(links.pages).length !== row.review.body_observation.pages) throw new Error('Incomplete reviewed pages.');
        for (let page = 1; page <= row.review.body_observation.pages; page++) links.pages[page] = evidenceUrl(links.pages[page]);
        row.evidence = links;
        groups.set(row.group, row);
      }
      for (const field of ['document_kind','document_family']) facets[field] = [...new Set([
        ...manifest.info.facets[field], ...[...groups.values()].filter(row => row.status === 'candidate_applied').flatMap(row => row.selected[field] || [])])].sort();
      return {groups, sources, info: {complete_body_reviews: true, reviewed_search: true, review_sha256: data.review_sha256,
        reviewed_groups: [...groups.values()].filter(row => row.status === 'candidate_applied').length, review_facets: facets}};
    }, configuredPolicy.signal);
  } catch (error) {
    return {...empty, info: {complete_body_reviews: true, reviewed_search: false, review_error: error.message}};
  }
}

export function reviewedMode(query, info) {
  if (!['', 'reviewed'].includes(query.classification || '')) throw new Error('Unknown classification mode.');
  if (query.classification !== 'reviewed') return false;
  if (!info.reviewed_search) throw new Error(info.review_error || 'Reviewed-category search is not configured.');
  if (query.review && query.review !== info.review_sha256) throw new Error('This search belongs to an older review. Reset the filters and search again.');
  return true;
}
