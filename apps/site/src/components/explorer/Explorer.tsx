import { useEffect, useRef, useState } from "react";
import {
  openPublicationReader,
  type CoverageSummary,
  type ExplorerQuery,
  type ExplorerReader,
  type ExplorerRecordRef,
  type QueryInfo,
  type QueryKind,
  type QueryResult,
  type RelatedResult,
} from "./reader/data-source.ts";
import {
  recordedCategoryLabel,
  sameRecordedTitle,
  titleInContext,
} from "./browse/related-materials.ts";
import { BackIcon, ExternalIcon, ForwardIcon } from "./view/icons";
import {
  RecordDetail,
  SourceLinkGroups,
  documentType,
  enumLabel,
  fields,
  publicUrl,
  recordTitle,
  type DetailRecord,
} from "./view/RecordDetail";
import Coverage from "./view/Coverage";
import RelatedMaterials, { OpenIssues } from "./view/RelatedMaterials";
import {
  PAGE_SIZE,
  Pagination,
  RequestMessage,
  SortLabel,
  integer,
  useRequest,
} from "./view/request-state";
import { downloadJson } from "./view/download";
import {
  accessStates,
  committeeTypes,
  materialCategories,
  materialProviders,
  nextSort,
  readNavigation,
  viewNavigation,
  drillNavigation,
  type Navigation,
  type View,
} from "./browse/navigation.ts";
import { issueCategories } from "./browse/kinds.ts";
import {
  categoryNote,
  committeeKindNote,
  committeeLevelLabel,
  committeeLevelNote,
  committeeSourceNote,
  committeeTypeLabel,
  committeeWebsite,
  coverageDrillNote,
  dateFilterReason,
  earlierCommitteeNames,
  detectedNote,
  documentSourceLabel,
  extraIssueAlternatives,
  listedDocumentType,
  listedEvidence,
  listedSourcePile,
  listedWitnessCount,
  filePartNote,
  issueNotes,
  issueStatusLabel,
  severityLabel,
  landingPageNote,
  linkedMeetingIds,
  listedSourceStatus,
  listedWhen,
  listTitle,
  meetingStatusNote,
  notableRoles,
  omitRepeatedChamber,
  omitRepeatedCongress,
  omitRepeatedWhen,
  participationNote,
  plainRecordedNote,
  providerLabel,
  publishedNote,
  recordedAction,
  recordedAddressNames,
  recordedAmendments,
  recordedFileNames,
  recordedFormatNote,
  recordedInstant,
  recordedMeasureValues,
  recordedPlace,
  recordedTitlePreview,
  recordedVotes,
  recordedWhen,
  recordedWitnesses,
  recordingIdentity,
  relatedParts,
  scheduleNote,
  sourceCountNote,
  sourceName,
  witnessNameList,
  sourceFacts,
  sourceLinks,
  sourcePageUrl,
  sourceTypeNote,
  subjectAbsentNote,
  subjectKindLabel,
  witnessNotes,
  congressName,
} from "./browse/record-presentation.ts";

const VIEWS = [
  { key: "meetings", label: "Meetings", kind: "meeting" },
  { key: "committees", label: "Committees", kind: "committee_term" },
  { key: "materials", label: "Recordings & documents", kind: "material" },
  { key: "witnesses", label: "Witnesses", kind: "appearance" },
  { key: "coverage", label: "Coverage", kind: "meeting" },
  { key: "gaps", label: "Gaps & issues", kind: "data_issue" },
] as const satisfies readonly { key: View; label: string; kind: QueryKind }[];

/** Keep a recorded calendar day on one line. */
const keepDate = (value: string) =>
  value.replace(/(\d{4})-(\d{2})-(\d{2})/g, "$1\u2011$2\u2011$3");

function preparedWhen(value: unknown): string {
  const text = String(value || "").trim();
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(text);
  return match ? `${match[1]} at ${match[2]} UTC` : "date not recorded";
}

/** Composition root: only this adapter choice knows a publication URL. */
export default function Explorer({ pointerUrl }: { pointerUrl: string }) {
  const [state, retry] = useRequest(
    (signal) => openPublicationReader({ pointerUrl, signal }),
    [pointerUrl],
  );
  return state.status === "ready" ? (
    <CommitteeExplorer reader={state.value} />
  ) : (
    <div className="explorer">
      <RequestMessage
        state={state}
        retry={retry}
        noun="the published archive"
      />
    </div>
  );
}

/** The application accepts domain queries; JSON, Parquet and transport stay in the reader. */
export function CommitteeExplorer({ reader }: { reader: ExplorerReader }) {
  const [state, retry] = useRequest(
    (signal) => reader.getQueryInfo({ signal }),
    [reader],
  );
  return state.status === "ready" ? (
    <Workspace reader={reader} info={state.value} />
  ) : (
    <div className="explorer">
      <RequestMessage state={state} retry={retry} noun="the archive" />
    </div>
  );
}

function writeNavigation(nav: Navigation, replace: boolean) {
  const url = new URL(window.location.href);
  url.search = "";
  for (const [key, value] of Object.entries(nav))
    if (value !== "" && !(key === "page" && value === 0))
      url.searchParams.set(key, String(value));
  window.history[replace ? "replaceState" : "pushState"](
    nav.kind && nav.id ? { explorerDetail: true } : null,
    "",
    url,
  );
}
function toQuery(nav: Navigation, info: QueryInfo): ExplorerQuery {
  const query: ExplorerQuery = {
    kind: VIEWS.find((view) => view.key === nav.view)!.kind,
    congress: nav.congress === "all" ? "all" : Number(nav.congress),
    chamber: nav.chamber || undefined,
    q: nav.q || undefined,
    dateFrom: nav.view === "committees" ? undefined : nav.from || undefined,
    dateTo: nav.view === "committees" ? undefined : nav.to || undefined,
    type: nav.type || undefined,
    status: nav.status || undefined,
    category:
      nav.view === "gaps"
        ? nav.category || undefined
        : nav.view === "materials"
          ? nav.materialCategory || undefined
          : undefined,
    severity: nav.view === "gaps" ? nav.severity || undefined : undefined,
    participation:
      nav.view === "witnesses" ? nav.participation || undefined : undefined,
    provider:
      nav.view === "materials"
        ? nav.provider || undefined
        : undefined,
    history: nav.view === "gaps" ? nav.history || undefined : undefined,
    committeeId: nav.committee || undefined,
    month: nav.month || undefined,
    committeeLevel: info.supported_filters?.includes("committeeLevel")
      ? nav.committeeLevel || undefined
      : undefined,
    committeeType: info.supported_filters?.includes("committeeType")
      ? nav.committeeType || undefined
      : undefined,
    access:
      info.supported_filters?.includes("access") &&
      (nav.view === "meetings" || nav.view === "coverage")
        ? nav.access || undefined
        : undefined,
    aspect: nav.aspect || undefined,
    evidence: nav.evidence || undefined,
    offset: nav.page * PAGE_SIZE,
    limit: PAGE_SIZE,
    sort: nav.sort || undefined,
    direction: nav.sort ? nav.direction || "asc" : undefined,
  };
  return query;
}

