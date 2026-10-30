import { type ReactNode } from 'react';
import { ExternalIcon, ForwardIcon } from './icons';
import { categoryNote, collapseRepeatedFacts, committeeHierarchyNote, committeeLevelLabel, committeeTypeLabel, congressName, disagreementSummary, distinctRecordedFacts, documentSourceLabel, factLabel, issueStatusLabel, severityLabel, fileLinkName, filePartNote, listedDocumentType, listTitle, meetingStatusNote, orderRecordedFiles, parentCommitteeId, plainRecordedNote, providerLabel, recordedTitlePreview, recordedWhen, recordingEmbedUrl, recordingIdentity, savedCopyHref, savedOriginalUrl, scheduleNote, sourceFacts, sourceLinks, sourcePageUrl, sourceTypeNote, type SourceLink } from '../browse/record-presentation.ts';
import type { ExplorerRecordRef, LoadedRecord } from '../reader/data-source.ts';

export type DetailRecord = LoadedRecord;
type Fields = Record<string, unknown>;
export function fields(value: unknown): Fields {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Fields : {};
}
export function words(value: unknown): string {
  if (value === 'business') return 'Business meeting';
  return typeof value === 'string' ? value.replaceAll('_', ' ') : '';
}
export function enumLabel(value: unknown): string {
  const text = words(value);
  return text.charAt(0).toUpperCase() + text.slice(1);
}
function readableLabel(label: string): string {
  return label === label.toLowerCase() ? label.charAt(0).toUpperCase() + label.slice(1) : label;
}
export function documentType(record: unknown): string {
  const row = fields(record);
  return typeof row.document_type === 'string' ? row.document_type : '';
}
export function recordTitle(value: unknown): string {
  const row = fields(value);
  if (row.kind === 'source_record') {
    if (typeof row.title === 'string' && row.title.trim()) return row.title.trim();
    const recorded = fields(row.payload).title;
    if (typeof recorded === 'string' && recorded.trim()) return recorded.trim();
    const filename = typeof row.url === 'string' ? decodeURIComponent(row.url.split('/').pop()?.split('?')[0] || '') : '';
    if (filename.includes('.')) return filename;
    return String(row.provider || 'Original source');
  }
  if (row.kind === 'material') {
    const listed = listTitle(row);
    if (listed) return listed;
  }
  const title = row.title || row.summary || fields(row.name).display || row.name;
  if (title && title !== '(Untitled source record)') return row.kind === 'data_issue' ? plainRecordedNote(String(title)) : String(title);
  const label = words(row.category && row.category !== 'unknown' ? row.category : row.type || row.kind);
  return label ? label[0].toUpperCase() + label.slice(1) : 'Untitled record';
}
export function publicUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}
const LABELS: Record<string, string> = { meeting: 'Meeting', committee_term: 'Committee', material: 'Document or recording', appearance: 'Witness', data_issue: 'Known issue', source_record: 'Original source' };

function fileTypeNote(value: string): string {
  const text = value.toLowerCase();
  if (!text) return '';
  if (text.includes('pdf')) return 'PDF';
  if (text.includes('html')) return 'Web page';
  if (text.includes('word') || text.includes('msword')) return 'Word document';
  if (text.includes('xml')) return 'XML file';
  return value.includes('/') ? '' : value;
}

function kindLabel(record: DetailRecord): string {
  const row = fields(record);
  if (record.kind === 'material') {
    const typed = listedDocumentType(documentType(record));
    if (typed) return typed;
    if (row.type === 'recording') return 'Recording';
    if (row.type === 'text') return 'Captions or transcript';
    if (row.type === 'document') return 'Document';
  }
  if (record.kind === 'meeting' && row.type && row.type !== 'unknown') return enumLabel(row.type);
  if (record.kind === 'data_issue' && row.category && row.category !== 'unknown') return enumLabel(row.category);
  return LABELS[record.kind] || words(record.kind);
}

