import congressMetadata from '../../../data/congress_metadata.json' with { type: 'json' };

const standingCommittees: Record<string, string> = {
  hsag00: 'House Agriculture',
  hsap00: 'House Appropriations',
  hsas00: 'House Armed Services',
  hsba00: 'House Financial Services',
  hsbu00: 'House Budget',
  hsed00: 'House Education & Workforce',
  hsfa00: 'House Foreign Affairs',
  hsgo00: 'House Oversight & Accountability',
  hsha00: 'House Administration',
  hshm00: 'House Homeland Security',
  hsif00: 'House Energy & Commerce',
  hsii00: 'House Natural Resources',
  hsju00: 'House Judiciary',
  hspw00: 'House Transportation & Infrastructure',
  hsru00: 'House Rules',
  hssm00: 'House Small Business',
  hsso00: 'House Ethics',
  hssy00: 'House Science, Space, & Technology',
  hsvr00: "House Veterans' Affairs",
  hswm00: 'House Ways & Means',
  hlig00: 'House Intelligence',
  hlcn00: 'House Select Climate Crisis',
  hlef00: 'House Select Economic Disparity',
  hlfd00: 'House Select Weaponization of the Federal Government',
  hlgw00: 'House Select Energy Independence & Global Warming',
  hlij00: 'House Select January 6th Attack',
  hlmh00: 'House Select Modernization of Congress',
  hlqj00: 'House Select January 6 Subcommittee',
  hlvc00: 'House Select Coronavirus Pandemic',
  hlzi00: 'House Select Benghazi',
  hlzs00: 'House Select Strategic Competition with the CCP',
  hotl00: 'Tom Lantos Human Rights Commission',
  htzt00: 'House Task Force on the Attempted Assassination of Donald J. Trump',
  jsec00: 'Joint Economic Committee',
  jcse00: 'Helsinki Commission',
  jcpk00: 'Congressional-Executive Commission on China',
  jstx00: 'Joint Committee on Taxation',
  jcov00: 'Congressional Oversight Commission',
  jsbp00: 'Joint Select Budget & Appropriations Process Reform',
  ssap00: 'Senate Appropriations',
  ssbk00: 'Senate Banking, Housing, & Urban Affairs',
  ssbu00: 'Senate Budget',
  sscm00: 'Senate Commerce, Science, & Transportation',
  sseg00: 'Senate Energy & Natural Resources',
  ssev00: 'Senate Environment & Public Works',
  ssfi00: 'Senate Finance',
  ssfr00: 'Senate Foreign Relations',
  ssga00: 'Senate Homeland Security & Governmental Affairs',
  sshr00: 'Senate Health, Education, Labor, & Pensions',
  ssju00: 'Senate Judiciary',
  sssb00: 'Senate Small Business & Entrepreneurship',
  ssva00: "Senate Veterans' Affairs",
  scnc00: 'Senate International Narcotics Control Caucus',
  slia00: 'Senate Indian Affairs',
  spag00: 'Senate Special Committee on Aging',
};

const subcommittees: Record<string, string> = {
  hsju01: 'Immigration Integrity, Security, & Enforcement',
  hsju02: 'Administrative Law & Governmental Relations',
  hsju03: 'Courts, Intellectual Property, AI, & the Internet',
  hsju04: 'Civil & Constitutional Rights',
  hsju05: 'Administrative State, Regulatory Reform, & Antitrust',
  hsju06: 'Crime',
  hsju07: 'Criminal Justice',
  hsju08: 'Crime & Federal Government Surveillance',
  hsju09: 'Commercial & Administrative Law',
  hsju10: 'Constitution & Limited Government',
  hsju11: 'Antitrust Task Force',
  hsju12: 'Over-Criminalization Task Force',
  hsju13: 'Oversight',
  hsif02: 'Communications & Technology',
  hsif03: 'Energy, Climate, & Grid Security',
  hsif14: 'Health',
  hsif16: 'Environment, Manufacturing, & Critical Materials',
  hsif17: 'Innovation, Data, & Commerce',
  hsif18: 'Oversight & Investigations',
  hsap01: 'Agriculture, Rural Development, & FDA',
  hsap02: 'Defense',
  hsap04: 'Interior, Environment, & Related Agencies',
  hsap06: 'Energy & Water Development',
  hsap07: 'Labor, Health & Human Services, & Education',
  hsap10: 'Transportation, Housing & Urban Development',
  hsap15: 'Homeland Security',
  hsap18: 'Military Construction & Veterans Affairs',
  hsap19: 'Commerce, Justice, Science, & Related Agencies',
  hsap20: 'State, Foreign Operations, & Related Programs',
  hsap23: 'Financial Services & General Government',
  hsap24: 'Legislative Branch',
  hsii06: 'Energy & Mineral Resources',
  hsii10: 'Federal Lands',
  hsii13: 'Water, Wildlife, & Fisheries',
  hsii15: 'Oversight & Investigations',
  hsii22: 'Indian & Insular Affairs',
  hsii24: 'Indian & Insular Affairs',
  hsgo02: 'National Security, the Border, & Foreign Affairs',
  hsgo05: 'Economic Growth, Energy Policy, & Regulatory Affairs',
  hsgo06: 'Government Operations & the Federal Workforce',
  hsgo12: 'Delivering on Government Efficiency',
  hsgo24: 'Government Operations',
  hsgo27: 'Health Care & Financial Services',
  hsgo28: 'Cybersecurity, Information Technology, & Government Innovation',
  hswm01: 'Social Security',
  hswm02: 'Health',
  hswm03: 'Human Resources / Work & Welfare',
  hswm04: 'Trade',
  hswm05: 'Tax',
  hswm06: 'Oversight',
};

