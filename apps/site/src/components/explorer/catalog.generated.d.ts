/** Generated from committee_meeting.Catalog. Do not edit. Run npm run generate:explorer-types. */

export type SchemaVersion = '0.1.0-draft.2';
export type Scope = 'complete';
export type Kind = 'source_record';
export type Id = string;
export type Provider = string;
export type Scheme = string;
export type Value = string;
export type Scope1 = string | null;
export type InputSnapshotId = string | null;
export type Url = string | null;
export type RetrievedAt = string | null;
export type ImportedAt = string | null;
export type Date = string;
export type Time = string | null;
export type Timezone = string | null;
export type Precision = 'day' | 'minute' | 'second';
export type Approximate = boolean;
export type Original = string | null;
export type Uri = string;
export type Sha256 = string;
export type Sources = SourceRecord[];
export type Id1 = string;
export type Identifiers = Identifier[];
/**
 * @minItems 1
 */
export type Citations = [Citation, ...Citation[]];
export type Kind1 = 'source_record';
export type Id2 = string;
export type SelectorType =
  ('json_pointer' | 'xpath' | 'css' | 'row_key' | 'page' | 'time' | 'text') | null;
export type Selector = string | null;
export type Quote = string | null;
export type Basis = 'reported' | 'observed' | 'derived' | 'inferred' | 'curated';
export type Name = string;
export type Version = string;
export type Explanation = string | null;
export type Path = string;
export type JsonValue = unknown;
export type Alternatives = AlternativeValue[];
export type SelectionReason = string | null;
export type FieldEvidence = FieldEvidence1[];
export type Kind2 = 'committee';
export type Label = string;
export type Id3 = string;
export type Identifiers1 = Identifier[];
export type FieldEvidence2 = FieldEvidence1[];
export type Kind3 = 'committee_term';
export type Kind4 = 'committee';
export type Id4 = string;
export type Congress = number;
export type Name1 = string | null;
export type Chamber = 'house' | 'senate' | 'joint' | 'unknown';
export type CommitteeType =
  'standing' | 'select' | 'special' | 'joint' | 'subcommittee' | 'other' | 'unknown';
export type Kind5 = 'committee_term';
export type Id5 = string;
export type Start = string | null;
export type End = string | null;
export type Jurisdiction = string | null;
export type Website = string | null;
export type Id6 = string;
export type Identifiers2 = Identifier[];
export type FieldEvidence3 = FieldEvidence1[];
export type Kind6 = 'committee_relation';
export type Relation = 'renamed' | 'replaced' | 'split' | 'merged';
export type Id7 = string;
export type Identifiers3 = Identifier[];
export type FieldEvidence4 = FieldEvidence1[];
export type Kind7 = 'channel';
export type Provider1 = string;
export type Title = string | null;
export type Url1 = string;
export type Id8 = string;
export type Identifiers4 = Identifier[];
export type FieldEvidence5 = FieldEvidence1[];
export type Kind8 = 'committee_channel';
export type Kind9 = 'channel';
export type Id9 = string;
export type Role =
  'official' | 'majority' | 'minority' | 'member' | 'archive' | 'other' | 'unknown';
export type Id10 = string;
export type Identifiers5 = Identifier[];
export type FieldEvidence6 = FieldEvidence1[];
export type Kind10 = 'committee_membership';
export type Kind11 = 'person';
export type Id11 = string;
export type Roles = ('chair' | 'ranking_member' | 'member' | 'ex_officio' | 'staff' | 'other')[];
export type Party = string | null;
export type State = string | null;
export type District = string | null;
export type Id12 = string;
export type Identifiers6 = Identifier[];
export type FieldEvidence7 = FieldEvidence1[];
export type Kind12 = 'meeting';
export type Title1 = string | null;
export type Congress1 = number | null;
export type CongressSession = (1 | 2 | 3) | null;
export type Chamber1 = 'house' | 'senate' | 'joint' | 'unknown';
export type MeetingType =
  'hearing' | 'markup' | 'business' | 'briefing' | 'field_hearing' | 'other' | 'unknown';
export type Role1 = 'host' | 'cohost' | 'participating' | 'unknown';
export type Committees = ConveningCommittee[];
export type Id13 = string;
export type Identifiers7 = Identifier[];
export type FieldEvidence8 = FieldEvidence1[];
export type Kind13 = 'occurrence';
export type Kind14 = 'meeting';
export type Id14 = string;
export type Label1 = string | null;
export type Status =
  'scheduled' | 'rescheduled' | 'postponed' | 'canceled' | 'held' | 'not_held' | 'unknown';
