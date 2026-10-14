/** A status overlay leaves every original catalog and fetch field intact. */
export async function loadRecoveries(descriptor, info, fetcher) {
  if (!descriptor) return {sources: new Map(), groups: new Map()};
  const response = await fetcher(descriptor.url);
  if (!response.ok) throw new Error('Could not load recovered document status.');
  const bytes = await response.arrayBuffer();
  const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('');
  if (bytes.byteLength !== descriptor.bytes || hash !== descriptor.sha256) throw new Error('Recovered document status failed verification.');
  const data = JSON.parse(new TextDecoder().decode(bytes));
  if (data.version !== 1 || data.catalog_id !== info.catalog_id || data.rows !== info.rows || data.entries !== info.entries) throw new Error('Recovered document status belongs to a different catalog.');
  const recovery = index => {
    const value = data.recoveries[index];
    if (!value || value.recovery_status !== 'recovered') throw new Error('Invalid recovered document status.');
    return value;
  };
  const positions = (pairs, maximum, value) => {
    const result = new Map();
    for (const [position, match] of pairs) {
      if (!Number.isInteger(position) || position < 0 || position >= maximum || result.has(position)) throw new Error('Invalid recovery position.');
      result.set(position, value(match));
    }
    return result;
  };
  return {sources: positions(data.sources, info.rows, recovery), groups: positions(data.groups, info.entries, matches => {
    if (!matches.length) throw new Error('Empty recovery group.');
    return matches.map(recovery);
  })};
}
