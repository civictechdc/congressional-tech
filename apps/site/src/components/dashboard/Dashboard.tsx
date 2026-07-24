import { useEffect, useMemo, useState } from 'react';
import congressMetadata from '../../data/congress_metadata.json';
import {
  formatInt,
  groupBy,
  ordinal,
  pct,
  sumTotals,
  toReportRows,
  type CongressInfo,
  type ReportRow,
} from './data';

/**
 * The one client island on the site: loads the committee YouTube coverage
 * report (CSV) and renders filterable, hand-rolled SVG/HTML charts styled
 * with the ctdc tokens. Coverage entity colors are fixed everywhere:
 * "has Event ID" = primary blue, "missing" = amber gold.
 */

const COLOR_WITH = '#104378'; // --ctdc-primary
const COLOR_MISSING = '#eec05e'; // --ctdc-gold

const METADATA = congressMetadata as Record<string, CongressInfo>;

const titleCase = (value: string) =>
  value.length === 0 ? value : value[0].toUpperCase() + value.slice(1);

interface Filters {
  congress: string;
  chamber: string;
  control: string;
}

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; rows: ReportRow[] };

export default function Dashboard() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [filters, setFilters] = useState<Filters>({
    congress: 'all',
    chamber: 'all',
    control: 'all',
  });

  useEffect(() => {
    const url = `${import.meta.env.BASE_URL.replace(/\/+$/, '')}/data/youtube/youtube_event_id_report.csv`;
    let cancelled = false;
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      })
      .then((text) => {
        if (!cancelled) setState({ status: 'ready', rows: toReportRows(text) });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setState({
            status: 'error',
            message: err instanceof Error ? err.message : String(err),
          });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const allRows = state.status === 'ready' ? state.rows : [];

  const options = useMemo(
    () => ({
      congresses: [...new Set(allRows.map((r) => r.congress))].sort(
        (a, b) => b - a,
      ),
      chambers: [...new Set(allRows.map((r) => r.chamber))].sort(),
      controls: [...new Set(allRows.map((r) => r.control))].sort(),
    }),
    [allRows],
  );

  const matches = (r: ReportRow, f: Filters) =>
    (f.congress === 'all' || String(r.congress) === f.congress) &&
    (f.chamber === 'all' || r.chamber === f.chamber) &&
    (f.control === 'all' || r.control === f.control);

  const rows = useMemo(
    () => allRows.filter((r) => matches(r, filters)),
    [allRows, filters],
  );

  /**
   * Cooperative filters: an option is disabled when combining it with the
   * other current selections would yield zero videos (e.g. a Republican-
   * control congress while "Democratic" is selected, or a pre-YouTube
   * congress). Prevents dead-end combinations instead of failing silently.
   */
  const isDead = (patch: Partial<Filters>) => {
    const candidate = { ...filters, ...patch };
    return !allRows.some((r) => r.totalVideos > 0 && matches(r, candidate));
  };

  if (state.status === 'loading') {
    return <p className="dash-status">Loading the coverage report…</p>;
  }
  if (state.status === 'error') {
    return (
      <p className="dash-status" role="alert">
        Could not load the coverage report ({state.message}). The raw CSV lives
        at <code>public/data/youtube/youtube_event_id_report.csv</code> in the
        repo.
      </p>
    );
  }

  const totals = sumTotals(rows);
  const set = (patch: Partial<Filters>) =>
    setFilters((prev) => ({ ...prev, ...patch }));

  return (
    <div className="dash">
      {/* One filter row above the charts; filters scope everything below. */}
      <form className="dash-filters" aria-label="Filter the report">
        <label className="dash-filter">
          <span className="dash-filter-label">Congress</span>
          <select
            value={filters.congress}
            onChange={(e) => set({ congress: e.target.value })}
          >
            <option value="all">All congresses</option>
            {options.congresses.map((congress) => {
              const meta = METADATA[String(congress)];
              const years = meta
                ? ` (${meta.start.slice(0, 4)}–${meta.end.slice(0, 4)})`
                : '';
              return (
                <option
                  key={congress}
                  value={String(congress)}
                  disabled={isDead({ congress: String(congress) })}
                >
                  {ordinal(congress)}
                  {years}
                </option>
              );
            })}
          </select>
        </label>
        <label className="dash-filter">
          <span className="dash-filter-label">Chamber</span>
          <select
            value={filters.chamber}
            onChange={(e) => set({ chamber: e.target.value })}
          >
            <option value="all">All chambers</option>
            {options.chambers.map((chamber) => (
              <option
                key={chamber}
                value={chamber}
                disabled={isDead({ chamber })}
              >
                {titleCase(chamber)}
              </option>
            ))}
          </select>
        </label>
        <label className="dash-filter">
          <span className="dash-filter-label">Party control</span>
          <select
            value={filters.control}
            onChange={(e) => set({ control: e.target.value })}
          >
            <option value="all">All parties</option>
            {options.controls.map((control) => (
              <option
                key={control}
                value={control}
                disabled={isDead({ control })}
              >
                {control}
              </option>
            ))}
          </select>
        </label>
      </form>

      {/* KPI row */}
      <div className="dash-kpis">
        <StatTile label="Total videos" value={totals.total} />
        <StatTile label="With an Event ID" value={totals.withId} />
        <StatTile label="Missing an Event ID" value={totals.missing} />
      </div>

      {rows.length === 0 ? (
        <div className="dash-empty">
          <p className="dash-status">
            No videos match that combination of filters.
          </p>
          <button
            type="button"
            className="dash-reset"
            onClick={() =>
              setFilters({ congress: 'all', chamber: 'all', control: 'all' })
            }
          >
            Reset filters
          </button>
        </div>
      ) : (
        <>
          <div className="dash-grid">
            <section className="dash-card" aria-label="Event ID coverage">
              <h3 className="dash-card-title">Event ID coverage</h3>
              <p className="dash-card-sub">
                Share of committee videos whose descriptions include the
                official Event ID linking them to Congress.gov.
              </p>
              <CoverageDonut withId={totals.withId} missing={totals.missing} />
            </section>
            <section
              className="dash-card"
              aria-label="Coverage by congress and party control"
            >
              <h3 className="dash-card-title">By congress</h3>
              <p className="dash-card-sub">
                Videos per congress, split by Event ID coverage. Letters mark
                the chamber's party control (D/R).
              </p>
              <CongressColumns rows={rows} />
            </section>
          </div>
          <section className="dash-card" aria-label="Committee leaderboard">
            <h3 className="dash-card-title">Committee leaderboard</h3>
            <p className="dash-card-sub">
              Committees ranked by uploaded videos across the selected slice.
            </p>
            <Leaderboard rows={rows} />
          </section>
        </>
      )}
    </div>
  );
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="dash-stat">
      <span className="dash-stat-label">{label}</span>
      <span className="dash-stat-value">{formatInt.format(value)}</span>
    </div>
  );
}