export function recordFiles(record: unknown): Fields[] {
  const row = fields(record);
  if (row.type === 'recording') {
    const url = publicUrl(row.recording_url);
    if (!url) return [];
    const files = Array.isArray(row.files) ? row.files.map(fields) : [];
    const identity = recordingIdentity(url);
    const match = files.find(file => publicUrl(file.url) === url) || files.find(file => identity && recordingIdentity(String(file.url || '')) === identity) || {};
    return [{ ...match, url, role: 'player' }];
  }
  const files = row.files;
  if (!Array.isArray(files)) return [];
  const seen = new Set<string>();
  const listed = files.map(fields).filter(file => {
    const url = publicUrl(file.url);
    if (!url || seen.has(url)) return false;
    seen.add(url); return true;
  });
  return orderRecordedFiles(listed);
}

export function FileLinks({ record }: { record: unknown }) {
  const files = recordFiles(record);
  if (!files.length) return null;
  return <div className="explorer-file-links">{files.map(file => {
    const saved = savedCopyHref(file, import.meta.env.PUBLIC_ARCHIVE_RAW_BASE_URL);
    const label = fileLinkName(file);
    const savedLabel = file.label && file.label !== 'unknown' ? ` (${words(file.label)})` : '';
    const meta = [file.version && file.version !== 'unknown' ? words(file.version) : '', typeof file.published_at === 'string' ? `Published ${file.published_at.slice(0, 10)}` : '', fileTypeNote(typeof file.media_type === 'string' ? file.media_type : '')].filter(Boolean).join(' · ');
    return <span key={String(file.url)}>
      <a href={publicUrl(file.url)} target="_blank" rel="noreferrer">{label} <ExternalIcon /></a>
      {saved ? <> <a href={saved} target="_blank" rel="noreferrer">Open saved copy{savedLabel} <ExternalIcon /></a></> : null}
      {meta ? <span className="explorer-row-meta">{meta}</span> : null}
    </span>;
  })}</div>;
}
export function RecordingPlayer({ record }: { record: unknown }) {
  const url = recordingEmbedUrl(fields(record));
  if (!url) return null;
  return <iframe className="explorer-recording-player" src={url} title={`Recording: ${recordTitle(record)}`}
    loading="lazy" allow="encrypted-media; picture-in-picture; fullscreen" allowFullScreen
    referrerPolicy="strict-origin-when-cross-origin" />;
}

export function SourceLinkGroups({ links }: { links: readonly SourceLink[] }) {
  const groups: { name: string; links: SourceLink[] }[] = [];
  for (const link of links) {
    const group = groups.find(item => item.name === link.group);
    if (group) group.links.push(link);
    else groups.push({ name: link.group, links: [link] });
  }
  if (!groups.length) return null;
  return <div className="explorer-link-groups">{groups.map(group => <section className="explorer-link-group" key={group.name}><h5>{group.name}</h5><ul className="explorer-related-list">{group.links.map((link, linkIndex) => {
    const href = publicUrl(link.href);
    return <li key={`${link.href}/${linkIndex}`}>{href ? <a href={href} target="_blank" rel="noreferrer">{link.label} <ExternalIcon /></a> : <span>{link.label}</span>}</li>;
  })}</ul></section>)}</div>;
}

const measureFacts = new Set(['Related bill', 'Related resolution', 'Related treaty', 'Related nomination']);
const amendmentFields = new Set(['Amendment number', 'Amendment description', 'Sponsor', 'Sponsor Bioguide ID', 'Regarding', 'En bloc group']);

interface AmendmentGroup {
  number: string;
  description: string;
  sponsor: string;
  bioguide: string;
  regarding: string;
  enBloc: string;
}