const documentKindLabels: Record<string, string> = {
  'published-hearing': 'Published Hearing',
  'meeting-support': 'Meeting Support Document',
  'testimony': 'Witness Testimony',
  'witness-statement': 'Witness Statement',
  'testimony-disclosure': 'Truth in Testimony Disclosure',
  'witness-biography': 'Witness Biography',
  'committee-amendment': 'Committee Amendment',
  'bill-numbered': 'Numbered Bill',
  'committee-vote': 'Committee Recorded Vote',
  'committee-amendment-described': 'Committee Amendment (Described)',
  'witness-support': 'Witness Supporting Material',
  'member-statement': 'Member Statement',
  'amendment': 'Amendment',
  'opening-statement': 'Opening Statement',
  'statement': 'Statement',
  'witness-list': 'Witness List',
  'committee-transcript': 'Committee Transcript',
  'committee-memorandum': 'Committee Memorandum',
  'bill-untyped-numbered': 'Numbered Legislation',
  'published-report': 'Published Committee Report',
  'meeting-notice': 'Meeting Notice',
  'questions-for-record': 'Questions for the Record',
  'questions-for-record-response': 'Responses to Questions for the Record',
  'bill-untyped-draft': 'Discussion Draft Bill',
  'biography': 'Biography',
  'member-roster': 'Committee Roster',
  'transcript': 'Transcript',
  'legislative-text': 'Legislative Text',
  'bill-suspension-numbered': 'Suspension Bill',
  'nomination': 'Nomination',
  'committee-enbloc-numbered': 'En Bloc Amendment',
  'letter-of-support': 'Letter of Support',
  'questionnaire': 'Questionnaire',
  'bill-measure-list': 'List of Bills & Measures',
  'business-meeting': 'Business Meeting / Markup',
  'committee-report': 'Committee Report',
  'report': 'Report',
  'hearing-charter': 'Hearing Charter',
  'appropriation-described': 'Appropriations Material',
  'letter': 'Letter',
  'committee-print': 'Committee Print',
  'meeting-results': 'Markup / Meeting Results',
  'opening-remarks': 'Opening Remarks',
  'remarks': 'Remarks',
  'bill-unnumbered': 'Unnumbered Bill',
  'appropriation-routed': 'Appropriations Routing Table',
  'summary': 'Summary',
  'attachment': 'Attachment',
  'exhibit': 'Exhibit',
  'committee-document': 'Committee Document',
  'bill-named-draft': 'Named Draft Bill',
  'bill-titled-draft': 'Titled Draft Bill',
  'appendix': 'Appendix',
  'bill-house-amendment': 'House Amendment',
  'bill-preintroduced': 'Pre-Introduced Bill Draft',
  'committee-enbloc-described': 'En Bloc Amendment (Described)',
  'amendment-collection': 'Amendment Packet',
  'bill-numbered-described': 'Numbered Bill (Described)',
  'section-by-section': 'Section-by-Section Summary',
  'oversight-plan': 'Oversight Plan',
  'tally-sheet': 'Vote Tally Sheet',
  'bill-comparison': 'Comparative Print',
  'committee-resolution': 'Committee Resolution',
  'fact-sheet': 'Fact Sheet',
  'committee-report-unnumbered': 'Unnumbered Committee Report',
  'public-law': 'Public Law',
  'field-hearing': 'Field Hearing',
  'explanatory-statement': 'Explanatory Statement',
  'response': 'Response',
  'published-print': 'Published Committee Print',
  'slides': 'Presentation Slides',
  'chair-mark': "Chairman's Mark",
  'budget-views-and-estimates': 'Budget Views & Estimates',
  'revenue-estimate': 'Revenue / Cost Estimate',
  'interchamber-amendment': 'Interchamber Amendment',
  'exhibit-collection': 'Exhibit Packet',
  'managers-package': "Manager's Amendment Package",
  'treaty-document': 'Treaty Document',
  'conference-unnumbered': 'Conference Material',
  'amendment-list': 'Amendment List',
  'mark-description': "Description of the Chairman's Mark",
  'mark-modification': "Modification to the Chairman's Mark",
  'conference-legislation-part': 'Conference Report Part',
  'issue-brief': 'Issue Brief',
  'activity-report': 'Committee Activity Report',
  'committee-report-part': 'Committee Report Part',
  'conference-report': 'Conference Report',
  'exhibit-list': 'Exhibit List',
  'flyer': 'Flyer',
  'graphic': 'Graphic',
  'motion': 'Motion',
  'notice': 'Notice',
  'pamphlet': 'Pamphlet',
  'panel-discussion': 'Panel Discussion',
  'panelist-list': 'Panelist List',
  'participant-list': 'Participant List',
  'rules-memorandum': 'Rules Committee Memorandum',
  'brochure': 'Brochure',
};