export type Access = 'open' | 'closed' | 'partly_closed' | 'unknown';
export type Label2 = string | null;
export type Building = string | null;
export type Room = string | null;
export type City = string | null;
export type Region = string | null;
export type Country = string | null;
export type Mode = 'in_person' | 'remote' | 'hybrid' | 'unknown';
export type AccessUrl = string | null;
export type Id15 = string;
export type Identifiers8 = Identifier[];
export type FieldEvidence9 = FieldEvidence1[];
export type Kind15 = 'meeting_relation';
export type Relation1 = 'same_proceeding' | 'continuation_of' | 'rescheduled_to' | 'related';
export type Id16 = string;
export type Identifiers9 = Identifier[];
export type FieldEvidence10 = FieldEvidence1[];
export type Kind16 = 'panel';
export type Kind17 = 'occurrence';
export type Id17 = string;
export type Label3 = string | null;
export type Order = number | null;
export type Id18 = string;
export type Identifiers10 = Identifier[];
export type FieldEvidence11 = FieldEvidence1[];
export type Kind18 = 'person';
export type Name2 = string | null;
export type Id19 = string;
export type Identifiers11 = Identifier[];
export type FieldEvidence12 = FieldEvidence1[];
export type Kind19 = 'organization';
export type Name3 = string;
export type Id20 = string;
export type Identifiers12 = Identifier[];
export type FieldEvidence13 = FieldEvidence1[];
export type Kind20 = 'appearance';
export type Kind21 = 'panel';
export type Id21 = string;
export type Display = string;
export type Honorific = string | null;
export type Given = string | null;
export type Middle = string | null;
export type Family = string | null;
export type Suffix = string | null;
export type Retired = string | null;
export type Roles1 = (
  | 'witness'
  | 'nominee'
  | 'chair'
  | 'ranking_member'
  | 'member'
  | 'staff'
  | 'clerk'
  | 'other'
  | 'unknown'
)[];
export type Participation =
  'listed' | 'invited' | 'present' | 'testified' | 'absent' | 'withdrawn' | 'unknown';
export type Kind22 = 'organization';
export type Id22 = string;
export type OrganizationName = string | null;
export type Position = string | null;
export type OnBehalfOf = string | null;
export type Location1 = string | null;
export type Order1 = number | null;
export type Id23 = string;
export type Identifiers13 = Identifier[];
export type FieldEvidence14 = FieldEvidence1[];
export type Kind23 = 'material';
export type Title2 = string | null;
export type Congress2 = number | null;
export type Chamber2 = 'house' | 'senate' | 'joint' | 'unknown';
export type ProceedingDates = ReportedTime[];
export type Details = DocumentDetails | RecordingDetails | TextDetails;
export type Type = 'document';
export type Category =
  | 'transcript'
  | 'statement'
  | 'biography'
  | 'disclosure'
  | 'questions_for_record'
  | 'responses_for_record'
  | 'notice'
  | 'agenda'
  | 'amendment'
  | 'vote'
  | 'report'
  | 'bill_text'
  | 'witness_list'
  | 'hearing_record'
  | 'supporting'
  | 'errata'
  | 'other'
  | 'unknown';
export type Type1 = 'recording';
export type Medium = 'video' | 'audio' | 'unknown';
export type Coverage = 'full' | 'clip' | 'compilation' | 'unknown';
export type Provider2 = string | null;
export type Type2 = 'text';
export type Category1 = 'transcript' | 'captions' | 'translation' | 'summary' | 'other' | 'unknown';
export type Production = 'publisher' | 'human' | 'automatic' | 'mixed' | 'unknown';
export type Id24 = string;
export type Identifiers14 = Identifier[];
export type FieldEvidence15 = FieldEvidence1[];
export type Kind24 = 'material_version';
export type Kind25 = 'material';
export type Id25 = string;
export type Label4 = string | null;
export type Kind26 = 'material_version';
export type Id26 = string;
export type Languages = string[];
export type DurationSeconds = number | null;
export type PageCount = number | null;
export type Id27 = string;
export type Identifiers15 = Identifier[];
export type FieldEvidence16 = FieldEvidence1[];
export type Kind27 = 'representation';
export type Url2 = string;
export type Role2 = 'landing' | 'download' | 'player' | 'stream' | 'api' | 'other' | 'unknown';
export type Locations = MaterialLocation[];
export type MediaType = string | null;
export type FormatLabel = string | null;
export type Encoding = string | null;
export type ByteSize = number | null;
export type Sha2561 = string | null;
export type LocalName = string;
export type Namespace = string | null;
export type Name4 = string;
export type Version1 = string;
export type Url3 = string | null;
export type Id28 = string;
export type Identifiers16 = Identifier[];
export type FieldEvidence17 = FieldEvidence1[];
export type Kind28 = 'material_link';
export type Kind29 =
  | 'meeting'
  | 'occurrence'
  | 'appearance'
  | 'committee_term'
  | 'legislative_item'
  | 'amendment'
  | 'amendment_group'
  | 'vote';