/** Keep a repeated amendment's number, sponsor, and description together. One amendment stays in the fact sheet. */
function groupAmendments(facts: [unknown, unknown][]): { others: [unknown, unknown][]; groups: AmendmentGroup[] } {
  const groups: AmendmentGroup[] = [];
  let current: AmendmentGroup | null = null;
  const others: [unknown, unknown][] = [];
  for (const fact of facts) {
    const label = String(fact[0]);
    const value = String(fact[1]).trim();
    if (!amendmentFields.has(label) || !value) { others.push(fact); continue; }
    if (label === 'Amendment number' || !current) {
      current = { number: '', description: '', sponsor: '', bioguide: '', regarding: '', enBloc: '' };
      groups.push(current);
    }
    if (label === 'Amendment number') current.number = value;
    else if (label === 'Amendment description') current.description = value;
    else if (label === 'Sponsor') current.sponsor = value;
    else if (label === 'Sponsor Bioguide ID') current.bioguide = value;
    else if (label === 'Regarding') current.regarding = current.regarding ? `${current.regarding}\n${value}` : value;
    else current.enBloc = value;
  }
  if (groups.filter(group => group.number).length < 2) return { others: facts, groups: [] };
  const numeric = groups.every(group => /^\d+$/.test(group.number));
  if (numeric) groups.sort((a, b) => Number(a.number) - Number(b.number));
  return { others, groups };
}
const numberedFact = /^(Vote|Amendment) (\d+)$/i;

/** Pull numbered vote or amendment facts out, in number order. */
function extractNumberedFacts(facts: [unknown, unknown][], kind: string): { others: [unknown, unknown][]; preview: [unknown, unknown][]; rest: [unknown, unknown][] } {
  const pattern = new RegExp(`^${kind} \\d+$`, 'i');
  const numbered = facts.filter(fact => pattern.test(String(fact[0]))).sort((a, b) => Number(numberedFact.exec(String(a[0]))?.[2]) - Number(numberedFact.exec(String(b[0]))?.[2]));
  const others = facts.filter(fact => !pattern.test(String(fact[0])));
  if (numbered.length <= 6) return { others, preview: numbered, rest: [] };
  return { others, preview: numbered.slice(0, 4), rest: numbered.slice(4) };
}

