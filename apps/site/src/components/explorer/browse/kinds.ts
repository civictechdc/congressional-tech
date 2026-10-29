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

export const materialCategories = [
  'statement', 'amendment', 'transcript', 'supporting', 'disclosure', 'biography', 'bill_text', 'vote',
  'witness_list', 'questions_for_record', 'hearing_record', 'report', 'errata', 'notice', 'committee_print', 'unknown',
] as const;
export type MaterialCategoryName = (typeof materialCategories)[number];
const materialCategorySet: ReadonlySet<string> = new Set(materialCategories);
export const isMaterialCategory = (value: string): value is MaterialCategoryName => materialCategorySet.has(value);

export const issueCategories = ['unlinked', 'unverified', 'conflicting', 'duplicate', 'incorrect'] as const;
export type IssueCategory = (typeof issueCategories)[number];
const issueCategorySet: ReadonlySet<string> = new Set(issueCategories);
export const isIssueCategory = (value: string): value is IssueCategory => issueCategorySet.has(value);

export const materialProviders = [
  'youtube', 'www.senate.gov', 'senate', 'www.c-span.org', 'www.facebook.com',
  'www-senate-gov-msl3archive.akamaized.net', 'web.archive.org', 'www.jec.senate.gov', 'www.dvidshub.net',
] as const;
export type MaterialProvider = (typeof materialProviders)[number];
const materialProviderSet: ReadonlySet<string> = new Set(materialProviders);
export const isMaterialProvider = (value: string): value is MaterialProvider => materialProviderSet.has(value);

export const meetingStatuses = ['upcoming', 'past', 'today', 'postponed', 'canceled'] as const;
export type MeetingStatus = (typeof meetingStatuses)[number];
const meetingStatusSet: ReadonlySet<string> = new Set(meetingStatuses);
export const isMeetingStatus = (value: string): value is MeetingStatus => meetingStatusSet.has(value);

export const issueHistories = ['current', 'retained'] as const;
export type IssueHistory = (typeof issueHistories)[number];
const issueHistorySet: ReadonlySet<string> = new Set(issueHistories);
export const isIssueHistory = (value: string): value is IssueHistory => issueHistorySet.has(value);

export const issueStatuses = ['open', 'resolved', 'dismissed'] as const;
export type IssueStatus = (typeof issueStatuses)[number];
const issueStatusSet: ReadonlySet<string> = new Set(issueStatuses);
export const isIssueStatus = (value: string): value is IssueStatus => issueStatusSet.has(value);

export const witnessParticipations = ['testified', 'listed'] as const;
export type WitnessParticipation = (typeof witnessParticipations)[number];
const witnessParticipationSet: ReadonlySet<string> = new Set(witnessParticipations);
export const isWitnessParticipation = (value: string): value is WitnessParticipation => witnessParticipationSet.has(value);

export const issueSeverities = ['affects_interpretation', 'informational'] as const;
export type IssueSeverity = (typeof issueSeverities)[number];
const issueSeveritySet: ReadonlySet<string> = new Set(issueSeverities);
export const isIssueSeverity = (value: string): value is IssueSeverity => issueSeveritySet.has(value);