export type Id29 = string;
export type Role3 =
  | 'recording'
  | 'transcript'
  | 'captions'
  | 'statement'
  | 'biography'
  | 'disclosure'
  | 'questions_for_record'
  | 'responses_for_record'
  | 'notice'
  | 'agenda'
  | 'amendment'
  | 'vote_record'
  | 'supporting'
  | 'other'
  | 'unknown';
export type Coverage1 = 'full' | 'partial' | 'unknown';
export type Kind30 = 'representation';
export type Id30 = string;
export type FirstPage = number | null;
export type LastPage = number | null;
export type StartSeconds = number | null;
export type EndSeconds = number | null;
export type Label5 = string | null;
export type Id31 = string;
export type Identifiers17 = Identifier[];
export type FieldEvidence18 = FieldEvidence1[];
export type Kind31 = 'material_relation';
export type Relation2 =
  'derived_from' | 'transcribes' | 'translation_of' | 'corrects' | 'part_of' | 'alternate_of';
export type Id32 = string;
export type Identifiers18 = Identifier[];
export type FieldEvidence19 = FieldEvidence1[];
export type Kind32 = 'speaker_attribution';
export type SpeakerKey = string;
export type Kind33 = 'appearance';
export type Id33 = string;
export type Id34 = string;
export type Identifiers19 = Identifier[];
export type FieldEvidence20 = FieldEvidence1[];
export type Kind34 = 'legislative_item';
export type Congress3 = number;
export type ItemType = 'bill' | 'resolution' | 'nomination' | 'treaty' | 'other' | 'unknown';
export type Designation = string;
export type Title3 = string | null;
export type Id35 = string;
export type Identifiers20 = Identifier[];
export type FieldEvidence21 = FieldEvidence1[];
export type Kind35 = 'meeting_subject';
export type Kind36 = 'legislative_item';
export type Id36 = string;
export type Relationship = 'considered' | 'mentioned' | 'related' | 'unknown';
export type Id37 = string;
export type Identifiers21 = Identifier[];
export type FieldEvidence22 = FieldEvidence1[];
export type Kind37 = 'amendment';
export type Kind38 = 'legislative_item' | 'amendment';
export type Id38 = string;
export type Number = string | null;
export type Description = string | null;
export type AmendmentType = string | null;
export type Name5 = string | null;
export type Role4 = 'sponsor' | 'cosponsor' | 'offered_by' | 'unknown';
export type Sponsors = AmendmentSponsor[];
export type Disposition =
  'offered' | 'adopted' | 'rejected' | 'withdrawn' | 'not_offered' | 'other' | 'unknown';
export type Id39 = string;
export type Identifiers22 = Identifier[];
export type FieldEvidence23 = FieldEvidence1[];
export type Kind39 = 'amendment_group';
export type Label6 = string;
export type Kind40 = 'amendment';
export type Id40 = string;
export type Members = RefLiteralAmendment[];
export type Id41 = string;
export type Identifiers23 = Identifier[];
export type FieldEvidence24 = FieldEvidence1[];
export type Kind41 = 'vote';
export type Kind42 = 'legislative_item' | 'amendment' | 'amendment_group';
export type Id42 = string;
export type Number1 = string | null;
export type Question = string | null;
export type Method1 =
  'roll_call' | 'voice' | 'unanimous_consent' | 'division' | 'other' | 'unknown';
export type Outcome = 'agreed' | 'rejected' | 'tied' | 'other' | 'unknown';
export type Yeas = number | null;
export type Nays = number | null;
export type Present = number | null;
export type NotVoting = number | null;
export type RecordedName1 = string | null;
export type Choice = 'yea' | 'nay' | 'present' | 'not_voting' | 'other' | 'unknown';
export type RawChoice = string | null;
export type Ballots = Ballot[];
export type Id43 = string;
export type Identifiers24 = Identifier[];
export type FieldEvidence25 = FieldEvidence1[];
export type Kind43 = 'assessment';
export type Kind44 =
  'meeting' | 'occurrence' | 'committee_term' | 'channel' | 'material' | 'representation';