function FactLines({ label, value }: { label: string; value: string }) {
  const prose = label === 'Description' || label === 'Match note' || label === 'Explanation' || label === 'Note';
  if (!prose) return <>{value.split('\n').map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</>;
  const note = recordedTitlePreview(value);
  const name = label.toLowerCase();
  return <>
    <span>{note.preview}</span>
    {note.rest.length ? <details><summary>Rest of the {name}<span className="explorer-field-reason">The rest of the recorded {name}.</span></summary>{note.rest.map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</details> : null}
  </>;
}

function FactRow({ fact }: { fact: [unknown, unknown] }) {
  const label = String(fact[0]);
  const value = String(fact[1]);
  const inline = measureFacts.has(label) && value.includes('\n');
  return <div><dt>{readableLabel(label)}</dt><dd className={inline ? 'explorer-inline-values' : undefined}>{label === 'Official website or archive' && publicUrl(value)
    ? <a href={publicUrl(value)} target="_blank" rel="noreferrer">Visit website or archive <ExternalIcon /></a>
    : label === 'How to read it' ? severityLabel(value)
    : label === 'Status' && value === 'open' ? issueStatusLabel(value)
    : ['Type', 'Status', 'At the source', 'Recorded here', 'Meeting status', 'Category', 'Chamber', 'Participation', 'medium', 'coverage', 'production', 'Access'].includes(label) ? enumLabel(value) : <FactLines label={label} value={value} />}</dd></div>;
}

const measureNoun: Record<string, string> = {
  'Related bill': 'bill',
  'Related resolution': 'resolution',
  'Related treaty': 'treaty',
  'Related nomination': 'nomination',
};

/** Keep a short list of related measures visible; the rest open on request. */
function extractMeasureFacts(facts: [unknown, unknown][]): { others: [unknown, unknown][]; rests: { label: string; values: string[]; noun: string }[] } {
  const others: [unknown, unknown][] = [];
  const rests: { label: string; values: string[]; noun: string }[] = [];
  for (const fact of facts) {
    const label = String(fact[0]);
    const lines = String(fact[1]).split('\n').map(line => line.trim()).filter(Boolean);
    if (!measureFacts.has(label) || lines.length <= 6) {
      others.push(fact);
      continue;
    }
    others.push([label, lines.slice(0, 4).join('\n')]);
    rests.push({ label, values: lines.slice(4), noun: measureNoun[label] || 'item' });
  }
  return { others, rests };
}

function AmendmentFact({ group }: { group: AmendmentGroup }) {
  return <div><dt>Amendment {group.number}</dt><dd>
    {group.sponsor ? <span>{group.sponsor}</span> : null}
    {group.bioguide ? <span className="explorer-row-meta">Member number {group.bioguide}</span> : null}
    {group.enBloc ? <span className="explorer-row-meta">En bloc group {group.enBloc}</span> : null}
    {group.regarding ? <FactLines label="Note" value={group.regarding.startsWith('Regarding') ? group.regarding : `Regarding ${group.regarding}`} /> : null}
    {group.description ? <FactLines label="Description" value={group.description} /> : null}
  </dd></div>;
}

function AmendmentList({ groups }: { groups: AmendmentGroup[] }) {
  const preview = groups.length > 6 ? groups.slice(0, 4) : groups;
  const rest = groups.length > 6 ? groups.slice(4) : [];
  return <>
    <dl className="explorer-facts">{preview.map((group, index) => <AmendmentFact key={`${group.number}-${index}`} group={group} />)}</dl>
    {rest.length ? <details className="explorer-detail-section"><summary>{rest.length} more recorded amendments<span className="explorer-field-reason">The remaining amendments recorded on this document, in amendment number order.</span></summary><dl className="explorer-facts">{rest.map((group, index) => <AmendmentFact key={`${group.number}-${index}`} group={group} />)}</dl></details> : null}
  </>;
}

function NumberedFactRest({ noun, facts, reason }: { noun: string; facts: [unknown, unknown][]; reason: string }) {
  const count = facts.length;
  return <details className="explorer-detail-section"><summary>{count} more recorded {count === 1 ? noun : `${noun}s`}<span className="explorer-field-reason">{reason}</span></summary><dl className="explorer-facts">{facts.map((fact, index) => <FactRow key={index} fact={fact} />)}</dl></details>;
}

const whenLabels = new Set(['Date', 'Scheduled time', 'Meeting schedule', 'Held', 'Published', 'Retrieved', 'Active from', 'Active through', 'File dated', 'Checked', 'Added at the source', 'Last changed', 'Meeting file updated', 'Detected']);
const whereLabels = new Set(['Place', 'Building', 'Room', 'City', 'Region', 'Location', 'Committees', 'Committee', 'Subcommittee', 'Chamber', 'Committee code', 'Official website or archive', 'Committee type', 'Committee level', 'Source committee type']);
const aboutLabels = new Set(['Type', 'Document type', 'Status', 'At the source', 'Recorded here', 'Meeting status', 'Access', 'Congress', 'Category', 'Participation', 'Position', 'Organization', 'Roles', 'Source', 'How to read it', 'Which copy', 'Filed as', 'Volume part', 'Open issues', 'Recorded difference', 'Why this version', 'What was decided', 'Compared field']);

function factBucket(label: string): 'when' | 'where' | 'about' | 'details' {
  const readable = readableLabel(label);
  if (whenLabels.has(readable)) return 'when';
  if (whereLabels.has(readable)) return 'where';
  if (aboutLabels.has(readable)) return 'about';
  return 'details';
}

function FactGroups({ facts, eyebrow }: { facts: [unknown, unknown][]; eyebrow: string }) {
  const readable = (label: unknown) => readableLabel(String(label));
  const shown = facts.filter(([label, value]) => readable(label) !== 'Congress' && !(['Type', 'Document type'].includes(readable(label)) && enumLabel(value) === eyebrow));
  const buckets = {
    when: shown.filter(([label]) => factBucket(String(label)) === 'when'),
    where: shown.filter(([label]) => factBucket(String(label)) === 'where'),
    about: shown.filter(([label]) => factBucket(String(label)) === 'about'),
    details: shown.filter(([label]) => factBucket(String(label)) === 'details'),
  };
  const statusLabels = new Set(['Status', 'At the source', 'Recorded here', 'Meeting status', 'Access']);
  const whoLabels = new Set(['Position', 'Organization', 'Participation', 'Roles']);
  const aboutTitle = buckets.about.length && buckets.about.every(([label]) => statusLabels.has(readable(label))) ? 'Status'
    : buckets.about.length && buckets.about.every(([label]) => whoLabels.has(readable(label))) ? 'Who'
    : 'What it is';
  const named = ([['When', buckets.when, 'When'], [aboutTitle, buckets.about, 'about'], ['Where', buckets.where, 'Where']] as const).filter(([, rows]) => rows.length);
  if (!named.length) return buckets.details.length ? <dl className="explorer-facts">{buckets.details.map((fact, index) => <FactRow key={index} fact={fact} />)}</dl> : null;
  return <>
    {named.map(([title, rows, key]) => <section className="explorer-fact-group" key={key}>{title ? <h3>{title}</h3> : null}<dl className="explorer-facts">{rows.map((fact, index) => <FactRow key={index} fact={fact} />)}</dl></section>)}
    {buckets.details.length ? <section className="explorer-fact-group"><h3>Details</h3><dl className="explorer-facts">{buckets.details.map((fact, index) => <FactRow key={index} fact={fact} />)}</dl></section> : null}
  </>;
}

/** A short fact sheet; source evidence is an optional disclosure. */
export function RecordDetail({ record, onSelect, sourceEvidence, committeeLabels, affectedAction, meetingAction }: { record: DetailRecord; onSelect: (ref: ExplorerRecordRef) => void; sourceEvidence?: ReactNode; committeeLabels?: Readonly<Record<string, string>>; affectedAction?: ReactNode; meetingAction?: ReactNode }) {
  const row = fields(record);
  const when = recordedWhen(row);
  const committees = (Array.isArray(row.committee_ids) ? row.committee_ids : []).map(id => committeeLabels?.[String(id)]).filter((name): name is string => Boolean(name));
  const kind = kindLabel(record);
  const roleLabels = (Array.isArray(row.roles) ? row.roles.map(role => enumLabel(role)) : []).filter(role => role.toLowerCase() !== kind.toLowerCase());
  const date = typeof row.date === 'string' ? row.date.slice(0, 10) : '';
  const facts = [
    ['Date', date || null], ['Scheduled time', date && when.time ? when.time : null], ['Meeting schedule', scheduleNote(row).replace(/^Scheduled /, '') || null], ['Congress', congressName(row.congress) || null], ['Chamber', row.chamber],
    ['Committees', record.kind === 'committee_term' ? null : committees.length ? committees.join(' · ') : null],
    ['Open issues', typeof row.issue_count === 'number' && row.issue_count > 0 ? row.issue_count : null],
    ['Access', row.access],
    ['Committee type', row.kind === 'committee_term' ? committeeTypeLabel(row) : null],
    ['Source committee type', (() => {
      const sourceType = String(row.source_committee_type || '');
      if (!sourceType || committees.some(name => name.toLowerCase().includes(sourceType.toLowerCase()))) return null;
      return sourceType.toLowerCase().replaceAll(' ', '_') !== row.committee_type || row.committee_type === 'subcommittee' ? sourceType : null;
    })()],
    ['Committee level', (() => { const level = committeeLevelLabel(row); return level && !committees.some(name => name.toLowerCase().includes(level.toLowerCase())) ? level : null; })()],
    [documentType(record) ? 'Document type' : 'Type', row.kind === 'committee_term' ? null : listedDocumentType(documentType(record)) || row.type || row.meeting_type], ['Status', record.kind === 'meeting' && ['past', 'upcoming', 'today', 'scheduled'].includes(String(row.status)) ? null : row.status], ['Category', row.kind === 'material' ? categoryNote(row) || null : row.category],
    ['Filed as', Array.isArray(row.source_document_groups) && row.source_document_groups.length ? documentSourceLabel(row) : null],
    ['Volume part', filePartNote(row) || null],
    ['Position', row.position], ['Organization', row.organization], ['Participation', row.participation],
    ['Roles', roleLabels.length ? roleLabels.join(' · ') : null],
    ['Meeting status', meetingStatusNote(row) ? row.meeting_status : null],
    ['How to read it', row.severity],
    ['Which copy', row.selection === 'retained_history' ? 'Saved in an earlier copy. Not in the latest copy.' : null],
    ['Source', providerLabel(typeof row.provider === 'string' ? row.provider : '') || null], ['Retrieved', row.retrieved_at],
    ['Active from', fields(row.active).start], ['Active through', fields(row.active).end],
    ['Official website or archive', row.website],
    ...distinctRecordedFacts(Array.isArray(row.facts) ? row.facts as { label?: string | null; value?: string | null }[] : []).filter(([label, value]) => label !== 'Hierarchy definition' && !(label === 'Committee hierarchy' && !committeeHierarchyNote(value)) && !(label === 'medium' && value === 'video' && row.type === 'recording') && !(label === 'Source type' && !sourceTypeNote(row))),
  ].filter(([label, value]) => value !== null && value !== undefined && value !== '' && (value !== 'unknown' || label === 'Meeting status'));
  if (record.kind === 'source_record') {
    const seen = new Set(facts.map(([label]) => String(label).toLowerCase()));
    for (const [label, value] of sourceFacts(record)) if (!seen.has(label.toLowerCase())) facts.push([label, value]);
  }
  const shownFacts: [unknown, unknown][] = [];
  for (let index = 0; index < facts.length; index++) {
    const [label, value] = facts[index];
    if (String(label).toLowerCase() !== 'selected value') { shownFacts.push([label, value]); continue; }
    const alternatives: string[] = [];
    let next = index + 1;
    while (next < facts.length && /^alternative \d+$/i.test(String(facts[next][0]))) { alternatives.push(String(facts[next][1])); next++; }
    const summary = disagreementSummary(String(value), alternatives);
    if (!summary) { shownFacts.push([label, value]); continue; }
    if (String(shownFacts.at(-1)?.[0]) === 'Compared field') shownFacts.pop();
    shownFacts.push(['Recorded difference', summary.join('\n')]);
    index = next - 1;
  }
  const factNames = shownFacts.map(([label]) => String(label));
  for (let index = 0; index < shownFacts.length; index++) shownFacts[index] = [factLabel(String(shownFacts[index][0]), factNames), shownFacts[index][1]];
  const amendmentGroups = groupAmendments(shownFacts);
  const collapsedFacts = collapseRepeatedFacts(amendmentGroups.others);
  const voteFacts = extractNumberedFacts(collapsedFacts, 'Vote');
  const amendmentFacts = extractNumberedFacts(voteFacts.others, 'Amendment');
  const measureFactsSplit = extractMeasureFacts(amendmentFacts.others);
  const sheetFacts = measureFactsSplit.others;
  const files = Array.isArray(row.files) ? row.files : [];
  const explanation = row.explanation || fields(row.provenance).explanation;
  const sourceUrl = publicUrl(sourcePageUrl(row.url));
  const savedUrl = record.kind === 'source_record' ? savedOriginalUrl(record) : undefined;
  const parentId = record.kind === 'committee_term' ? parentCommitteeId(row) : '';
  const parentName = parentId ? committeeLabels?.[parentId] || '' : '';
  const affected = record.kind !== 'data_issue' ? null
    : ['meeting', 'material', 'appearance', 'committee_term', 'source_record'].includes(String(row.subject_kind))
      ? {kind: String(row.subject_kind), id: String(row.subject_id)}
      : row.meeting_id ? {kind: 'meeting', id: String(row.meeting_id)} : null;
  const congressFact = sheetFacts.find(([label]) => readableLabel(String(label)) === 'Congress');
  const eyebrow = congressFact ? `${kind} · ${congressFact[1]}` : kind;
  return <>
    <h2 id="explorer-detail-title">{recordTitle(record)}</h2>
    <p className="explorer-record-kind">{eyebrow}</p>
    <RecordingPlayer record={record} />
    <FileLinks record={record} />
    {sourceUrl ? <p className="explorer-actions"><a href={sourceUrl} target="_blank" rel="noreferrer">Open original source <ExternalIcon /></a></p> : null}
    {savedUrl ? <p className="explorer-actions"><a href={savedUrl} target="_blank" rel="noreferrer">Open saved original <ExternalIcon /></a></p> : null}
    {sheetFacts.length ? <FactGroups facts={sheetFacts} eyebrow={kind} /> : null}
    {measureFactsSplit.rests.map(rest => <details className="explorer-detail-section" key={rest.label}><summary>{rest.values.length} more related {rest.values.length === 1 ? rest.noun : `${rest.noun}s`}<span className="explorer-field-reason">The remaining {rest.noun}s recorded for this meeting.</span></summary><dl className="explorer-facts"><div><dt>{readableLabel(rest.label)}</dt><dd className="explorer-inline-values">{rest.values.map(value => <span key={value}>{value}</span>)}</dd></div></dl></details>)}
    {row.committee_code ? <details><summary>Committee code<span className="explorer-field-reason">A short code recorded for this committee. You do not need it to browse.</span></summary><p className="explorer-note">{String(row.committee_code)}</p></details> : null}
    {amendmentGroups.groups.length ? <AmendmentList groups={amendmentGroups.groups} /> : null}
    {voteFacts.preview.length ? <dl className="explorer-facts">{voteFacts.preview.map((fact, index) => <FactRow key={index} fact={fact} />)}</dl> : null}
    {voteFacts.rest.length ? <NumberedFactRest noun="vote" facts={voteFacts.rest} reason="The remaining roll-call and voice-vote results, in vote number order." /> : null}
    {amendmentFacts.preview.length ? <dl className="explorer-facts">{amendmentFacts.preview.map((fact, index) => <FactRow key={index} fact={fact} />)}</dl> : null}
    {amendmentFacts.rest.length ? <NumberedFactRest noun="amendment" facts={amendmentFacts.rest} reason="The remaining amendment outcomes, in amendment number order." /> : null}
    {record.kind === 'source_record' ? <SourceLinkGroups links={sourceLinks(record).links} /> : null}
    {explanation ? <p className="explorer-note">{plainRecordedNote(String(explanation))}</p> : null}
    {parentId ? <p><button className="explorer-text-button" aria-label={parentName ? `Open the parent committee ${parentName}` : 'Open the parent committee recorded for this subcommittee'} onClick={() => onSelect({kind: 'committee_term', id: parentId})}>{parentName ? `Subcommittee of ${parentName}` : 'Parent committee'} <ForwardIcon /></button></p> : null}
    {record.kind === 'material' && !files.length ? <p className="explorer-note">{row.type === 'recording' ? 'No recording is available in the collected sources.' : 'No file link in the collected sources.'}</p> : null}
    {meetingAction !== undefined ? meetingAction : row.meeting_id && !['meeting', 'material', 'data_issue'].includes(record.kind) ? <p><button className="explorer-text-button" aria-label="Open the meeting this record belongs to" onClick={() => onSelect({ kind: 'meeting', id: String(row.meeting_id) })}>Meeting <ForwardIcon /></button></p> : null}
    {affectedAction !== undefined ? affectedAction : affected ? <p><button className="explorer-text-button" aria-label="Open the record this issue describes" onClick={() => onSelect(affected)}>Affected record <ForwardIcon /></button></p> : null}
    {sourceEvidence}
  </>;
}