function Legend() {
  return (
    <ul className="dash-legend">
      <li>
        <span className="dash-swatch" style={{ background: COLOR_WITH }} />
        Has Event ID
      </li>
      <li>
        <span className="dash-swatch" style={{ background: COLOR_MISSING }} />
        Missing Event ID
      </li>
    </ul>
  );
}

/** Two-slice coverage donut with a hero % in the middle (inline SVG). */
function CoverageDonut({ withId, missing }: { withId: number; missing: number }) {
  const total = withId + missing;
  const coverage = pct(withId, total);
  const size = 200;
  const radius = 78;
  const strokeWidth = 26;
  const c = 2 * Math.PI * radius;
  const gap = total > 0 && withId > 0 && missing > 0 ? 3 : 0; // 2px-ish surface gap
  const withLen = Math.max((withId / (total || 1)) * c - gap, 0);
  const missLen = Math.max((missing / (total || 1)) * c - gap, 0);

  const circleProps = {
    cx: size / 2,
    cy: size / 2,
    r: radius,
    fill: 'none' as const,
    strokeWidth,
  };

  return (
    <div className="dash-donut">
      <svg
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`${coverage.toFixed(1)} percent of ${formatInt.format(total)} videos include an Event ID`}
      >
        {/* track */}
        <circle {...circleProps} stroke="rgba(11, 26, 48, 0.06)" />
        {withLen > 0 && (
          <circle
            {...circleProps}
            stroke={COLOR_WITH}
            strokeDasharray={`${withLen} ${c - withLen}`}
            strokeDashoffset={c / 4}
          >
            <title>{`Has Event ID: ${formatInt.format(withId)} videos`}</title>
          </circle>
        )}
        {missLen > 0 && (
          <circle
            {...circleProps}
            stroke={COLOR_MISSING}
            strokeDasharray={`${missLen} ${c - missLen}`}
            strokeDashoffset={c / 4 - withLen - gap}
          >
            <title>{`Missing Event ID: ${formatInt.format(missing)} videos`}</title>
          </circle>
        )}
        <text
          x={size / 2}
          y={size / 2 - 4}
          textAnchor="middle"
          className="dash-donut-hero"
        >
          {total === 0 ? '—' : `${Math.round(coverage)}%`}
        </text>
        <text
          x={size / 2}
          y={size / 2 + 22}
          textAnchor="middle"
          className="dash-donut-sub"
        >
          have Event IDs
        </text>
      </svg>
      <div className="dash-donut-side">
        <Legend />
        <dl className="dash-donut-figures">
          <div>
            <dt>Has Event ID</dt>
            <dd>{formatInt.format(withId)}</dd>
          </div>
          <div>
            <dt>Missing</dt>
            <dd>{formatInt.format(missing)}</dd>
          </div>
          <div>
            <dt>Total</dt>
            <dd>{formatInt.format(withId + missing)}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}