export type Id44 = string;
export type Aspect =
  | 'recording'
  | 'transcript'
  | 'captions'
  | 'witnesses'
  | 'documents'
  | 'event_id'
  | 'reachability'
  | 'content';
export type Status1 =
  'available' | 'not_found' | 'unknown' | 'not_applicable' | 'blocked' | 'error';
export type EvaluatedAt = string;
export type ObservedAt = string | ReportedTime | null;
export type Provider3 = string | null;
export type Scope2 = string | null;
export type Explanation1 = string | null;
export type Kind45 = 'material' | 'representation' | 'appearance';
export type Id45 = string;
export type Results = RefLiteralMaterialRepresentationAppearance[];
export type Id46 = string;
export type Identifiers25 = Identifier[];
export type FieldEvidence26 = FieldEvidence1[];
export type Kind46 = 'data_issue';
export type Kind47 =
  | 'committee'
  | 'committee_term'
  | 'committee_relation'
  | 'channel'
  | 'committee_channel'
  | 'committee_membership'
  | 'meeting'
  | 'occurrence'
  | 'meeting_relation'
  | 'panel'
  | 'person'
  | 'organization'
  | 'appearance'
  | 'material'
  | 'material_version'
  | 'representation'
  | 'material_link'
  | 'material_relation'
  | 'speaker_attribution'
  | 'legislative_item'
  | 'meeting_subject'
  | 'amendment'
  | 'amendment_group'
  | 'vote'
  | 'assessment'
  | 'source_record';
export type Id47 = string;
export type FieldPath = string | null;
export type Category2 =
  'missing' | 'unverified' | 'conflicting' | 'incorrect' | 'stale' | 'unlinked' | 'duplicate';
export type Impact = 'blocks_use' | 'affects_interpretation' | 'informational';
export type Status2 = 'open' | 'resolved' | 'dismissed';
export type Summary = string;
export type Explanation2 = string | null;
export type Expected = string | null;
export type DetectedAt = string;
export type LastCheckedAt = string | ReportedTime | null;
export type DecidedAt = string;
export type Explanation3 = string;
export type Records = (
  | Committee
  | CommitteeTerm
  | CommitteeRelation
  | Channel
  | CommitteeChannel
  | CommitteeMembership
  | Meeting
  | MeetingOccurrence
  | MeetingRelation
  | Panel
  | Person
  | Organization
  | Appearance
  | Material
  | MaterialVersion
  | Representation
  | MaterialLink
  | MaterialRelation
  | SpeakerAttribution
  | LegislativeItem
  | MeetingSubject
  | Amendment
  | AmendmentGroup
  | Vote
  | Assessment
  | DataIssue
)[];

/**
 * An export's complete set of records and evidence.
 *
 * Validate this set before partitioning for the site. A single record may refer
 * outside its detail file; do not treat that file as a complete Catalog.
 * Identity is (kind, id). Provider identifiers are aliases, not primary keys.
 */
export interface Catalog {
  schema_version?: SchemaVersion;
  scope?: Scope;
  sources?: Sources;
  records?: Records;
}
/**
 * One version of one provider record, not a mutable provider URL alone.
 *
 * `payload` preserves public, source-native fields, including unknown fields.
 * A source file can instead be retained by digest; a citation locates its record.
 * Import time does not establish when the source was fetched or published.
 */
export interface SourceRecord {
  kind?: Kind;
  id: Id;
  provider: Provider;
  identifier: Identifier;
  input_snapshot_id?: InputSnapshotId;
  url?: Url;
  retrieved_at?: RetrievedAt;
  imported_at?: ImportedAt;
  source_modified_at?: ReportedTime | null;
  payload?: unknown;
  retained?: RetainedContent | null;
}
/**
 * An exact provider identifier. Scope is part of identity, never decoration.
 */
export interface Identifier {
  scheme: Scheme;
  value: Value;
  scope?: Scope1;
}
/**
 * Keep date-only and unzoned local times without inventing midnight or UTC.
 */
export interface ReportedTime {
  date: Date;
  time?: Time;
  timezone?: Timezone;
  precision?: Precision;
  approximate?: Approximate;
  original?: Original;
}
/**
 * Digest pins the exact bytes at uri, including an imported input artifact.
 */