const formatNames: Record<string, string> = {
  pdf: 'PDF',
  html: 'HTML',
  xml: 'XML',
  docx: 'DOCX',
  doc: 'DOC',
  zip: 'ZIP',
  json: 'JSON',
  txt: 'TXT',
  text: 'TXT',
  image: 'Image',
  other: 'Other',
};

const measurePrefixes: Record<string, string> = {
  hr: 'H.R.',
  s: 'S.',
  hres: 'H.Res.',
  sres: 'S.Res.',
  hjres: 'H.J.Res.',
  sjres: 'S.J.Res.',
  hconres: 'H.Con.Res.',
  sconres: 'S.Con.Res.',
};

const genericAnchorTitles = new Set([
  'zip', 'pdf', 'html', 'htm', 'xml', 'doc', 'docx', 'txt', 'text', 'json', 'csv',
  'xls', 'xlsx', 'ppt', 'pptx', 'mp3', 'mp4', 'click here', 'please click here',
  'here', 'link', 'document', 'file', 'download', 'download file', 'download pdf',
  'download testimony', 'download witness testimony',
  'download executive business meeting results', 'view', 'view pdf', 'view testimony',
  'open', 'read more', 'more', 'email', 'print', 'share', 'website', 'webpage',
  'untitled', 'attachment',
]);

export function ordinal(n: number): string {
  const rem10 = n % 10;
  const rem100 = n % 100;
  if (rem10 === 1 && rem100 !== 11) return `${n}st`;
  if (rem10 === 2 && rem100 !== 12) return `${n}nd`;
  if (rem10 === 3 && rem100 !== 13) return `${n}rd`;
  return `${n}th`;
}

export function congressLabel(congress: number | string | null | undefined): string | null {
  const num = Number(congress);
  if (!Number.isInteger(num) || num < 1 || num > 200) return null;
  return `${ordinal(num)} Congress`;
}

export function congressOptionLabel(congress: number | string): string {
  const num = Number(congress);
  if (!Number.isInteger(num) || num < 1) return String(congress);
  const meta = (congressMetadata as Record<string, { start: string; end: string }>)[String(num)];
  const startYear = meta ? meta.start.slice(0, 4) : String(1789 + (num - 1) * 2);
  const endYear = meta ? meta.end.slice(0, 4) : String(1789 + num * 2);
  return `${ordinal(num)} Congress (${startYear}–${endYear})`;
}

export function parentCommitteeCode(code: string): string {
  const clean = String(code ?? '').trim().toLowerCase();
  if (clean.length === 6 && /^[a-z]{4}\d{2}$/.test(clean)) {
    const parent = `${clean.slice(0, 4)}00`;
    if (standingCommittees[parent]) return parent;
  }
  return clean;
}

