/** A pinned publication of assistant findings bound to one original catalog pair. */
export async function loadReviews(descriptor, manifest, fetcher) {
  const empty = {groups: new Map(), sources: new Map(), info: {}};
  if (!descriptor || descriptor.catalog_id !== manifest.info.catalog_id) return empty;
  try {
    const response = await fetcher(descriptor.url);
    if (!response.ok) throw new Error('Could not load the document reviews.');
    const bytes = await response.arrayBuffer();
    const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('');
    if (hash !== descriptor.sha256 || bytes.byteLength !== descriptor.bytes) throw new Error('Document review publication failed verification.');
    const data = JSON.parse(new TextDecoder().decode(bytes));
    if (data.version !== 1 || data.catalog_id !== manifest.info.catalog_id || data.review_sha256 !== descriptor.review_sha256 ||
        ['filenames','documents'].some(name => data.baseline[name] !== manifest.source_manifest?.files[name]?.sha256)) {
      throw new Error('Document reviews belong to a different catalog pair.');
    }
    const groups = new Map(), sources = new Map(), facets = {};
    for (const row of data.rows) {
      if (!Number.isInteger(row.group) || row.group < 0 || row.group >= manifest.info.entries || groups.has(row.group) ||
          !['candidate_applied','annotation_only_unsupported_forms'].includes(row.status) || !row.sources.length) throw new Error('Invalid reviewed group.');
      if (row.status === 'annotation_only_unsupported_forms' && JSON.stringify(row.baseline) !== JSON.stringify(row.selected)) throw new Error('Unsupported forms changed catalog categories.');
      for (const field of ['document_kind','document_family','document_kind_source']) {
        for (const value of [row.baseline[field], row.selected[field]]) if (value != null && (!Array.isArray(value) || value.some(item => typeof item !== 'string'))) throw new Error('Invalid reviewed classification.');
      }
      for (const source of row.sources) {
        if (!Number.isInteger(source) || source < 0 || source >= manifest.info.rows || sources.has(source)) throw new Error('Invalid reviewed source.');
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
  } catch (error) {
    return {...empty, info: {complete_body_reviews: true, reviewed_search: false, review_error: error.message}};
  }
}

export function reviewedMode(query, info) {
  if (!['', 'reviewed'].includes(query.classification || '')) throw new Error('Unknown classification mode.');
  if (query.classification !== 'reviewed') return false;
  if (!info.reviewed_search) throw new Error(info.review_error || 'Reviewed-category search is not configured.');
  if (query.review && query.review !== info.review_sha256) throw new Error('This search belongs to a different review snapshot.');
  return true;
}