export interface RetainedContent {
  uri: Uri;
  sha256: Sha256;
}
export interface Committee {
  id: Id1;
  identifiers?: Identifiers;
  provenance: Provenance;
  field_evidence?: FieldEvidence;
  kind?: Kind2;
  label: Label;
}
export interface Provenance {
  citations: Citations;
  basis: Basis;
  method?: Method | null;
  explanation?: Explanation;
}
export interface Citation {
  source: RefLiteralSourceRecord;
  selector_type?: SelectorType;
  selector?: Selector;
  quote?: Quote;
}
export interface RefLiteralSourceRecord {
  kind: Kind1;
  id: Id2;
}
export interface Method {
  name: Name;
  version: Version;
}
/**
 * Optional field override; record provenance supplies the ordinary case.
 *
 * Alternatives preserve disagreements without wrapping every domain value in
 * a generic claim. The selected value remains in the domain record itself.
 */
export interface FieldEvidence1 {
  path: Path;
  selected: Provenance;
  alternatives?: Alternatives;
  selection_reason?: SelectionReason;
}
export interface AlternativeValue {
  value: JsonValue;
  provenance: Provenance;
}
export interface CommitteeTerm {
  id: Id3;
  identifiers?: Identifiers1;
  provenance: Provenance;
  field_evidence?: FieldEvidence2;
  kind?: Kind3;
  committee: RefLiteralCommittee;
  congress: Congress;
  name?: Name1;
  chamber: Chamber;
  committee_type?: CommitteeType;
  parent?: RefLiteralCommitteeTerm | null;
  active?: DateRange | null;
  jurisdiction?: Jurisdiction;
  website?: Website;
}
export interface RefLiteralCommittee {
  kind: Kind4;
  id: Id4;
}
export interface RefLiteralCommitteeTerm {
  kind: Kind5;
  id: Id5;
}
export interface DateRange {
  start?: Start;
  end?: End;
}
export interface CommitteeRelation {
  id: Id6;
  identifiers?: Identifiers2;
  provenance: Provenance;
  field_evidence?: FieldEvidence3;
  kind?: Kind6;
  predecessor: RefLiteralCommittee;
  successor: RefLiteralCommittee;
  relation: Relation;
  effective?: DateRange | null;
}
export interface Channel {
  id: Id7;
  identifiers?: Identifiers3;
  provenance: Provenance;
  field_evidence?: FieldEvidence4;
  kind?: Kind7;
  provider: Provider1;
  title?: Title;
  url: Url1;
}
export interface CommitteeChannel {
  id: Id8;
  identifiers?: Identifiers4;
  provenance: Provenance;
  field_evidence?: FieldEvidence5;
  kind?: Kind8;
  committee: RefLiteralCommitteeTerm;
  channel: RefLiteralChannel;
  role?: Role;
  active?: DateRange | null;
}
export interface RefLiteralChannel {
  kind: Kind9;
  id: Id9;
}
export interface CommitteeMembership {
  id: Id10;
  identifiers?: Identifiers5;
  provenance: Provenance;
  field_evidence?: FieldEvidence6;
  kind?: Kind10;
  committee: RefLiteralCommitteeTerm;
  person: RefLiteralPerson;
  roles?: Roles;
  active?: DateRange | null;
  party?: Party;
  state?: State;
  district?: District;
}
export interface RefLiteralPerson {
  kind: Kind11;
  id: Id11;
}
/**
 * A proceeding, retaining its provider IDs even when another entry describes it.
 */
export interface Meeting {
  id: Id12;
  identifiers?: Identifiers6;
  provenance: Provenance;
  field_evidence?: FieldEvidence7;
  kind?: Kind12;
  title?: Title1;
  congress?: Congress1;
  congress_session?: CongressSession;
  chamber?: Chamber1;
  meeting_type?: MeetingType;
  committees?: Committees;
}
export interface ConveningCommittee {
  committee: RefLiteralCommitteeTerm;
  role?: Role1;
  provenance: Provenance;
}
/**
 * One scheduled sitting/day; changes to its schedule remain in source versions.
 *
 * A rescheduled notice alone is not proof that a second sitting took place.
 * Multi-day proceedings may have several occurrences under one meeting.
 */