export function committeeShortLabel(code: string): string {
  const clean = String(code ?? '').trim().toLowerCase();
  if (!clean) return '';
  if (standingCommittees[clean]) return standingCommittees[clean];
  const parent = parentCommitteeCode(clean);
  if (standingCommittees[parent]) return standingCommittees[parent];
  return clean.toUpperCase();
}

export function committeeLabel(code: string): string {
  const clean = String(code ?? '').trim().toLowerCase();
  if (!clean) return '';
  if (standingCommittees[clean]) return standingCommittees[clean];
  const parent = parentCommitteeCode(clean);
  const parentName = standingCommittees[parent];
  const subName = subcommittees[clean];
  if (parentName && subName) return `${parentName} — ${subName}`;
  if (parentName && clean !== parent) return `${parentName} (${clean.slice(4)})`;
  return clean.toUpperCase();
}

export function expandCommitteeKeys(selected: string, facetItems: Array<{ value: string; count: number }>): string[] {
  const clean = String(selected ?? '').trim().toLowerCase();
  if (!clean) return [];
  if (clean.endsWith('00') && standingCommittees[clean]) {
    const prefix = clean.slice(0, 4);
    const matching = facetItems
      .map(item => String(item.value).toLowerCase())
      .filter(code => code === clean || (code.startsWith(prefix) && parentCommitteeCode(code) === clean));
    return matching.length ? matching : [clean];
  }
  return [clean];
}