function Workspace({
  reader,
  info,
}: {
  reader: ExplorerReader;
  info: QueryInfo;
}) {
  const [nav, setNav] = useState(() =>
    readNavigation(window.location.search, info.default_congress),
  );
  const [queryText, setQueryText] = useState(nav.q);
  const headingRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const pop = () => {
      const next = readNavigation(
        window.location.search,
        info.default_congress,
      );
      setNav(next);
      setQueryText(next.q);
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, [info.default_congress]);
  const update = (patch: Partial<Navigation>, replace = false) => {
    const next = { ...nav, ...patch };
    writeNavigation(next, replace);
    setNav(next);
    if (patch.q !== undefined) setQueryText(patch.q);
  };
  const filter = (patch: Partial<Navigation>) =>
    update({ ...patch, page: 0, kind: "", id: "" });
  const select = (ref: ExplorerRecordRef) => {
    update({ kind: ref.kind, id: ref.id }, Boolean(nav.kind && nav.id));
    headingRef.current?.focus({ preventScroll: true });
    headingRef.current?.scrollIntoView({ block: "start", behavior: "instant" });
  };
  const query = toQuery(nav, info);
  const selection = nav.kind && nav.id ? { kind: nav.kind, id: nav.id } : null;
  const changeView = (view: View) => update(viewNavigation(nav, view));
  const drill = (patch: ExplorerQuery) => update(drillNavigation(nav, patch));
  const reset = () => {
    const next: Navigation = {
      view: nav.view,
      congress: String(info.default_congress),
      chamber: "",
      q: "",
      from: "",
      to: "",
      type: "",
      status: "",
      category: "",
      severity: "",
      materialCategory: "",
      participation: "",
      provider: "",
      history: "",
      access: "",
      page: 0,
      kind: "",
      id: "",
      committee: "",
      committeeLevel: "",
      committeeType: "",
      month: "",
      aspect: "",
      evidence: "",
      measure: "transcript",
      grouping: "congress",
      sort: "",
      direction: "",
    };
    writeNavigation(next, false);
    setNav(next);
    setQueryText("");
  };
  const dateError =
    nav.view !== "committees" &&
    nav.from &&
    nav.to &&
    nav.from > nav.to;
  const hasDrill = nav.committee || nav.month || nav.aspect || nav.evidence;
  const closeDetail = () => {
    if (
      window.history.state &&
      (window.history.state as { explorerDetail?: boolean }).explorerDetail
    )
      window.history.back();
    else update({ kind: "", id: "" }, true);
    headingRef.current?.focus({ preventScroll: true });
  };
  return (
    <div className="explorer">
      <div className="explorer-publication">
        <span>Prepared {preparedWhen(reader.publication.generated_at)}</span>
      </div>
      <nav className="explorer-tabs" aria-label="Explorer workspaces">
        {VIEWS.map((view) => (
          <button
            key={view.key}
            aria-current={nav.view === view.key ? "page" : undefined}
            aria-label={`${view.label}. ${view.key === "coverage" ? "Counts of recorded evidence for the current selection." : VIEW_NOTES[view.key]}`}
            onClick={() => changeView(view.key)}
          >
            {view.label}
          </button>
        ))}
      </nav>
      <form
        className="explorer-filters"
        aria-label="Filter committee records"
        onSubmit={(event) => {
          event.preventDefault();
          filter({ q: queryText });
        }}
      >
        <div className="explorer-search">
          <label>
            <span>Search this workspace</span>
            <span className="explorer-field-reason">
              Find a title, vote, note, or other recorded text in this workspace.
            </span>
            <input
              type="search"
              value={queryText}
              onChange={(event) => setQueryText(event.target.value)}
              placeholder="Title or recorded text"
            />
          </label>
          <button
            type="submit"
            className="explorer-button"
            aria-label="Search this workspace with the text in the box"
          >
            Search
          </button>
        </div>
        <label>
          <span>Congress</span>
          <span className="explorer-field-reason">
            Keep one Congress, or search every Congress in this archive.
          </span>
          <select
            value={nav.congress}
            onChange={(event) => filter({ congress: event.target.value })}
          >
            <option value="all">All Congresses</option>
            {info.congresses.map((value) => (
              <option key={value} value={value}>
                {value}th Congress
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Chamber</span>
          <span className="explorer-field-reason">
            House, Senate, joint, or a chamber the source did not record.
          </span>
          <select
            value={nav.chamber}
            onChange={(event) => filter({ chamber: event.target.value })}
          >
            <option value="">All chambers</option>
            <option value="house">House</option>
            <option value="senate">Senate</option>
            <option value="joint">Joint</option>
            <option value="unknown">Not recorded</option>
          </select>
        </label>
        {info.supported_filters?.includes("committeeLevel") ? (
          <label>
            <span>Committee level</span>
            <span className="explorer-field-reason">
              All levels keeps subcommittees. Full committees only leaves them
              out, along with records that have no recorded level.
            </span>
            <select
              value={nav.committeeLevel}
              onChange={(event) =>
                filter({
                  committeeLevel: event.target.value === "full" ? "full" : "",
                })
              }
            >
              <option value="">All levels</option>
              <option value="full">Full committees only</option>
            </select>
          </label>
        ) : null}
        {info.supported_filters?.includes("committeeType") ? (
          <label>
            <span>Committee type</span>
            <span className="explorer-field-reason">
              Standing, select, and the other types recorded for the committee.
            </span>
            <select
              value={nav.committeeType}
              onChange={(event) =>
                filter({ committeeType: event.target.value })
              }
            >
              <option value="">All committee types</option>
              {committeeTypes.map((value) => (
                <option key={value} value={value}>
                  {value === "unknown" ? "Not recorded" : enumLabel(value)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {nav.view !== "committees" ? (
          <>
            <label>
              <span>From date</span>
              <span className="explorer-field-reason">
                {dateFilterReason(nav.view, "from")}
              </span>
              <input
                type="date"
                value={nav.from}
                onChange={(event) => filter({ from: event.target.value })}
              />
            </label>
            <label>
              <span>Through date</span>
              <span className="explorer-field-reason">
                {dateFilterReason(nav.view, "through")}
              </span>
              <input
                type="date"
                value={nav.to}
                onChange={(event) => filter({ to: event.target.value })}
              />
            </label>
          </>
        ) : null}
        {nav.view === "materials" ? (
          <>
            <label>
              <span>Material type</span>
              <span className="explorer-field-reason">
                Documents, recordings, or captions and transcripts linked to a
                meeting.
              </span>
              <select
                value={nav.type}
                onChange={(event) => filter({ type: event.target.value })}
              >
                <option value="">All types</option>
                <option value="document">Document</option>
                <option value="recording">Recording</option>
                <option value="text">Captions or transcript</option>
              </select>
            </label>
            <label>
              <span>Document category</span>
              <span className="explorer-field-reason">
                Statement, amendment, transcript, and the other recorded
                categories. Choosing one keeps only that category; most
                recordings have none.
              </span>
              <select
                value={nav.materialCategory}
                onChange={(event) =>
                  filter({ materialCategory: event.target.value })
                }
              >
                <option value="">All categories</option>
                {materialCategories.map((value) => (
                  <option key={value} value={value}>
                    {value === "unknown"
                      ? "Not recorded"
                      : recordedCategoryLabel(value)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Published by</span>
              <span className="explorer-field-reason">
                YouTube, Senate.gov, C-SPAN, and the other sites that published
                the file. Senate.gov, untitled is a Senate.gov video saved only
                as “Recording.” Choosing one site keeps only that site.
              </span>
              <select
                value={nav.provider}
                onChange={(event) => filter({ provider: event.target.value })}
              >
                <option value="">All sites</option>
                {materialProviders.map((value) => (
                  <option key={value} value={value}>
                    {value === "www.senate.gov"
                      ? "Senate.gov, untitled"
                      : providerLabel(value)}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : null}
        {nav.view === "meetings" || nav.view === "coverage" ? (
          <label>
            <span>Meeting type</span>
            <span className="explorer-field-reason">
              Hearing, markup, business meeting, and the other recorded types.
            </span>
            <select
              value={nav.type}
              onChange={(event) => filter({ type: event.target.value })}
            >
              <option value="">All types</option>
              <option value="hearing">Hearing</option>
              <option value="markup">Markup</option>
              <option value="business">Business meeting</option>
              <option value="meeting">Meeting</option>
              <option value="briefing">Briefing</option>
              <option value="roundtable">Roundtable</option>
              <option value="field_hearing">Field hearing</option>
              <option value="other">Other</option>
              <option value="unknown">Not recorded</option>
            </select>
          </label>
        ) : null}
        {info.supported_filters?.includes("access") &&
        (nav.view === "meetings" || nav.view === "coverage") ? (
          <label>
            <span>Access</span>
            <span className="explorer-field-reason">
              Whether the meeting was recorded as open, closed, or partly
              closed.
            </span>
            <select
              value={nav.access}
              onChange={(event) => filter({ access: event.target.value })}
            >
              <option value="">All access states</option>
              {accessStates.map((value) => (
                <option key={value} value={value}>
                  {value === "unknown" ? "Not recorded" : enumLabel(value)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {nav.view === "meetings" || nav.view === "coverage" ? (
          <label>
            <span>Meeting status</span>
            <span className="explorer-field-reason">
              Upcoming, past, and today come from the schedule. Canceled and
              postponed stay as recorded.
            </span>
            <select
              value={nav.status}
              onChange={(event) => filter({ status: event.target.value })}
            >
              <option value="">All statuses</option>
              <option value="upcoming">Upcoming</option>
              <option value="past">Past</option>
              <option value="today">Today</option>
              <option value="postponed">Postponed</option>
              <option value="canceled">Canceled</option>
            </select>
          </label>
        ) : null}
        {nav.view === "witnesses" ? (
          <label>
            <span>Participation</span>
            <span className="explorer-field-reason">
              Testified means the record says the witness testified. Listed is
              everyone else on the witness list.
            </span>
            <select
              value={nav.participation}
              onChange={(event) =>
                filter({
                  participation:
                    event.target.value === "testified" ||
                    event.target.value === "listed"
                      ? event.target.value
                      : "",
                })
              }
            >
              <option value="">All participation</option>
              <option value="testified">Testified</option>
              <option value="listed">Listed</option>
            </select>
          </label>
        ) : null}
        {nav.view === "gaps" ? (
          <>
            <label>
              <span>Issue status</span>
              <span className="explorer-field-reason">
                Still open means the issue still needs work. Resolved and
                dismissed are closed.
              </span>
              <select
                value={nav.status}
                onChange={(event) => filter({ status: event.target.value })}
              >
                <option value="">All statuses</option>
                <option value="open">Still open</option>
                <option value="resolved">Resolved</option>
                <option value="dismissed">Dismissed</option>
              </select>
            </label>
            <label>
              <span>Which copy</span>
              <span className="explorer-field-reason">
                The latest copy is what this archive has now. An earlier copy is
                a previous saved version.
              </span>
              <select
                value={nav.history}
                onChange={(event) =>
                  filter({
                    history:
                      event.target.value === "current" ||
                      event.target.value === "retained"
                        ? event.target.value
                        : "",
                  })
                }
              >
                <option value="">All copies</option>
                <option value="current">Latest copy</option>
                <option value="retained">Earlier copy</option>
              </select>
            </label>
            <label>
              <span>Issue category</span>
              <span className="explorer-field-reason">
                Unlinked has no meeting match. Unverified and conflicting
                describe the recorded comparison. Duplicate and incorrect name a
                repeated or wrong recorded value.
              </span>
              <select
                value={nav.category}
                onChange={(event) => filter({ category: event.target.value })}
              >
                <option value="">All categories</option>
                {issueCategories.map((category) => (
                  <option key={category} value={category}>
                    {enumLabel(category)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>How to read it</span>
              <span className="explorer-field-reason">
                Changes how to read it means the record should be read
                differently. For information only leaves the record as it is.
              </span>
              <select
                value={nav.severity}
                onChange={(event) => filter({ severity: event.target.value })}
              >
                <option value="">All</option>
                <option value="affects_interpretation">
                  Changes how to read it
                </option>
                <option value="informational">For information only</option>
              </select>
            </label>
          </>
        ) : null}
        <button
          type="button"
          className="explorer-text-button"
          aria-label="Reset every filter to this workspace’s defaults"
          onClick={reset}
        >
          Reset
        </button>
      </form>
      {hasDrill ? (
        <div className="explorer-subheading">
          <p className="explorer-note">
            {coverageDrillNote({
              committee: nav.committee
                ? info.committee_labels?.[nav.committee] ||
                  "the selected committee"
                : "",
              month: nav.month,
              aspect: nav.aspect,
              evidence: nav.evidence,
            })}
          </p>
          <button
            className="explorer-text-button"
            aria-label="Remove the committee, month, and evidence limits that came from a coverage chart"
            onClick={() =>
              filter({ committee: "", month: "", aspect: "", evidence: "" })
            }
          >
            Clear chart filters
          </button>
        </div>
      ) : null}
      {nav.congress === "all" ? (
        <p className="explorer-note">
          Searching every Congress looks through the whole archive and may take
          longer.
        </p>
      ) : null}
      {nav.view === "gaps" && nav.congress !== "all" ? (
        <p className="explorer-note">
          Issues with no recorded Congress are listed under All Congresses.
        </p>
      ) : null}
      {nav.view === "materials" &&
      nav.congress !== "all" ? (
        <p className="explorer-note">
          Recordings and documents with no recorded Congress are listed under
          All Congresses.
        </p>
      ) : null}
      <section
        ref={headingRef}
        tabIndex={-1}
        className="explorer-workspace"
        aria-label="Explorer results"
      >
        {dateError ? (
          <p className="explorer-alert" role="alert">
            The start date must be on or before the end date.
          </p>
        ) : selection ? (
          <Inspector
            key={`${selection.kind}/${selection.id}`}
            reader={reader}
            selected={selection}
            onSelect={select}
            committeeLabels={info.committee_labels}
            onClose={closeDetail}
          />
        ) : nav.view === "coverage" ? (
          <CoverageView
            reader={reader}
            query={query}
            onDrill={drill}
            measure={nav.measure}
            grouping={nav.grouping}
            onSettings={update}
          />
        ) : (
          <Listing
            reader={reader}
            query={query}
            view={nav.view}
            info={info}
            nav={nav}
            onSelect={select}
            onPage={(page) => update({ page })}
            onSort={(patch) => update({ ...patch, page: 0 })}
          />
        )}
      </section>
      {!selection && (nav.view === "coverage" || nav.view === "gaps") ? (
        <PublicationScope publication={reader.publication} />
      ) : null}
    </div>
  );
}

function coverageDates(item: { coverage?: unknown }): string {
  const coverage = fields(item.coverage);
  const start = coverage.start ? String(coverage.start) : "";
  const end = coverage.end ? String(coverage.end) : "";
  if (!start && !end) return "";
  return `${start || "Unknown"} to ${end || "Unknown"}`;
}

function coverageLabel(item: { scope?: unknown }): string {
  const raw = String(item.scope || "");
  const plain = plainRecordedNote(raw);
  return plain === raw ? enumLabel(raw) || raw : plain;
}

function PublicationScope({
  publication,
}: {
  publication: Readonly<Record<string, unknown>>;
}) {
  const scopes = Array.isArray(publication.source_scopes)
    ? publication.source_scopes.map(fields)
    : [];
  const inputs = Array.isArray(publication.inputs)
    ? publication.inputs.map(fields)
    : [];
  const limitations = Array.isArray(publication.limitations)
    ? publication.limitations
    : [];
  const grouped = new Map<string, typeof scopes>();
  for (const scope of scopes) {
    const key = JSON.stringify([
      scope.provider,
      scope.status,
      scope.explanation,
    ]);
    const group = grouped.get(key) || [];
    group.push(scope);
    grouped.set(key, group);
  }
  const checks = new Map<
    string,
    { input: (typeof inputs)[number]; count: number }
  >();
  for (const input of inputs) {
    const key = JSON.stringify([
      input.provider,
      input.limitations,
      input.last_observed_at,
      input.last_attempt_status,
      input.last_attempt_at,
      input.imported_at,
    ]);
    const existing = checks.get(key);
    if (existing) existing.count += 1;
    else checks.set(key, { input, count: 1 });
  }
  const exactNotes = [
    ...new Set(
      [
        ...scopes.flatMap((scope) => [
          String(scope.scope || ""),
          String(scope.explanation || ""),
        ]),
        ...limitations.map(String),
        ...inputs.flatMap((input) =>
          Array.isArray(input.limitations) ? input.limitations.map(String) : [],
        ),
      ]
        .map((text) => text.trim())
        .filter((text) => text && plainRecordedNote(text) !== text),
    ),
  ];
  return (
    <section className="explorer-detail-section">
      <h3>Source coverage and limits</h3>
      <p className="explorer-note">
        This describes the whole archive, not just the filters above. Including
        a source still leaves room for documents that were never captured.
      </p>
      {scopes.length ? (
        <div className="explorer-table-scroll">
          <table className="explorer-table">
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Collection status</th>
                <th scope="col">What was collected</th>
              </tr>
            </thead>
            <tbody>
              {[...grouped.values()].map((group, index) => {
                const scope = group[0];
                const collected = plainRecordedNote(String(scope.scope || ""));
                const parts = group.map((item) => ({
                  label: coverageLabel(item),
                  dates: coverageDates(item),
                  raw: String(item.scope || ""),
                }));
                const dated = parts.filter((part) => part.dates);
                return (
                  <tr key={index}>
                    <th scope="row">
                      {sourceName(String(scope.provider))}
                      {group.length > 1 ? (
                        <span className="explorer-row-meta">
                          {integer(group.length)}{" "}
                          {dated.length ? "date ranges" : "parts"}
                        </span>
                      ) : null}
                    </th>
                    <td>{enumLabel(scope.status)}</td>
                    <td>
                      {group.length === 1
                        ? collected === String(scope.scope || "")
                          ? enumLabel(scope.scope)
                          : collected
                        : null}
                      {parts.length === 1 && parts[0].dates ? (
                        <span className="explorer-row-meta">
                          Dates covered: {parts[0].dates}
                        </span>
                      ) : null}
                      <span className="explorer-row-meta">
                        {plainRecordedNote(String(scope.explanation || ""))}
                      </span>
                      {dated.length > 1 ? (
                        <details>
                          <summary>
                            Dates covered
                            <span className="explorer-field-reason">
                              The dates recorded for each part of this
                              collection.
                            </span>
                          </summary>
                          <ul className="explorer-values">
                            {parts.map((part, itemIndex) => (
                              <li key={itemIndex}>
                                {part.label !== collected ? (
                                  <strong>{part.label}</strong>
                                ) : null}
                                <span className="explorer-row-meta">
                                  {part.dates || "Dates not recorded"}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </details>
                      ) : group.length > 1 ? (
                        <details>
                          <summary>
                            Part names
                            <span className="explorer-field-reason">
                              The saved name of each part. You do not need it to
                              read this row.
                            </span>
                          </summary>
                          <ul className="explorer-values">
                            {parts.map((part, itemIndex) => (
                              <li key={itemIndex}>{part.raw}</li>
                            ))}
                          </ul>
                        </details>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="explorer-note">
          The dates this collection covers have not been described.
        </p>
      )}
      {scopes.length && scopes.every((scope) => !coverageDates(scope)) ? (
        <p className="explorer-note">
          None of these collections record the dates they cover.
        </p>
      ) : null}
      {limitations.length ? (
        <ul className="explorer-note">
          {limitations.map((limitation, index) => (
            <li key={index}>{plainRecordedNote(String(limitation))}</li>
          ))}
        </ul>
      ) : null}
      {exactNotes.length ? (
        <details>
          <summary>
            Exact saved notes
            <span className="explorer-field-reason">
              The wording saved with this archive. You do not need it to read
              the table.
            </span>
          </summary>
          <ul className="explorer-values">
            {exactNotes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <details>
        <summary>
          When the sources were last checked
          <span className="explorer-field-reason">
            When each source was last looked at, tried, and added here.
          </span>
        </summary>
        <p className="explorer-note">
          The time a source was added here is not the time it was last checked.
          A missing date is not recorded.
        </p>
        <div className="explorer-table-scroll">
          <table className="explorer-table explorer-input-freshness">
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Last checked</th>
                <th scope="col">Last try</th>
                <th scope="col">Added here</th>
              </tr>
            </thead>
            <tbody>
              {[...checks.values()].map(({ input, count }, index) => (
                <tr key={index}>
                  <th scope="row">
                    {sourceName(String(input.provider))}
                    {count > 1 ? (
                      <span className="explorer-row-meta">
                        Same check for {integer(count)} parts
                      </span>
                    ) : null}
                    <span className="explorer-row-meta">
                      {Array.isArray(input.limitations)
                        ? input.limitations
                            .map((item) => plainRecordedNote(String(item)))
                            .filter(Boolean)
                            .join(" ")
                        : ""}
                    </span>
                  </th>
                  <td data-label="Last checked">
                    {input.last_observed_at
                      ? recordedInstant(String(input.last_observed_at))
                      : "Not recorded"}
                  </td>
                  <td data-label="Last try">
                    {enumLabel(input.last_attempt_status) || "Not recorded"}
                    <span className="explorer-row-meta">
                      {input.last_attempt_at
                        ? recordedInstant(String(input.last_attempt_at))
                        : "Date not recorded"}
                    </span>
                  </td>
                  <td data-label="Added here">
                    {input.imported_at
                      ? recordedInstant(String(input.imported_at))
                      : "Not recorded"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function listingColumns(
  view: Exclude<View, "coverage">,
  groupedCommittees: boolean,
  pinnedCongress: boolean,
): readonly (readonly [Navigation["sort"], string, string])[] {
  const record: readonly [Navigation["sort"], string, string] = [
    "record",
    view === "witnesses"
      ? "Recorded name"
      : view === "gaps"
        ? "Known issue"
        : "Record",
    "the record name",
  ];
  const when: readonly [Navigation["sort"], string, string] =
    view === "committees"
      ? ["congress", "Congress", "Congress"]
      : [
          "date",
          view === "witnesses"
            ? pinnedCongress
              ? "Date"
              : "Date / Congress"
            : "Date / status",
          "the recorded date",
        ];
  const detail: readonly [Navigation["sort"], string, string] =
    view === "committees"
      ? [
          "kind",
          groupedCommittees ? "Latest type / level" : "Type / level",
          "committee type",
        ]
      : view === "witnesses"
        ? ["kind", "Position / organization", "position or organization"]
        : view === "gaps"
          ? ["kind", "Category / severity", "issue category and severity"]
          : pinnedCongress
            ? ["kind", "Type", "the recorded type"]
            : ["congress", "Congress / type", "Congress"];
  return [record, when, detail];
}

const VIEW_NOTES: Record<Exclude<View, "coverage">, string> = {
  meetings:
    "Committee meetings, including scheduled, postponed and canceled entries.",
  committees:
    "Browse each committee’s documents, recordings and meetings by Congress.",
  materials:
    "Documents and recordings from collected sources, including items without a matched meeting.",
  witnesses:
    "Witnesses listed by meeting. A listing does not confirm attendance.",
  gaps: "Known collection and matching issues. Coverage shows which material remains unchecked.",
};

const subjectKinds = new Set([
  "meeting",
  "material",
  "appearance",
  "committee_term",
  "source_record",
]);

function useWitnessLines(
  reader: ExplorerReader,
  rows: readonly {
    id: string;
    title?: string | null;
    search_text?: string | null;
  }[],
): ReadonlyMap<string, readonly string[]> {
  const key = rows
    .map((row) => row.id)
    .sort()
    .join("|");
  const [state] = useRequest(
    (signal) =>
      key
        ? reader.listWitnesses(
            rows.map((row) => row.id),
            { signal },
          )
        : Promise.resolve([]),
    [reader, key],
  );
  const lines = new Map<string, readonly string[]>();
  if (state.status === "ready") {
    const names = new Map<string, string[]>();
    for (const witness of state.value)
      names.set(witness.meeting_id, [
        ...(names.get(witness.meeting_id) || []),
        witness.title,
      ]);
    for (const row of rows)
      lines.set(
        row.id,
        witnessNameList(recordedWitnesses(row), names.get(row.id) || []),
      );
  }
  return lines;
}

function useSubjectTitles(
  reader: ExplorerReader,
  rows: readonly { subject_kind?: string | null; subject_id?: string | null }[],
): ReadonlyMap<string, string> {
  const cache = useRef(new Map<string, string>());
  const [, refresh] = useState(0);
  const missing = rows.flatMap((row) => {
    const kind = row.subject_kind || "";
    const id = row.subject_id || "";
    return kind &&
      id &&
      subjectKinds.has(kind) &&
      !cache.current.has(`${kind}/${id}`)
      ? [{ kind, id }]
      : [];
  });
  const key = missing
    .map((ref) => `${ref.kind}/${ref.id}`)
    .sort()
    .join("|");
  const [state] = useRequest(
    (signal) =>
      key ? reader.getRecords(missing, { signal }) : Promise.resolve([]),
    [reader, key],
  );
  useEffect(() => {
    if (state.status !== "ready" || !state.value) return;
    let changed = false;
    state.value.forEach((record, index) => {
      const ref = missing[index];
      if (!ref) return;
      const id = `${ref.kind}/${ref.id}`;
      const title = record ? recordTitle(record) : "";
      if (cache.current.get(id) !== title) {
        cache.current.set(id, title);
        changed = true;
      }
    });
    if (changed) refresh((value) => value + 1);
  }, [state]);
  return cache.current;
}

function RecordedNote({
  text,
  summary,
  reason,
}: {
  text: string;
  summary: string;
  reason: string;
}) {
  const note = recordedTitlePreview(text);
  return (
    <span>
      <span className="explorer-row-meta explorer-recorded-lines">
        {note.preview}
      </span>
      <RemainingNotes
        values={note.rest}
        noun="line"
        reason={reason}
        limit={0}
        plain
        summary={summary}
      />
    </span>
  );
}

function RemainingNotes({
  values,
  noun,
  reason,
  limit,
  label,
  summary,
  plain = false,
}: {
  values: readonly string[];
  noun: string;
  reason: string;
  limit: number;
  label?: string;
  summary?: string;
  plain?: boolean;
}) {
  if (!values.length) return null;
  const rest = values.slice(limit);
  const className = plain
    ? "explorer-row-meta explorer-recorded-lines"
    : "explorer-row-meta explorer-clamp";
  return (
    <>
      {label ? <span className="explorer-row-meta">{label}</span> : null}
      {values.slice(0, limit).map((value, index) => (
        <span className={className} title={value} key={index}>
          {value}
        </span>
      ))}
      {rest.length ? (
        <details className="explorer-row-meta">
          <summary>
            {summary ||
              `${rest.length} more recorded ${rest.length === 1 ? noun : noun.endsWith("s") ? `${noun}es` : `${noun}s`}`}
            <span className="explorer-field-reason">{reason}</span>
          </summary>
          {rest.map((value, index) => (
            <span className={className} title={value} key={index}>
              {value}
            </span>
          ))}
        </details>
      ) : null}
    </>
  );
}

function shownChamber(
  row: { chamber?: string | null },
  coveredBy: readonly string[],
): string {
  if (!row.chamber) return "";
  if (row.chamber === "unknown") return "Chamber not recorded";
  const name = enumLabel(row.chamber);
  return coveredBy.some((text) =>
    text.toLowerCase().includes(name.toLowerCase()),
  )
    ? ""
    : name;
}

function Listing({
  reader,
  query,
  view,
  info,
  nav,
  onSelect,
  onPage,
  onSort,
}: {
  reader: ExplorerReader;
  query: ExplorerQuery;
  view: Exclude<View, "coverage">;
  info: QueryInfo;
  nav: Navigation;
  onSelect: (ref: ExplorerRecordRef) => void;
  onPage: (page: number) => void;
  onSort: (patch: Pick<Navigation, "sort" | "direction">) => void;
}) {
  const key = JSON.stringify(query);
  const [state, retry] = useRequest<QueryResult>(
    (signal) => reader.search(query, { signal }),
    [reader, key],
  );
  const shown = useRef<{ view: typeof view; value: QueryResult } | null>(null);
  if (state.status === "ready") shown.current = { view, value: state.value };
  const visible = shown.current?.view === view ? shown.current.value : null;
  const title = VIEWS.find((item) => item.key === view)!.label;
  const groupedCommittees = view === "committees" && query.congress === "all";
  const subjectTitles = useSubjectTitles(
    reader,
    view === "gaps" && visible ? visible.rows : [],
  );
  const meetingLookups =
    (view === "witnesses" || view === "materials") && visible
      ? visible.rows.flatMap((row) =>
          linkedMeetingIds(row).map((id) => ({
            subject_kind: "meeting",
            subject_id: id,
          })),
        )
      : [];
  const seenMeetings = new Set<string>();
  const meetingRefs = meetingLookups.filter((ref) =>
    seenMeetings.has(ref.subject_id) ? false : seenMeetings.add(ref.subject_id),
  );
  const meetingTitles = useSubjectTitles(reader, meetingRefs);
  const witnessLines = useWitnessLines(
    reader,
    view === "meetings" && visible ? visible.rows : [],
  );
  const noun =
    view === "committees"
      ? visible?.total === 1
        ? "committee"
        : "committees"
      : view === "witnesses"
        ? visible?.total === 1
          ? "appearance"
          : "appearances"
        : visible?.total === 1
          ? "record"
          : "records";
  return (
    <>
      <div className="explorer-subheading">
        <h2>{title}</h2>
        {visible ? (
          <>
            <span
              className="explorer-muted"
              role={state.status === "loading" ? "status" : undefined}
            >
              {state.status === "loading"
                ? "Updating the list"
                : `${integer(visible.total)} ${noun}`}
            </span>
            {state.status === "ready" ? (
              <button
                className="explorer-text-button"
                aria-label="Download the rows shown on this page only"
                onClick={() =>
                  downloadJson(
                    `committee-explorer-${view}-page-${Math.floor(visible.offset / PAGE_SIZE) + 1}.json`,
                    {
                      scope: "selection",
                      publication_id: reader.publication.publication_id,
                      schema_version: reader.publication.schema_version,
                      filters: query,
                      total: visible.total,
                      offset: visible.offset,
                      rows: visible.rows,
                    },
                  )
                }
              >
                Download this page
              </button>
            ) : null}
          </>
        ) : null}
      </div>
      <p className="explorer-note">
        {groupedCommittees
          ? "Each committee appears once. Choose a Congress to see its name, classification and records for that term."
          : VIEW_NOTES[view]}{" "}
        Column headings sort this full selection.{" "}
        {view === "committees"
          ? "A third click restores the original list order."
          : "A third click restores newest recorded date first."}
      </p>
      {state.status === "error" ? (
        <RequestMessage state={state} retry={retry} />
      ) : null}
      {state.status === "loading" && !visible ? (
        <RequestMessage state={state} retry={retry} />
      ) : null}
      {visible?.rows.length ? (
        <>
          <div className="explorer-table-scroll">
            <table
              className="explorer-table explorer-list-table"
              aria-busy={state.status === "loading"}
            >
              <thead>
                <tr>
                  {listingColumns(
                    view,
                    groupedCommittees,
                    query.congress !== "all",
                  ).map(([column, label, reason]) => {
                    const direction = nav.sort === column ? nav.direction : "";
                    const restore =
                      view === "committees"
                        ? "restore the original list order"
                        : "restore newest recorded date first";
                    return (
                      <th
                        key={column}
                        scope="col"
                        aria-sort={
                          direction === "asc"
                            ? "ascending"
                            : direction === "desc"
                              ? "descending"
                              : "none"
                        }
                      >
                        <button
                          type="button"
                          className="explorer-sort"
                          data-direction={direction}
                          onClick={() => onSort(nextSort(nav, column))}
                          aria-label={
                            direction === "asc"
                              ? `Sort by ${reason}, ascending. Activate to sort descending.`
                              : direction === "desc"
                                ? `Sort by ${reason}, descending. Activate to ${restore}.`
                                : `Sort by ${reason}`
                          }
                        >
                          <SortLabel label={label} />
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {visible.rows.map((row, index) => {
                  const meetingIds =
                    view === "witnesses" || view === "materials"
                      ? linkedMeetingIds(row).join("|")
                      : "";
                  const previousMeetingIds =
                    index > 0 && meetingIds
                      ? linkedMeetingIds(visible.rows[index - 1]).join("|")
                      : "";
                  const repeatedMeeting =
                    Boolean(meetingIds) && meetingIds === previousMeetingIds;
                  const filenames =
                    view === "materials" ? recordedFileNames(row.files) : [];
                  const addresses =
                    view === "materials" ? recordedAddressNames(row) : [];
                  const formats =
                    view === "materials" ? recordedFormatNote(row.files) : "";
                  const filename = filenames[0] || "";
                  const action =
                    view === "materials"
                      ? recordedAction(row)
                          .split(" · ")
                          .filter(
                            (part) =>
                              !filename
                                .toLowerCase()
                                .includes(part.toLowerCase()),
                          )
                          .join(" · ")
                      : "";
                  const recordingCode =
                    view === "materials" && !filename
                      ? recordingIdentity(row.recording_url)
                      : "";
                  const recording = recordingCode.startsWith("YouTube ")
                    ? "YouTube"
                    : recordingCode;
                  const provider = providerLabel(row.provider);
                  const shownProvider =
                    provider &&
                    !recording.toLowerCase().includes(provider.toLowerCase())
                      ? provider
                      : "";
                  const parent =
                    view === "committees" && row.parent_committee_id
                      ? info.committee_labels?.[row.parent_committee_id] || ""
                      : "";
                  const label =
                    (view === "materials" && listTitle(row)) ||
                    recordTitle(row);
                  const subjectKey =
                    view === "gaps" && row.subject_kind && row.subject_id
                      ? `${row.subject_kind}/${row.subject_id}`
                      : "";
                  const subjectKnown = Boolean(
                    subjectKey && subjectTitles.has(subjectKey),
                  );
                  const about = subjectKnown
                    ? subjectTitles.get(subjectKey) || ""
                    : "";
                  const absentSubject =
                    subjectKnown && !about
                      ? subjectAbsentNote(row.subject_kind)
                      : "";
                  const unnamedSubject =
                    view === "gaps" && !subjectKnown && !about
                      ? subjectKindLabel(row.subject_kind)
                      : "";
                  const website =
                    view === "committees"
                      ? publicUrl(committeeWebsite(row))
                      : "";
                  const earlierNames =
                    view === "committees"
                      ? earlierCommitteeNames(row.terms, label)
                      : [];
                  const votes = view === "meetings" ? recordedVotes(row) : [];
                  const amendments =
                    view === "meetings" ? recordedAmendments(row) : [];
                  const measures =
                    view === "meetings" ? recordedMeasureValues(row) : [];
                  const recordedNames =
                    view === "meetings" ? recordedWitnesses(row) : "";
                  const witnesses =
                    view === "meetings"
                      ? witnessLines.get(row.id) ||
                        (recordedNames ? [recordedNames] : [])
                      : [];
                  const witnessCount = listedWitnessCount(witnesses.length);
                  const evidenceNotes =
                    view === "meetings"
                      ? listedEvidence(row.evidence_states, {
                          omit: witnesses.length ? ["witnesses"] : [],
                        })
                      : [];
                  const committeeNames = (
                    view === "committees" ? [] : row.committee_ids || []
                  )
                    .map((id) => info.committee_labels?.[id])
                    .filter((name): name is string => Boolean(name));
                  const meetingPlace =
                    view === "meetings" ? recordedPlace(row) : "";
                  const chamberText = shownChamber(row, [
                    ...committeeNames,
                    meetingPlace,
                    view === "committees" ? label : "",
                  ]);
                  const committeeKind =
                    view === "committees"
                      ? ""
                      : [
                          committeeKindNote(row, info.committee_labels),
                          committeeLevelNote(row, info.committee_labels),
                        ]
                          .filter(Boolean)
                          .join(" · ");
                  const roleNote =
                    view === "witnesses" ? notableRoles(row).join(", ") : "";
                  const participation =
                    view === "witnesses" ? participationNote(row) : "";
                  const recordedType =
                    view === "materials" ? documentType(row) : "";
                  const listedType =
                    view === "materials"
                      ? listedDocumentType(recordedType)
                      : "";
                  const category =
                    view === "materials"
                      ? recordedType
                        ? categoryNote(row)
                        : row.category && row.category !== "unknown"
                          ? recordedCategoryLabel(row.category)
                          : ""
                      : "";
                  const vagueDocument =
                    !listedType || listedType === "Document";
                  const materialType =
                    view === "materials"
                      ? (vagueDocument && category ? category : listedType) ||
                        (row.type === "recording" ? "Recording" : "") ||
                        (row.type === "text" ? "Captions or transcript" : "") ||
                        (row.type &&
                        row.type !== "unknown" &&
                        row.type !== "document"
                          ? enumLabel(row.type)
                          : "") ||
                        listedType ||
                        category
                      : "";
                  const materialCategory =
                    view === "materials" &&
                    listedType &&
                    listedType !== "Document"
                      ? categoryNote(row)
                      : "";
                  const materialPart =
                    view === "materials" ? filePartNote(row) : "";
                  const materialSource =
                    view === "materials"
                      ? listedSourcePile(row, recordedType)
                      : "";
                  const history =
                    row.selection === "retained_history" ? (
                      <span className="explorer-row-meta">
                        Saved in an earlier copy. Not in the latest copy.
                      </span>
                    ) : null;
                  const congressText =
                    query.congress !== "all" &&
                    String(row.congress ?? "") === String(query.congress)
                      ? ""
                      : row.congress
                        ? `${row.congress}th Congress`
                        : "Congress not recorded";
                  const meetings =
                    view === "witnesses" || view === "materials"
                      ? linkedMeetingIds(row).flatMap((id) => {
                          const title =
                            meetingTitles.get(`meeting/${id}`) || "";
                          return title && !sameRecordedTitle(title, label)
                            ? [[id, title] as const]
                            : [];
                        })
                      : [];
                  const titlePreview = recordedTitlePreview(label);
                  return (
                    <tr key={`${row.kind}/${row.id}`}>
                      <td
                        className="explorer-title-cell"
                        onClick={(event) => {
                          const target = event.target as HTMLElement | null;
                          if (
                            target?.closest(
                              "a, button, summary, input, select, textarea",
                            )
                          )
                            return;
                          onSelect(row);
                        }}
                      >
                        <button
                          className="explorer-text-button"
                          title={
                            about
                              ? `${label} — ${about}`
                              : absentSubject
                                ? `${label} — ${absentSubject}`
                                : unnamedSubject
                                  ? `${label} — about a ${unnamedSubject}`
                                  : label
                          }
                          aria-label={
                            about
                              ? `Open ${label}, about ${about}`
                              : absentSubject
                                ? `Open ${label}. ${absentSubject}`
                                : unnamedSubject
                                  ? `Open ${label}, about a ${unnamedSubject}`
                                  : `Open ${label}`
                          }
                          onClick={() => onSelect(row)}
                        >
                          {titlePreview.preview}
                        </button>
                        <RemainingNotes
                          values={titlePreview.rest}
                          noun="line"
                          reason="The rest of the title, in the order it was recorded."
                          limit={0}
                          plain
                          summary={
                            titlePreview.continued
                              ? "Rest of the recorded title"
                              : titlePreview.rest.length === 1
                                ? "1 more line of the recorded title"
                                : `${titlePreview.rest.length} more lines of the recorded title`
                          }
                        />
                        {about ? (
                          <RecordedNote
                            text={`About ${about}`}
                            summary="Rest of the subject title"
                            reason="The rest of the title of the record this issue describes."
                          />
                        ) : absentSubject ? (
                          <span className="explorer-row-meta">
                            {absentSubject}
                          </span>
                        ) : unnamedSubject ? (
                          <span className="explorer-row-meta">
                            About a {unnamedSubject}
                          </span>
                        ) : null}
                        {view === "gaps"
                          ? issueNotes(row).map((note, index) => (
                              <RecordedNote
                                text={note}
                                summary="Rest of the issue note"
                                reason="The rest of this issue note, in the order it was recorded."
                                key={index}
                              />
                            ))
                          : null}
                        {view === "gaps" ? (
                          <RemainingNotes
                            values={extraIssueAlternatives(row)}
                            noun="alternative"
                            reason="Other recorded values compared with the selected value."
                            limit={0}
                          />
                        ) : null}
                        {repeatedMeeting
                          ? null
                          : meetings.map(([id, title]) => {
                              const meetingTitle = recordedTitlePreview(title);
                              return (
                                <span key={id}>
                                  <span
                                    className="explorer-row-meta explorer-recorded-lines"
                                    title={title}
                                  >
                                    {meetingTitle.preview}
                                  </span>
                                  <RemainingNotes
                                    values={meetingTitle.rest}
                                    noun="line"
                                    reason="The rest of the meeting title, in the order it was recorded."
                                    limit={0}
                                    plain
                                    summary={
                                      meetingTitle.continued
                                        ? "Rest of the meeting title"
                                        : meetingTitle.rest.length === 1
                                          ? "1 more line of the meeting title"
                                          : `${meetingTitle.rest.length} more lines of the meeting title`
                                    }
                                  />
                                </span>
                              );
                            })}
                        {view === "committees" ? (
                          <RemainingNotes
                            values={earlierNames}
                            noun="name"
                            reason="Names recorded for this committee in another Congress."
                            limit={0}
                            summary={
                              earlierNames.length === 1
                                ? "1 earlier recorded name"
                                : `${earlierNames.length} earlier recorded names`
                            }
                          />
                        ) : null}
                        {view === "committees" && row.explanation ? (
                          <RecordedNote
                            text={row.explanation}
                            summary="Rest of the committee note"
                            reason="The rest of the committee note, in the order it was recorded."
                          />
                        ) : null}
                        {website ? (
                          <a
                            className="explorer-row-meta"
                            href={website}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {website.replace(/^https?:\/\//, "")}
                          </a>
                        ) : null}
                        {filename && filename !== label ? (
                          <span className="explorer-row-meta">{filename}</span>
                        ) : null}
                        {addresses.map((name) => (
                          <span className="explorer-row-meta" key={name}>
                            {name}
                          </span>
                        ))}
                        {filenames.slice(1).map((name) => (
                          <span className="explorer-row-meta" key={name}>
                            {name}
                          </span>
                        ))}
                        {formats ? (
                          <span className="explorer-row-meta">{formats}</span>
                        ) : null}
                        {view === "materials" && landingPageNote(row) ? (
                          <span className="explorer-row-meta">
                            {landingPageNote(row)}
                          </span>
                        ) : null}
                        {action ? (
                          <span className="explorer-row-meta">{action}</span>
                        ) : null}
                        {recording ? (
                          <span
                            className="explorer-row-meta"
                            title={
                              recordingCode !== recording
                                ? recordingCode
                                : undefined
                            }
                          >
                            {recording}
                          </span>
                        ) : null}
                        <span className="explorer-row-meta">
                          {[
                            chamberText,
                            ...committeeNames,
                            committeeKind,
                            view === "meetings" &&
                            row.access &&
                            row.access !== "unknown"
                              ? enumLabel(row.access)
                              : "",
                            shownProvider,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                        {meetingPlace ? (
                          <span className="explorer-row-meta explorer-place">
                            {meetingPlace}
                          </span>
                        ) : null}
                        {witnessCount ? (
                          <span className="explorer-row-meta">
                            {witnessCount}
                          </span>
                        ) : null}
                        {view === "meetings" ? (
                          <RemainingNotes
                            values={measures}
                            noun="measure"
                            reason="Bills, resolutions, treaties, and nominations recorded for this meeting."
                            limit={4}
                          />
                        ) : null}
                        {evidenceNotes.length ? (
                          <span className="explorer-row-meta">
                            {evidenceNotes.join(" · ")}
                          </span>
                        ) : null}
                        {view === "meetings" ? (
                          <RemainingNotes
                            values={votes}
                            noun="vote"
                            reason="Roll-call and voice-vote results recorded for this meeting."
                            limit={2}
                          />
                        ) : null}
                        {view === "meetings" ? (
                          <RemainingNotes
                            values={amendments}
                            noun="amendment"
                            reason="Amendment outcomes recorded for this meeting."
                            limit={2}
                          />
                        ) : null}
                        {view === "materials" && row.explanation ? (
                          <RecordedNote
                            text={row.explanation}
                            summary="Rest of the recorded note"
                            reason="The rest of the note, in the order it was recorded."
                          />
                        ) : null}
                      </td>
                      <td>
                        {view !== "committees"
                          ? keepDate((row.date || "").slice(0, 10)) ||
                            ((view === "materials" || view === "meetings") &&
                            scheduleNote(row) ? null : (
                              <span className="explorer-unknown">
                                Date not recorded
                              </span>
                            ))
                          : null}
                        {view !== "committees" &&
                        (row.date || "").slice(0, 10) &&
                        recordedWhen(row).time ? (
                          <span className="explorer-row-meta">
                            {recordedWhen(row).time}
                          </span>
                        ) : null}
                        {(view === "materials" || view === "meetings") &&
                        scheduleNote(row) ? (
                          <span className="explorer-row-meta">
                            {keepDate(scheduleNote(row))}
                          </span>
                        ) : null}
                        {view === "materials" && publishedNote(row) ? (
                          <span className="explorer-row-meta">
                            {keepDate(publishedNote(row))}
                          </span>
                        ) : null}
                        {view === "materials" && meetingStatusNote(row) ? (
                          <span className="explorer-row-meta">
                            {meetingStatusNote(row)}
                          </span>
                        ) : null}
                        {view === "gaps" && detectedNote(row) ? (
                          <span className="explorer-row-meta explorer-nowrap">
                            {keepDate(detectedNote(row))}
                          </span>
                        ) : null}
                        <span
                          className={
                            view === "committees"
                              ? undefined
                              : "explorer-row-meta"
                          }
                        >
                          {view === "committees" && row.terms ? (
                            <span className="explorer-congress-terms">
                              {row.terms.map((term) => (
                                <button
                                  key={term.id}
                                  className="explorer-text-button"
                                  title={`${term.title} — ${term.congress}th Congress. Open this committee’s term.`}
                                  aria-label={`View ${term.title}, ${term.congress}th Congress`}
                                  onClick={() => onSelect(term)}
                                >
                                  {term.congress}th
                                </button>
                              ))}
                            </span>
                          ) : view === "committees" ? (
                            row.congress ? (
                              <span className="explorer-nowrap">
                                {row.congress}th Congress
                              </span>
                            ) : (
                              "Congress not recorded"
                            )
                          ) : view === "witnesses" ? (
                            congressText ? (
                              <span className="explorer-nowrap">
                                {congressText}
                              </span>
                            ) : null
                          ) : (
                            <>
                              {row.status ? (
                                <span className="explorer-status">
                                  {view === "gaps"
                                    ? issueStatusLabel(row.status) ||
                                      enumLabel(row.status)
                                    : enumLabel(row.status)}
                                </span>
                              ) : null}
                              {listedSourceStatus(row) ? (
                                <span className="explorer-row-meta">
                                  {listedSourceStatus(row)}
                                </span>
                              ) : null}
                            </>
                          )}
                        </span>
                        {row.issue_count ? (
                          <OpenIssues
                            reader={reader}
                            record={row}
                            count={row.issue_count}
                            onSelect={onSelect}
                          />
                        ) : null}
                        {sourceCountNote(row) ? (
                          <span className="explorer-row-meta explorer-nowrap">
                            {sourceCountNote(row)}
                          </span>
                        ) : null}
                      </td>
                      <td>
                        {view === "committees" ? (
                          <>
                            {committeeTypeLabel(row)}
                            <span className="explorer-row-meta">
                              {committeeLevelLabel(row) || "Level not recorded"}
                            </span>
                            {committeeSourceNote(row) ? (
                              <span className="explorer-row-meta">
                                {committeeSourceNote(row)}
                              </span>
                            ) : null}
                            {parent ? (
                              <span className="explorer-row-meta">
                                Subcommittee of {parent}
                              </span>
                            ) : null}
                          </>
                        ) : view === "witnesses" ? (
                          <>
                            {row.position ||
                              row.roles?.map(enumLabel).join(", ") ||
                              "Position not recorded"}
                            {row.organization ? (
                              <span className="explorer-row-meta">
                                {row.organization}
                              </span>
                            ) : null}
                            {witnessNotes(row).map((note) => (
                              <span className="explorer-row-meta" key={note}>
                                {note}
                              </span>
                            ))}
                            {roleNote ? (
                              <span className="explorer-row-meta">
                                {roleNote}
                              </span>
                            ) : null}
                            {participation ? (
                              <span className="explorer-row-meta">
                                {participation}
                              </span>
                            ) : null}
                          </>
                        ) : view === "materials" ? (
                          <>
                            {materialType || "Type not recorded"}
                            {materialCategory ? (
                              <span className="explorer-row-meta">
                                {materialCategory}
                              </span>
                            ) : null}
                            {materialPart ? (
                              <span className="explorer-row-meta">
                                {materialPart}
                              </span>
                            ) : null}
                            {materialSource ? (
                              <span className="explorer-row-meta">
                                {materialSource}
                              </span>
                            ) : null}
                            {congressText ? (
                              <span className="explorer-row-meta">
                                {congressText}
                              </span>
                            ) : null}
                            {history}
                          </>
                        ) : view === "gaps" ? (
                          <>
                            {enumLabel(row.category) ||
                              enumLabel(row.type) ||
                              "Category not recorded"}
                            {row.severity ? (
                              <span className="explorer-row-meta">
                                {severityLabel(row.severity)}
                              </span>
                            ) : null}
                            {congressText ? (
                              <span className="explorer-row-meta">
                                {congressText}
                              </span>
                            ) : null}
                            {history}
                          </>
                        ) : (
                          <>
                            {congressText}
                            <span className="explorer-row-meta">
                              {[
                                documentType(row) ||
                                  [row.type, row.category]
                                    .filter(
                                      (value, index, list) =>
                                        value &&
                                        value !== "unknown" &&
                                        list.indexOf(value) === index,
                                    )
                                    .map(enumLabel)
                                    .join(" · "),
                                documentSourceLabel(row),
                              ]
                                .filter(Boolean)
                                .join(" · ")}
                            </span>
                            {history}
                            {view === "meetings" && sourceTypeNote(row) ? (
                              <span className="explorer-row-meta">
                                {sourceTypeNote(row)}
                              </span>
                            ) : null}
                          </>
                        )}{" "}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination
            total={visible.total}
            offset={visible.offset}
            count={visible.rows.length}
            onPage={onPage}
          />
        </>
      ) : state.status === "ready" ? (
        <div className="explorer-alert">
          <p>
            {state.value.total
              ? "This page is beyond the available results. Return to the first page to continue."
              : "No records match this selection. Broaden the filters. Records may still exist at the source."}
          </p>
          {query.offset ? (
            <button
              className="explorer-button"
              aria-label="This page is past the last result. Return to the first page."
              onClick={() => onPage(0)}
            >
              Return to first page
            </button>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

function CoverageView({
  reader,
  query,
  onDrill,
  measure,
  grouping,
  onSettings,
}: {
  reader: ExplorerReader;
  query: ExplorerQuery;
  onDrill: (query: ExplorerQuery) => void;
  measure: Navigation["measure"];
  grouping: Navigation["grouping"];
  onSettings: (patch: Partial<Navigation>) => void;
}) {
  const key = JSON.stringify(query);
  const [state, retry] = useRequest<CoverageSummary>(
    (signal) => reader.getCoverage({ filters: query, signal }),
    [reader, key],
  );
  const shown = useRef<CoverageSummary | null>(null);
  if (state.status === "ready") shown.current = state.value;
  const summary = state.status === "ready" ? state.value : shown.current;
  return summary ? (
    <>
      {state.status === "loading" ? (
        <p className="explorer-note" role="status">
          Updating coverage.
        </p>
      ) : null}
      {state.status === "error" ? (
        <RequestMessage
          state={state}
          retry={retry}
          noun="coverage for this selection"
        />
      ) : null}
      <Coverage
        summary={summary}
        onDrill={onDrill}
        aspect={measure}
        grouping={grouping}
        onAspect={(measure) => onSettings({ measure })}
        onGrouping={(grouping) => onSettings({ grouping })}
      />
    </>
  ) : (
    <RequestMessage
      state={state.status === "ready" ? { status: "loading" } : state}
      retry={retry}
      noun="coverage for this selection"
    />
  );
}

function NamedMeeting({
  reader,
  meetingId,
  onSelect,
}: {
  reader: ExplorerReader;
  meetingId: string;
  onSelect: (ref: ExplorerRecordRef) => void;
}) {
  const [state] = useRequest(
    (signal) =>
      reader.getRecord({ kind: "meeting", id: meetingId }, { signal }),
    [reader, meetingId],
  );
  const title =
    state.status === "ready" && state.value ? recordTitle(state.value) : "";
  return (
    <section className="explorer-fact-group">
      <h3>Meeting</h3>
      <p>
        <button
          className="explorer-text-button"
          aria-label={
            title
              ? `Open the meeting ${title}`
              : "Open the meeting this record belongs to"
          }
          onClick={() => onSelect({ kind: "meeting", id: meetingId })}
        >
          {title || "Open the meeting"} <ForwardIcon />
        </button>
      </p>
    </section>
  );
}

function IssueSubject({
  reader,
  record,
  onSelect,
}: {
  reader: ExplorerReader;
  record: DetailRecord;
  onSelect: (ref: ExplorerRecordRef) => void;
}) {
  const row = fields(record);
  const affected = [
    "meeting",
    "material",
    "appearance",
    "committee_term",
    "source_record",
  ].includes(String(row.subject_kind))
    ? { kind: String(row.subject_kind), id: String(row.subject_id) }
    : row.meeting_id
      ? { kind: "meeting", id: String(row.meeting_id) }
      : null;
  const [state] = useRequest(
    (signal) =>
      affected
        ? reader.getRecord(affected, { signal })
        : Promise.resolve(undefined),
    [reader, affected?.kind, affected?.id],
  );
  if (!affected) return null;
  const title =
    state.status === "ready" && state.value ? recordTitle(state.value) : "";
  return (
    <section className="explorer-fact-group">
      <h3>About this issue</h3>
      <p>
        <button
          className="explorer-text-button"
          aria-label={
            title
              ? `Open ${title}. This is the record the issue describes.`
              : "Open the record this issue describes"
          }
          onClick={() => onSelect(affected)}
        >
          {title || "Open the record"} <ForwardIcon />
        </button>
      </p>
    </section>
  );
}

function Inspector({
  reader,
  selected,
  onSelect,
  committeeLabels,
  onClose,
}: {
  reader: ExplorerReader;
  selected: ExplorerRecordRef;
  onSelect: (ref: ExplorerRecordRef) => void;
  committeeLabels?: Readonly<Record<string, string>>;
  onClose: () => void;
}) {
  const [state, retry] = useRequest<DetailRecord | undefined>(
    (signal) => reader.getRecord(selected, { signal }),
    [reader, selected.kind, selected.id],
  );
  return (
    <article className="explorer-detail">
      <div className="explorer-subheading">
        <button
          className="explorer-text-button"
          aria-label="Back to the list. Filters stay as they are."
          onClick={onClose}
        >
          <BackIcon /> Results
        </button>
        {state.status === "ready" && state.value ? (
          <button
            className="explorer-text-button"
            aria-label="Download a copy of everything saved for this record"
            onClick={() =>
              downloadJson(
                `committee-explorer-${selected.kind}-${selected.id}.json`,
                {
                  scope: "record",
                  publication_id: reader.publication.publication_id,
                  schema_version: reader.publication.schema_version,
                  record: state.value,
                },
              )
            }
          >
            Download this record
          </button>
        ) : null}
      </div>
      {state.status !== "ready" ? (
        <RequestMessage state={state} retry={retry} noun="record details" />
      ) : state.value ? (
        <>
          <RecordDetail
            record={state.value}
            onSelect={onSelect}
            committeeLabels={committeeLabels}
            affectedAction={
              state.value.kind === "data_issue" ? (
                <IssueSubject
                  reader={reader}
                  record={state.value}
                  onSelect={onSelect}
                />
              ) : undefined
            }
            meetingAction={
              fields(state.value).meeting_id &&
              !["meeting", "material", "data_issue"].includes(
                state.value.kind,
              ) ? (
                <NamedMeeting
                  reader={reader}
                  meetingId={String(fields(state.value).meeting_id)}
                  onSelect={onSelect}
                />
              ) : undefined
            }
            sourceEvidence={
              <SourceEvidence reader={reader} record={state.value} />
            }
          />
          <Related
            key={`${selected.kind}/${selected.id}`}
            reader={reader}
            selected={selected}
            contextTitle={
              state.value.kind === "committee_term"
                ? recordTitle(state.value)
                : ""
            }
            contextCongress={
              state.value.kind === "committee_term"
                ? fields(state.value).congress
                : ""
            }
            contextChamber={
              state.value.kind === "committee_term"
                ? fields(state.value).chamber
                : ""
            }
            contextWhen={
              state.value.kind === "meeting"
                ? listedWhen(fields(state.value))
                : ""
            }
            onSelect={onSelect}
          />
        </>
      ) : (
        <p className="explorer-alert">
          This record is not in the archive you are viewing. It may still exist
          at the original source.
        </p>
      )}
    </article>
  );
}

function SourceEvidence({
  reader,
  record,
}: {
  reader: ExplorerReader;
  record: DetailRecord;
}) {
  const [open, setOpen] = useState(false);
  const ids = fields(record).source_ids;
  if (!Array.isArray(ids) || !ids.length) return null;
  return (
    <details
      className="explorer-detail-section"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        Source evidence ({ids.length})
        <span className="explorer-field-reason">
          The original pages this record was built from.
        </span>
      </summary>
      {open ? (
        <SourceRecords
          reader={reader}
          ids={ids.map(String)}
          focusName={record.kind === "appearance" ? recordTitle(record) : ""}
        />
      ) : null}
    </details>
  );
}

function FactValue({ label, value }: { label: string; value: string }) {
  const lines = value.split("\n");
  const proseName =
    label === "Description"
      ? "description"
      : label === "Match note"
        ? "match note"
        : label === "Explanation"
          ? "explanation"
          : label === "Note"
            ? "note"
            : "";
  if (!proseName)
    return (
      <>
        {lines.map((line, lineIndex) => (
          <span key={lineIndex}>{line}</span>
        ))}
      </>
    );
  const note = recordedTitlePreview(value);
  const name = proseName;
  return (
    <>
      <span>{note.preview}</span>
      {note.rest.length ? (
        <details>
          <summary>
            Rest of the {name}
            <span className="explorer-field-reason">
              The rest of the recorded {name}.
            </span>
          </summary>
          {note.rest.map((line, lineIndex) => (
            <span key={lineIndex}>{line}</span>
          ))}
        </details>
      ) : null}
    </>
  );
}

function sourceFocus(name: string): string {
  return (
    name
      .replace(/^(?:honorable|hon|mr|ms|mrs|dr|miss)\.?\s+/i, "")
      .trim()
      .split(/\s+/)
      .at(-1)
      ?.toLowerCase() || ""
  );
}

function SourceRecords({
  reader,
  ids,
  focusName = "",
}: {
  reader: ExplorerReader;
  ids: string[];
  focusName?: string;
}) {
  const [state, retry] = useRequest(
    (signal) =>
      reader.getRecords(
        ids.map((id) => ({ kind: "source_record", id })),
        { signal },
      ),
    [reader, ids.join(",")],
  );
  if (state.status !== "ready")
    return (
      <RequestMessage state={state} retry={retry} noun="source evidence" />
    );
  const focus = sourceFocus(focusName);
  return (
    <>
      {state.value.map((source, index) => {
        if (!source)
          return (
            <p className="explorer-note" key={ids[index]}>
              This source is not in the archive.
            </p>
          );
        const url = publicUrl(sourcePageUrl(fields(source).url));
        const facts = sourceFacts(source);
        const recorded = sourceLinks(source);
        const links =
          focus.length >= 3
            ? [...recorded.links].sort(
                (left, right) =>
                  Number(
                    `${right.label} ${right.href}`
                      .toLowerCase()
                      .includes(focus),
                  ) -
                  Number(
                    `${left.label} ${left.href}`.toLowerCase().includes(focus),
                  ),
              )
            : recorded.links;
        return (
          <div key={source.id}>
            <div className="explorer-subheading">
              <h4>
                Source {index + 1}: {recordTitle(source)}
              </h4>
              {url ? (
                <a href={url} target="_blank" rel="noreferrer">
                  Open original source <ExternalIcon />
                </a>
              ) : null}
            </div>
            {facts.length ? (
              <dl className="explorer-facts">
                {facts.map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>
                      <FactValue label={label} value={value} />
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}
            <SourceLinkGroups links={links} />
            <SourcePayload source={source} />
          </div>
        );
      })}
    </>
  );
}

function SourcePayload({ source }: { source: object }) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        See the saved source
        <span className="explorer-field-reason">
          The complete saved source, in a technical format. You do not need it
          to read this page.
        </span>
      </summary>
      {open ? (
        <pre>
          <code>{JSON.stringify(source, null, 2)}</code>
        </pre>
      ) : null}
    </details>
  );
}

function Related({
  reader,
  selected,
  onSelect,
  contextTitle = "",
  contextCongress = "",
  contextChamber = "",
  contextWhen = "",
}: {
  reader: ExplorerReader;
  selected: ExplorerRecordRef;
  onSelect: (ref: ExplorerRecordRef) => void;
  contextTitle?: string;
  contextCongress?: unknown;
  contextChamber?: unknown;
  contextWhen?: string;
}) {
  const sections: Record<string, string[]> = {
    meeting: ["material", "appearance", "data_issue"],
    appearance: ["material", "data_issue"],
    material: ["meeting", "appearance", "data_issue"],
    committee_term: ["committee_term", "material", "meeting", "data_issue"],
  };
  return (
    <div className="explorer-related">
      {(sections[selected.kind] || []).map((kind) =>
        kind === "material" ? (
          <RelatedMaterials
            key={kind}
            reader={reader}
            selected={selected}
            contextTitle={contextTitle}
            contextWhen={contextWhen}
            onSelect={onSelect}
          />
        ) : (
          <RelatedSection
            key={kind}
            kind={kind}
            reader={reader}
            selected={selected}
            contextTitle={contextTitle}
            contextCongress={contextCongress}
            contextChamber={contextChamber}
            contextWhen={contextWhen}
            onSelect={onSelect}
          />
        ),
      )}
    </div>
  );
}

function RelatedSection({
  reader,
  selected,
  onSelect,
  kind,
  contextTitle = "",
  contextCongress = "",
  contextChamber = "",
  contextWhen = "",
}: {
  reader: ExplorerReader;
  selected: ExplorerRecordRef;
  onSelect: (ref: ExplorerRecordRef) => void;
  kind: string;
  contextTitle?: string;
  contextCongress?: unknown;
  contextChamber?: unknown;
  contextWhen?: string;
}) {
  const [page, setPage] = useState(0);
  const [state, retry] = useRequest(
    (signal) =>
      reader.getRelated(selected, {
        kind,
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        signal,
      }),
    [reader, selected.kind, selected.id, kind, page],
  );
  const identity = `${selected.kind}/${selected.id}/${kind}`;
  const shown = useRef<{ identity: string; value: RelatedResult } | null>(null);
  if (state.status === "ready")
    shown.current = { identity, value: state.value };
  const visible =
    shown.current?.identity === identity ? shown.current.value : null;
  const labels: Record<string, string> = {
    material: "Documents & recordings",
    appearance: "Witnesses",
    meeting: "Meetings",
    committee_term: "Subcommittees",
    data_issue: "Known issues",
  };
  const witnessLines = useWitnessLines(
    reader,
    kind === "meeting" && visible ? visible.records : [],
  );
  if (!visible)
    return state.status !== "ready" ? (
      <RequestMessage
        state={state}
        retry={retry}
        noun={labels[kind].toLowerCase()}
      />
    ) : null;
  if (!visible.records.length) return null;
  return (
    <section
      className="explorer-detail-section"
      aria-busy={state.status === "loading"}
    >
      {state.status === "error" ? (
        <RequestMessage
          state={state}
          retry={retry}
          noun={labels[kind].toLowerCase()}
        />
      ) : null}
      <h3>
        {labels[kind]}{" "}
        <span
          className="explorer-muted"
          role={state.status === "loading" ? "status" : undefined}
        >
          {state.status === "loading"
            ? "Updating"
            : `(${integer(visible.total)})`}
        </span>
      </h3>
      <ul className="explorer-related-list">
        {visible.records.map((record) => {
          const row = fields(record);
          const parts = omitRepeatedWhen(
            omitRepeatedChamber(
              omitRepeatedCongress(relatedParts(kind, row), contextCongress),
              contextChamber,
            ),
            contextWhen,
          )
            .map((part) =>
              contextTitle &&
              kind === "committee_term" &&
              part.text.endsWith(", like the parent committee")
                ? {
                    ...part,
                    text: part.text.slice(
                      0,
                      -", like the parent committee".length,
                    ),
                  }
                : part,
            )
            .filter((part) => part.text);
          const measures = kind === "meeting" ? recordedMeasureValues(row) : [];
          const votes = kind === "meeting" ? recordedVotes(row) : [];
          const amendments = kind === "meeting" ? recordedAmendments(row) : [];
          const alternatives =
            kind === "data_issue" ? extraIssueAlternatives(row) : [];
          const loadedWitnesses =
            kind === "meeting" ? witnessLines.get(record.id) : undefined;
          const witnessNames =
            kind === "meeting"
              ? loadedWitnesses ||
                (recordedWitnesses(row) ? [recordedWitnesses(row)] : [])
              : [];
          const witnessCount = listedWitnessCount(witnessNames.length);
          const title =
            kind === "meeting" || kind === "committee_term"
              ? titleInContext(recordTitle(record), contextTitle)
              : recordTitle(record);
          const titlePreview = recordedTitlePreview(title);
          return (
            <li key={record.id}>
              <button
                className="explorer-text-button"
                aria-label={`Open ${title}`}
                onClick={() => onSelect(record)}
              >
                {titlePreview.preview}
              </button>
              <RemainingNotes
                values={titlePreview.rest}
                noun="line"
                reason="The rest of the title, in the order it was recorded."
                limit={0}
                plain
                summary={
                  titlePreview.continued
                    ? "Rest of the recorded title"
                    : titlePreview.rest.length === 1
                      ? "1 more line of the recorded title"
                      : `${titlePreview.rest.length} more lines of the recorded title`
                }
              />
              {parts.length ? (
                <span className="explorer-evidence">
                  {parts.map((part, index) => (
                    <span
                      key={`${part.role || "fact"}-${index}`}
                      className={
                        part.role === "place"
                          ? "explorer-place"
                          : part.role === "status"
                            ? "explorer-status"
                            : part.role === "note"
                              ? "explorer-issue-note"
                              : undefined
                      }
                    >
                      {part.text}
                    </span>
                  ))}
                </span>
              ) : null}
              {typeof row.issue_count === "number" && row.issue_count > 0 ? (
                <OpenIssues
                  reader={reader}
                  record={record}
                  count={row.issue_count}
                  onSelect={onSelect}
                />
              ) : null}
              {witnessCount ? (
                <span className="explorer-row-meta">{witnessCount}</span>
              ) : null}
              <RemainingNotes
                values={measures}
                noun="measure"
                reason="Bills, resolutions, treaties, and nominations recorded for this meeting."
                limit={4}
              />
              <RemainingNotes
                values={votes}
                noun="vote"
                reason="Roll-call and voice-vote results recorded for this meeting."
                limit={2}
              />
              <RemainingNotes
                values={amendments}
                noun="amendment"
                reason="Amendment outcomes recorded for this meeting."
                limit={2}
              />
              <RemainingNotes
                values={alternatives}
                noun="alternative"
                reason="Other recorded values compared with the selected value."
                limit={0}
              />
            </li>
          );
        })}
      </ul>
      {visible.total > PAGE_SIZE ? (
        <Pagination
          total={visible.total}
          offset={visible.offset}
          count={visible.records.length}
          onPage={setPage}
        />
      ) : null}
    </section>
  );
}