export interface MeetingOccurrence {
  id: Id13;
  identifiers?: Identifiers7;
  provenance: Provenance;
  field_evidence?: FieldEvidence8;
  kind?: Kind13;
  meeting: RefLiteralMeeting;
  label?: Label1;
  status?: Status;
  access?: Access;
  scheduled_start?: ReportedTime | null;
  scheduled_end?: ReportedTime | null;
  actual_start?: ReportedTime | null;
  actual_end?: ReportedTime | null;
  location?: Location | null;
}
export interface RefLiteralMeeting {
  kind: Kind14;
  id: Id14;
}
export interface Location {
  label?: Label2;
  building?: Building;
  room?: Room;
  city?: City;
  region?: Region;
  country?: Country;
  mode?: Mode;
  access_url?: AccessUrl;
}
export interface MeetingRelation {
  id: Id15;
  identifiers?: Identifiers8;
  provenance: Provenance;
  field_evidence?: FieldEvidence9;
  kind?: Kind15;
  subject: RefLiteralMeeting;
  related: RefLiteralMeeting;
  relation: Relation1;
}
export interface Panel {
  id: Id16;
  identifiers?: Identifiers9;
  provenance: Provenance;
  field_evidence?: FieldEvidence10;
  kind?: Kind16;
  meeting: RefLiteralMeeting;
  occurrence?: RefLiteralOccurrence | null;
  label?: Label3;
  order?: Order;
}
export interface RefLiteralOccurrence {
  kind: Kind17;
  id: Id17;
}
/**
 * Create only with a supported identity; a name-only appearance needs no Person.
 */
export interface Person {
  id: Id18;
  identifiers?: Identifiers10;
  provenance: Provenance;
  field_evidence?: FieldEvidence11;
  kind?: Kind18;
  name?: Name2;
}
export interface Organization {
  id: Id19;
  identifiers?: Identifiers11;
  provenance: Provenance;
  field_evidence?: FieldEvidence12;
  kind?: Kind19;
  name: Name3;
}
/**
 * What a source says about someone's participation in this meeting.
 *
 * Name and affiliation are historical observations, not live Person properties.
 * A nominee named in a title is not automatically a person who testified.
 */
export interface Appearance {
  id: Id20;
  identifiers?: Identifiers12;
  provenance: Provenance;
  field_evidence?: FieldEvidence13;
  kind?: Kind20;
  meeting: RefLiteralMeeting;
  occurrence?: RefLiteralOccurrence | null;
  panel?: RefLiteralPanel | null;
  person?: RefLiteralPerson | null;
  name: RecordedName;
  roles?: Roles1;
  participation?: Participation;
  affiliation?: Affiliation | null;
  order?: Order1;
}
export interface RefLiteralPanel {
  kind: Kind21;
  id: Id21;
}
export interface RecordedName {
  display: Display;
  honorific?: Honorific;
  given?: Given;
  middle?: Middle;
  family?: Family;
  suffix?: Suffix;
  retired?: Retired;
}
export interface Affiliation {
  organization?: RefLiteralOrganization | null;
  organization_name?: OrganizationName;
  position?: Position;
  on_behalf_of?: OnBehalfOf;
  location?: Location1;
}
export interface RefLiteralOrganization {
  kind: Kind22;
  id: Id22;
}
/**
 * One described work/recording/track; it may have no accessible file or meeting.
 */
export interface Material {
  id: Id23;
  identifiers?: Identifiers13;
  provenance: Provenance;
  field_evidence?: FieldEvidence14;
  kind?: Kind23;
  title?: Title2;
  congress?: Congress2;
  chamber?: Chamber2;
  proceeding_dates?: ProceedingDates;
  details: Details;
}
export interface DocumentDetails {
  type?: Type;
  category?: Category;
}
export interface RecordingDetails {
  type?: Type1;
  medium?: Medium;
  coverage?: Coverage;
  provider?: Provider2;
  channel?: RefLiteralChannel | null;
}
/**
 * A distinct text product, including captions and generated transcripts.
 */
export interface TextDetails {
  type?: Type2;
  category?: Category1;
  production?: Production;
}
/**
 * An edition or revision of a material, not a new version on every crawl.
 */
export interface MaterialVersion {
  id: Id24;
  identifiers?: Identifiers14;
  provenance: Provenance;
  field_evidence?: FieldEvidence15;
  kind?: Kind24;
  material: RefLiteralMaterial;
  label?: Label4;
  supersedes?: RefLiteralMaterialVersion | null;
  published_at?: ReportedTime | null;
  source_modified_at?: ReportedTime | null;
  generated_at?: ReportedTime | null;
  languages?: Languages;
  duration_seconds?: DurationSeconds;
  page_count?: PageCount;
}
export interface RefLiteralMaterial {
  kind: Kind25;
  id: Id25;
}
export interface RefLiteralMaterialVersion {
  kind: Kind26;
  id: Id26;
}
/**
 * A file/encoding of one version; a reported URL does not prove fetched bytes.
 *
 * Different formats can encode the same version. Share a representation across
 * source listings only with evidence of identity; identical basenames do not
 * establish it. Locations retain exact provider URLs, never guessed suffixes.
 */