/** Committee leaderboard: horizontal stacked bars, values always visible. */
function Leaderboard({ rows }: { rows: ReportRow[] }) {
  const committees = [...groupBy(rows, (r) => r.committee)]
    .map(([committee, group]) => ({ committee, ...sumTotals(group) }))
    .filter((entry) => entry.total > 0)
    .sort((a, b) => b.total - a.total)
    .slice(0, 12);
  const max = committees[0]?.total ?? 0;

  if (committees.length === 0) {
    return <p className="dash-status">No videos in this slice.</p>;
  }

  return (
    <div>
      <Legend />
      <ol className="dash-board">
        {committees.map((entry) => (
          <li key={entry.committee} className="dash-board-row">
            <span className="dash-board-name" title={entry.committee}>
              {entry.committee}
            </span>
            <span className="dash-board-bar" aria-hidden="true">
              {entry.withId > 0 && (
                <span
                  className="dash-board-seg"
                  style={{
                    width: `${pct(entry.withId, max)}%`,
                    background: COLOR_WITH,
                  }}
                  title={`Has Event ID: ${formatInt.format(entry.withId)}`}
                />
              )}
              {entry.missing > 0 && (
                <span
                  className="dash-board-seg"
                  style={{
                    width: `${pct(entry.missing, max)}%`,
                    background: COLOR_MISSING,
                  }}
                  title={`Missing Event ID: ${formatInt.format(entry.missing)}`}
                />
              )}
            </span>
            <span className="dash-board-value">
              {formatInt.format(entry.total)}
              <small>{Math.round(pct(entry.withId, entry.total))}% tagged</small>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Stacked columns per congress (inline SVG) + a table view fallback. */
function CongressColumns({ rows }: { rows: ReportRow[] }) {
  const congresses = [...groupBy(rows, (r) => r.congress)]
    .map(([congress, group]) => ({
      congress,
      ...sumTotals(group),
      controls: [...new Set(group.map((r) => r.control))],
      chambers: [...new Set(group.map((r) => r.chamber))],
    }))
    .sort((a, b) => a.congress - b.congress);

  const width = 640;
  const height = 260;
  const margin = { top: 12, right: 8, bottom: 44, left: 56 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  const max = Math.max(...congresses.map((c) => c.total), 1);
  // Clean tick step: 1/2/5 × 10^n covering max in <= 4 steps.
  const rawStep = max / 4;
  const pow = 10 ** Math.floor(Math.log10(rawStep));
  const step =
    [1, 2, 5, 10].map((m) => m * pow).find((s) => s * 4 >= max) ?? pow * 10;
  const ticks = Array.from(
    { length: Math.floor(max / step) + 1 },
    (_, i) => i * step,
  );
  const yFor = (value: number) => margin.top + plotH - (value / max) * plotH;
  const band = plotW / Math.max(congresses.length, 1);
  const barW = Math.min(band * 0.6, 24);

  return (
    <div>
      <Legend />
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Stacked columns of videos per congress, split by Event ID coverage"
        className="dash-columns"
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={margin.left}
              x2={width - margin.right}
              y1={yFor(tick)}
              y2={yFor(tick)}
              stroke="rgba(11, 26, 48, 0.08)"
              strokeWidth="1"
            />
            <text
              x={margin.left - 8}
              y={yFor(tick) + 4}
              textAnchor="end"
              className="dash-axis-text"
            >
              {formatInt.format(tick)}
            </text>
          </g>
        ))}
        {congresses.map((entry, i) => {
          const x = margin.left + band * i + (band - barW) / 2;
          const gapPx = entry.withId > 0 && entry.missing > 0 ? 2 : 0;
          const withTop = yFor(entry.withId);
          const missH = Math.max(
            (entry.missing / max) * plotH - gapPx,
            entry.missing > 0 ? 1 : 0,
          );
          const label = `${ordinal(entry.congress)} Congress — has ID ${formatInt.format(entry.withId)}, missing ${formatInt.format(entry.missing)}`;
          return (
            <g key={entry.congress}>
              {entry.withId > 0 && (
                <rect
                  x={x}
                  y={withTop}
                  width={barW}
                  height={Math.max(margin.top + plotH - withTop, 1)}
                  fill={COLOR_WITH}
                >
                  <title>{label}</title>
                </rect>
              )}
              {entry.missing > 0 && (
                <rect
                  x={x}
                  y={withTop - gapPx - missH}
                  width={barW}
                  height={missH}
                  rx="4"
                  fill={COLOR_MISSING}
                >
                  <title>{label}</title>
                </rect>
              )}
              <text
                x={x + barW / 2}
                y={height - 26}
                textAnchor="middle"
                className="dash-axis-text"
              >
                {entry.congress}
              </text>
              <text
                x={x + barW / 2}
                y={height - 10}
                textAnchor="middle"
                className="dash-axis-sub"
              >
                {entry.controls
                  .map((control) => (control === 'Democratic' ? 'D' : 'R'))
                  .join('/')}
              </text>
            </g>
          );
        })}
        <line
          x1={margin.left}
          x2={width - margin.right}
          y1={margin.top + plotH}
          y2={margin.top + plotH}
          stroke="rgba(11, 26, 48, 0.25)"
          strokeWidth="1"
        />
      </svg>
      <details className="dash-table-details">
        <summary>View as table</summary>
        <div className="dash-table-wrap">
          <table className="dash-table">
          <thead>
            <tr>
              <th scope="col">Congress</th>
              <th scope="col">Control</th>
              <th scope="col" className="num">
                Has Event ID
              </th>
              <th scope="col" className="num">
                Missing
              </th>
              <th scope="col" className="num">
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {congresses.map((entry) => (
              <tr key={entry.congress}>
                <th scope="row">{ordinal(entry.congress)}</th>
                <td>
                  {entry.chambers
                    .map((chamber) => {
                      const meta = METADATA[String(entry.congress)];
                      const control =
                        chamber === 'senate' ? meta?.senate : meta?.house;
                      return `${titleCase(chamber)}: ${control ?? '—'}`;
                    })
                    .join(' · ')}
                </td>
                <td className="num">{formatInt.format(entry.withId)}</td>
                <td className="num">{formatInt.format(entry.missing)}</td>
                <td className="num">{formatInt.format(entry.total)}</td>
              </tr>
            ))}
          </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
