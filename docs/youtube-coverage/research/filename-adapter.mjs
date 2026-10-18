/** Keep published-worker and local-comparison routes explicit. */
export function createViewerAdapter({mode, workerApi, fetcher}) {
  if (!['published','local'].includes(mode)) throw new Error('Unknown filename viewer mode.');
  const publicUrl = value => {try {const url=new URL(value);return /^https?:$/.test(url.protocol)&&!url.username&&!url.password ? url.href : null;}catch{return null;}};
  const published = entry => mode === 'published' || entry?.published_only === true;
  const identityQuery = entry => encodeURIComponent(entry.record.source_id)+'?catalog='+encodeURIComponent(entry.catalog_id);
  return {
    published,
    reading: entry => mode === 'local' ? entry.reading : null,
    async request(url,signal) {
      if (mode === 'published') {
        const api=workerApi();
        if(typeof api!=='function')throw new Error('The published catalog reader is unavailable. Reload this page to retry.');
        return api(url,signal);
      }
      const response=await fetcher(url,{signal}),data=await response.json();
      if(!response.ok)throw new Error(data.error||'Could not read the catalog.');
      return data;
    },
    savedUrl(entry) {
      const value=publicUrl(entry.saved_file_url);
      if(value)return value;
      return mode==='local' && entry.saved_file_available ? '/saved/'+identityQuery(entry) : null;
    },
    reviewEvidence(entry,result,kind,page) {
      const value=result.evidence && (kind==='page' ? result.evidence.pages?.[page] : result.evidence[kind]);
      if(value && (mode==='local' || publicUrl(value)))return value;
      if(mode==='published')throw new Error('The published review is missing its verified evidence link.');
      return '/review-evidence/'+identityQuery(entry)+'&kind='+kind+(page?'&page='+page:'');
    }
  };
}