export interface Representation {
  id: Id27;
  identifiers?: Identifiers15;
  provenance: Provenance;
  field_evidence?: FieldEvidence16;
  kind?: Kind27;
  version: RefLiteralMaterialVersion;
  locations?: Locations;
  media_type?: MediaType;
  format_label?: FormatLabel;
  encoding?: Encoding;
  byte_size?: ByteSize;
  sha256?: Sha2561;
  retained?: RetainedContent | null;
  xml_root?: XmlRoot | null;
  content_schema?: ContentSchema | null;
}
export interface MaterialLocation {
  url: Url2;
  role?: Role2;
}
/**
 * Actual XML root metadata; amendment-doc is not an amendment identifier.
 */
export interface XmlRoot {
  local_name: LocalName;
  namespace?: Namespace;
}
export interface ContentSchema {
  name: Name4;
  version: Version1;
  url?: Url3;
}
/**
 * A material's role for a subject. The same material can serve many subjects.
 */
export interface MaterialLink {
  id: Id28;
  identifiers?: Identifiers16;
  provenance: Provenance;
  field_evidence?: FieldEvidence17;
  kind?: Kind28;
  material: RefLiteralMaterial;
  version?: RefLiteralMaterialVersion | null;
  subject: RefLiteralMeetingOccurrenceAppearanceCommitteeTermLegislativeItemAmendmentAmendmentGroupVote;
  role?: Role3;
  coverage?: Coverage1;
  extent?: Extent | null;
}
export interface RefLiteralMeetingOccurrenceAppearanceCommitteeTermLegislativeItemAmendmentAmendmentGroupVote {
  kind: Kind29;
  id: Id29;
}
/**
 * A portion of an exact file/stream, not interchangeable PDF/HTML pagination.
 */
export interface Extent {
  representation: RefLiteralRepresentation;
  first_page?: FirstPage;
  last_page?: LastPage;
  start_seconds?: StartSeconds;
  end_seconds?: EndSeconds;
  label?: Label5;
}
export interface RefLiteralRepresentation {
  kind: Kind30;
  id: Id30;
}
/**
 * A directed relationship between particular material versions.
 *
 * Example: generated transcript subject -> recording related, derived_from.
 * Standalone printed transcripts do not require this relationship.
 */
export interface MaterialRelation {
  id: Id31;
  identifiers?: Identifiers17;
  provenance: Provenance;
  field_evidence?: FieldEvidence18;
  kind?: Kind31;
  subject: RefLiteralMaterialVersion;
  related: RefLiteralMaterialVersion;
  relation: Relation2;
  subject_extent?: Extent | null;
  related_extent?: Extent | null;
}
/**
 * Optional bridge from a transcript's local speaker key to an appearance.
 *
 * Transcript turns and text remain in the existing body schema. A local speaker
 * can be unresolved; do not allocate a Person just to fill this reference.
 */
export interface SpeakerAttribution {
  id: Id32;
  identifiers?: Identifiers18;
  provenance: Provenance;
  field_evidence?: FieldEvidence19;
  kind?: Kind32;
  representation: RefLiteralRepresentation;
  speaker_key: SpeakerKey;
  appearance: RefLiteralAppearance;
}
export interface RefLiteralAppearance {
  kind: Kind33;
  id: Id33;
}
export interface LegislativeItem {
  id: Id34;
  identifiers?: Identifiers19;
  provenance: Provenance;
  field_evidence?: FieldEvidence20;
  kind?: Kind34;
  congress: Congress3;
  item_type?: ItemType;
  designation: Designation;
  title?: Title3;
}
export interface MeetingSubject {
  id: Id35;
  identifiers?: Identifiers20;
  provenance: Provenance;
  field_evidence?: FieldEvidence21;
  kind?: Kind35;
  meeting: RefLiteralMeeting;
  item: RefLiteralLegislativeItem;
  relationship?: Relationship;
}
export interface RefLiteralLegislativeItem {
  kind: Kind36;
  id: Id36;
}
/**
 * Local numbers are scoped to a meeting; amendments may lack file URLs.
 */
export interface Amendment {
  id: Id37;
  identifiers?: Identifiers21;
  provenance: Provenance;
  field_evidence?: FieldEvidence22;
  kind?: Kind37;
  meeting: RefLiteralMeeting;
  occurrence?: RefLiteralOccurrence | null;
  target?: RefLiteralLegislativeItemAmendment | null;
  number?: Number;
  description?: Description;
  amendment_type?: AmendmentType;
  sponsors?: Sponsors;
  disposition?: Disposition;
}
export interface RefLiteralLegislativeItemAmendment {
  kind: Kind38;
  id: Id38;
}
export interface AmendmentSponsor {
  person?: RefLiteralPerson | null;
  name?: Name5;
  role?: Role4;
  provenance: Provenance;
}
/**
 * An en-bloc group; retain a label even if the source omits its membership.
 */