export function buildCommitteeGroups(facetItems: Array<{ value: string; count: number }>) {
  const parentTotals = new Map<string, number>();
  const subItems: Array<{ value: string; label: string; count: number }> = [];
  for (const item of facetItems) {
    const code = String(item.value).toLowerCase();
    const count = Number(item.count) || 0;
    const parent = parentCommitteeCode(code);
    parentTotals.set(parent, (parentTotals.get(parent) ?? 0) + count);
    if (code !== parent) {
      subItems.push({ value: code, label: committeeLabel(code), count });
    }
  }
  const primary = [...parentTotals.entries()]
    .map(([value, count]) => ({ value, label: committeeShortLabel(value), count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  subItems.sort((a, b) => a.label.localeCompare(b.label));
  return { primary, subItems };
}

export function documentKindLabel(kind: string): string {
  const clean = String(kind ?? '').trim().toLowerCase();
  if (!clean) return '';
  if (documentKindLabels[clean]) return documentKindLabels[clean];
  return clean
    .split('-')
    .filter(Boolean)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function formatOptionLabel(format: string): string {
  const clean = String(format ?? '').trim().toLowerCase();
  return formatNames[clean] ?? clean.toUpperCase();
}

export function effectiveFormat(document: any, detail?: any): string {
  const filename = String(document?.filename ?? '').trim();
  const extMatch = /\.([a-z0-9]{2,5})$/i.exec(filename);
  const ext = extMatch ? extMatch[1].toLowerCase() : '';
  const knownExt: Record<string, string> = {
    pdf: 'pdf', zip: 'zip', html: 'html', htm: 'html', xml: 'xml',
    docx: 'docx', doc: 'doc', txt: 'txt', text: 'txt', json: 'json', csv: 'csv',
  };
  const docFormat = String(document?.format ?? '').trim().toLowerCase();
  if (ext && knownExt[ext] && (!docFormat || docFormat === 'other' || docFormat === 'json' || docFormat === 'text')) {
    return knownExt[ext];
  }
  if (docFormat && docFormat !== 'other') return docFormat === 'text' ? 'txt' : docFormat;
  if (ext && knownExt[ext]) return knownExt[ext];
  const media = String(detail?.saved_media_type ?? '').toLowerCase();
  if (media.includes('pdf')) return 'pdf';
  if (media.includes('zip')) return 'zip';
  if (media.includes('html')) return 'html';
  if (media.includes('xml')) return 'xml';
  if (media.includes('word') || media.includes('officedocument')) return 'docx';
  if (media.includes('json')) return 'json';
  return docFormat || 'file';
}

export function formatMeasure(key: string): string {
  const match = /^(?:(\d+)-)?([a-z]+)-(\d+)$/i.exec(String(key ?? '').trim());
  if (!match) return String(key ?? '');
  const prefix = measurePrefixes[match[2].toLowerCase()] ?? match[2].toUpperCase();
  return `${prefix} ${match[3]}`;
}

export function formatBytes(value: any): string | null {
  if (value == null) return null;
  const num = Number(value);
  if (!Number.isFinite(num) || num <= 0) return null;
  if (num < 1024) return `${Math.round(num)} B`;
  if (num < 1024 * 1024) return `${(num / 1024).toFixed(num < 10 * 1024 ? 1 : 0)} KB`;
  return `${(num / (1024 * 1024)).toFixed(1)} MB`;
}

export function cleanIdentityNote(note: any): string | null {
  const text = String(note ?? '').trim();
  if (!text) return null;
  if (/^Reconciled from pinned accepted mappings\s+[0-9a-f]{16,}/i.test(text)) return null;
  return text;
}

export function isGenericTitle(title: any): boolean {
  const clean = String(title ?? '').trim().replace(/\s+/g, ' ');
  if (!clean) return true;
  const lower = clean.toLowerCase().replace(/[.!:]+$/, '');
  if (genericAnchorTitles.has(lower)) return true;
  if (/^(?:please\s+)?click\s+here\b/i.test(lower)) return true;
  if (/^(?:download|view|open)\s+(?:witness\s+)?(?:testimony|statement|document|pdf|file|results)\b/i.test(lower)) return true;
  return false;
}

export function cleanDisplayFilename(filename: any): string {
  const raw = String(filename ?? '').trim();
  if (!raw || !/[0-9a-z]/i.test(raw)) return '';
  return raw.replace(/^[0-9a-f]{64}\./i, '');
}

function urlFallbackLabel(url: any): string {
  const raw = String(url ?? '').trim();
  if (!raw) return '';
  try {
    const parsed = new URL(raw);
    const segments = parsed.pathname.split('/').filter(Boolean);
    const last = segments.at(-1) ? decodeURIComponent(segments.at(-1)!) : '';
    if (last && /\.[a-z0-9]{2,5}$/i.test(last)) return cleanDisplayFilename(last) || last;
    const host = parsed.hostname.replace(/^www\./i, '');
    const pathPart = segments.slice(0, 3).join('/');
    return pathPart ? `${host}/${pathPart}` : host;
  } catch {
    return '';
  }
}

export function presentDocument(document: any, detail?: any, sources?: any[], recoveries?: any[]) {
  const rawTitle = String(document?.title ?? '').trim();
  const cleanFile = cleanDisplayFilename(document?.filename);
  const validTitle = !isGenericTitle(rawTitle) ? rawTitle : '';
  const sourceUrl = document?.source_url || sources?.[0]?.url || recoveries?.[0]?.recovered_url || '';
  const urlLabel = (!validTitle && !cleanFile) ? urlFallbackLabel(sourceUrl) : '';
  const kindLabels = Array.isArray(document?.document_kind)
    ? document.document_kind.map(documentKindLabel).filter(Boolean)
    : [];
  const committees = Array.isArray(document?.committee_keys)
    ? [...new Set(document.committee_keys.map(committeeShortLabel).filter(Boolean))]
    : [];
  const congress = congressLabel(document?.congress);
  const measures = Array.isArray(document?.measure_keys)
    ? document.measure_keys.slice(0, 3).map(formatMeasure).filter(Boolean)
    : [];

  const fmt = effectiveFormat(document, detail).toUpperCase();
  const fallbackKind = kindLabels[0]
    || (document?.saved_kind === 'recovery' ? `Recovered ${fmt} document` : `Archived ${fmt} document`);
  const fallbackSuffix = committees[0]
    ? ` — ${committees[0]}`
    : document?.list_row != null
      ? ` (#${Number(document.list_row) + 1})`
      : '';

  const title = validTitle || cleanFile || urlLabel || `${fallbackKind}${fallbackSuffix}`;
  const subtitle = cleanFile && cleanFile !== title ? cleanFile : '';
  const contextParts = [
    congress,
    ...committees.slice(0, 2),
    ...kindLabels.slice(0, 2),
    ...measures.slice(0, 2),
  ].filter(Boolean) as string[];

  return {
    title,
    subtitle,
    contextParts,
    format: fmt,
    congress,
    committees: Array.isArray(document?.committee_keys)
      ? [...new Set(document.committee_keys.map(committeeLabel).filter(Boolean))]
      : [],
    kinds: kindLabels,
    measures: Array.isArray(document?.measure_keys)
      ? document.measure_keys.map((key: string) => ({ key, label: formatMeasure(key) }))
      : [],
  };
}
