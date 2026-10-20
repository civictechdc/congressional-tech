export const coverageAspects = ['recording', 'transcript', 'documents', 'witnesses', 'captions'] as const;
export type CoverageAspect = (typeof coverageAspects)[number];

export const evidenceStates = [
  'observed', 'reported', 'curated', 'derived', 'inferred', 'error', 'blocked',
  'not_found_in_checked_scope', 'not_applicable', 'unknown', 'unchecked',
] as const;
export type EvidenceState = (typeof evidenceStates)[number];

export const viewKeys = ['meetings', 'committees', 'materials', 'witnesses', 'coverage', 'gaps'] as const;
export type View = (typeof viewKeys)[number];

export const accessStates = ['open', 'closed', 'partly_closed', 'unknown'] as const;
export type AccessState = (typeof accessStates)[number];

export const committeeTypes = [
  'standing', 'select', 'joint', 'special', 'other', 'commission_or_caucus', 'task_force', 'unknown',
] as const;
export type CommitteeType = (typeof committeeTypes)[number];

const coverageSet: ReadonlySet<string> = new Set(coverageAspects);
const viewSet: ReadonlySet<string> = new Set(viewKeys);
const accessSet: ReadonlySet<string> = new Set(accessStates);
const committeeTypeSet: ReadonlySet<string> = new Set(committeeTypes);
const evidenceSet: ReadonlySet<string> = new Set(evidenceStates);

export const isCoverageAspect = (value: string): value is CoverageAspect => coverageSet.has(value);
export const isView = (value: string): value is View => viewSet.has(value);
export const isAccessState = (value: string): value is AccessState => accessSet.has(value);
export const isCommitteeType = (value: string): value is CommitteeType => committeeTypeSet.has(value);
export const isEvidenceState = (value: string): value is EvidenceState => evidenceSet.has(value);