export interface AmendmentGroup {
  id: Id39;
  identifiers?: Identifiers22;
  provenance: Provenance;
  field_evidence?: FieldEvidence23;
  kind?: Kind39;
  meeting: RefLiteralMeeting;
  label: Label6;
  members?: Members;
}
export interface RefLiteralAmendment {
  kind: Kind40;
  id: Id40;
}
/**
 * A recorded committee action; a vote attachment need not include a tally.
 */
export interface Vote {
  id: Id41;
  identifiers?: Identifiers23;
  provenance: Provenance;
  field_evidence?: FieldEvidence24;
  kind?: Kind41;
  meeting: RefLiteralMeeting;
  occurrence?: RefLiteralOccurrence | null;
  committee?: RefLiteralCommitteeTerm | null;
  subject?: RefLiteralLegislativeItemAmendmentAmendmentGroup | null;
  number?: Number1;
  question?: Question;
  method?: Method1;
  outcome?: Outcome;
  held_at?: ReportedTime | null;
  tally?: VoteTally | null;
  ballots?: Ballots;
}
export interface RefLiteralLegislativeItemAmendmentAmendmentGroup {
  kind: Kind42;
  id: Id42;
}
/**
 * Absent counts stay unknown; no implicit zero or assumed full roll call.
 */
export interface VoteTally {
  yeas?: Yeas;
  nays?: Nays;
  present?: Present;
  not_voting?: NotVoting;
}
export interface Ballot {
  person?: RefLiteralPerson | null;
  recorded_name?: RecordedName1;
  choice?: Choice;
  raw_choice?: RawChoice;
  provenance: Provenance;
}
export interface Assessment {
  id: Id43;
  identifiers?: Identifiers24;
  provenance: Provenance;
  field_evidence?: FieldEvidence25;
  kind?: Kind43;
  subject: RefLiteralMeetingOccurrenceCommitteeTermChannelMaterialRepresentation;
  aspect: Aspect;
  status: Status1;
  evaluated_at: EvaluatedAt;
  observed_at?: ObservedAt;
  provider?: Provider3;
  scope?: Scope2;
  explanation?: Explanation1;
  results?: Results;
}
export interface RefLiteralMeetingOccurrenceCommitteeTermChannelMaterialRepresentation {
  kind: Kind44;
  id: Id44;
}
export interface RefLiteralMaterialRepresentationAppearance {
  kind: Kind45;
  id: Id45;
}
/**
 * A known limitation, supported expectation or documented correction.
 *
 * Missing requires a reason to expect the item; null fields alone are not
 * defects. Conflicting facts are not proof that either source is incorrect.
 * Closing an issue retains its original evidence and a separate decision.
 */
export interface DataIssue {
  id: Id46;
  identifiers?: Identifiers25;
  provenance: Provenance;
  field_evidence?: FieldEvidence26;
  kind?: Kind46;
  subject: RefLiteralCommitteeCommitteeTermCommitteeRelationChannelCommitteeChannelCommitteeMembershipMeetingOccurrenceMeetingRelationPanelPersonOrganizationAppearanceMaterialMaterialVersionRepresentationMaterialLinkMaterialRelationSpeakerAttributionLegislativeItemMeetingSubjectAmendmentAmendmentGroupVoteAssessmentSourceRecord;
  field_path?: FieldPath;
  category: Category2;
  impact?: Impact;
  status?: Status2;
  summary: Summary;
  explanation?: Explanation2;
  expected?: Expected;
  detected_at: DetectedAt;
  last_checked_at?: LastCheckedAt;
  resolution?: IssueResolution | null;
}
export interface RefLiteralCommitteeCommitteeTermCommitteeRelationChannelCommitteeChannelCommitteeMembershipMeetingOccurrenceMeetingRelationPanelPersonOrganizationAppearanceMaterialMaterialVersionRepresentationMaterialLinkMaterialRelationSpeakerAttributionLegislativeItemMeetingSubjectAmendmentAmendmentGroupVoteAssessmentSourceRecord {
  kind: Kind47;
  id: Id47;
}
export interface IssueResolution {
  decided_at: DecidedAt;
  explanation: Explanation3;
  provenance: Provenance;
}
