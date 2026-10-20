import {withVerifiedJson} from './startup.mjs';

// Saved sidecars reach 12.6 MB. Allow bounded growth and a separate mandatory
// status deadline; the evidence and policy rationale live in recovery.md.
export const recoveryStartupPolicy = Object.freeze({deadlineMs: 30_000, maxBytes: 32 * 1024 * 1024});

/** A status overlay leaves every original catalog and fetch field intact. */
export async function loadRecoveries(descriptor, info, fetcher, configuredPolicy = {}) {
  if (!descriptor) return {sources: new Map(), groups: new Map()};
  const policy = {...recoveryStartupPolicy, ...configuredPolicy};
  return withVerifiedJson(policy, 'Recovered document status', async verified => {
    const data = await verified(fetcher, descriptor.url, descriptor.sha256, descriptor.bytes, 'recovered document status');
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
  }, configuredPolicy.signal);
}
