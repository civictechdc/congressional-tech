// @ts-nocheck
import {withVerifiedJson, canonicalJson} from './startup.ts';

// Saved sidecars reach 12.6 MB. Allow bounded growth and a separate mandatory
// status deadline; the evidence and policy rationale live in recovery.md.
export const recoveryStartupPolicy = Object.freeze({deadlineMs: 30_000, maxBytes: 32 * 1024 * 1024});

/** A status overlay leaves every original catalog and fetch field intact. */
export async function loadRecoveries(descriptor, info, fetcher, configuredPolicy = {}) {
  if (!descriptor) return {sources: new Map(), groups: new Map()};
  const policy = {...recoveryStartupPolicy, ...configuredPolicy};
  return withVerifiedJson(policy, 'Recovered document status', async verified => {
    const data = await verified(fetcher, descriptor.url, descriptor.sha256, descriptor.bytes, 'recovered document status');
    if (data.version !== (configuredPolicy.sourceIdentity ? 2 : 1) || data.catalog_id !== info.catalog_id || data.rows !== info.rows || data.entries !== info.entries) throw new Error('Recovered document status belongs to a different catalog.');
    const recovery = index => {
      const value = data.recoveries[index];
      if (!Number.isSafeInteger(index) || index < 0 || !value || value.recovery_status !== 'recovered') throw new Error('Invalid recovered document status.');
      return value;
    };
    if (configuredPolicy.sourceIdentity && (data.version !== 2 || canonicalJson(data.source_identity) !== canonicalJson(configuredPolicy.sourceIdentity))) throw new Error('Recovered document status belongs to a different selected snapshot.');
    const positions = (pairs, maximum, value, source = false) => {
      const result = new Map();
      for (const pair of pairs) {
        const [position, match] = data.version === 2 && source ? [pair[0], pair[2]] : pair;
        if ((data.version === 2 ? source ? !/^[a-f0-9]{64}$/.test(position) || typeof pair[1] !== 'string' || !pair[1] :
            typeof position !== 'string' || !position : !Number.isInteger(position) || position < 0 || position >= maximum) || result.has(position)) throw new Error('Invalid recovery position.');
        result.set(position, value(match));
      }
      return result;
    };
    const sources = positions(data.sources, info.rows, recovery, true), groups = positions(data.groups, info.entries, matches => {
      if (!Array.isArray(matches) || !matches.length || new Set(matches).size !== matches.length) throw new Error('Empty recovery group.');
      return matches.map(recovery);
    });
    if (sources.size > info.rows || groups.size > info.entries || data.version === 2 && data.sources.some(([id,document,index])=>!groups.get(document)?.includes(recovery(index)))) throw new Error('Recovery source and document memberships differ.');
    return {sources, groups};
  }, configuredPolicy.signal);
}
