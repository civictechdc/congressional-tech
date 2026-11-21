(() => {
  "use strict";

  const DEFAULT_URL_PATTERN = "https://congressional-data.spicygov.ai/bodies/sha256/{sha2}/{sha}.gz";
  const STORAGE_URL_KEY = "docmeta_viewer_url_pattern_v1";
  const ROW_HEIGHT = 48;
  const OVERSCAN = 8;
  const MAX_AUTO_GZ_BYTES = 60 * 1024 * 1024; // 60 MB compressed guard

  // State
  let allDocs = [];
  let docIndexByKey = new Map();
  let filteredDocs = [];
  let reviewsByKey = new Map(); // key -> array of review objects (latest last)
  let selectedKey = null;
  let currentDoc = null;

  let activeMidTab = "text"; // "text" | "source"
  let sideBySide = false;
  let rawJsonMode = false;
  let urlPattern = localStorage.getItem(STORAGE_URL_KEY) || DEFAULT_URL_PATTERN;

  // Find / highlight state
  let activeQuery = "";
  let activeMatchMode = ""; // "exact" | "whitespace" | "ref-stripped" | "not-found"
  let matchElements = [];
  let activeMatchIdx = -1;

  // Source loader state
  let loadedSourceKey = null;
  let loadedSourcePattern = null;
  let sourceAbortCtrl = null;
  let activeBlobUrl = null;

  // DOM Elements
  const elApp = document.getElementById("app");
  const elListCount = document.getElementById("list-count");
  const elReviewedSummary = document.getElementById("reviewed-summary");
  const elDocSearch = document.getElementById("doc-search");
  const elFilterSplit = document.getElementById("filter-split");
  const elFilterFormat = document.getElementById("filter-format");
  const elFilterKind = document.getElementById("filter-kind");
  const elChkOpenFindings = document.getElementById("chk-open-findings");
  const elChkNeedsOwner = document.getElementById("chk-needs-owner");
  const elChkRemoved = document.getElementById("chk-removed");
  const elChkGt10 = document.getElementById("chk-gt10-people");
  const elChkUnreviewed = document.getElementById("chk-unreviewed");
  const elChkNeedsFix = document.getElementById("chk-needs-fix");
  const elChkRulings = document.getElementById("chk-rulings");
  const elBtnResetFilters = document.getElementById("btn-reset-filters");
  const elBtnPrevDoc = document.getElementById("btn-prev-doc");
  const elBtnNextDoc = document.getElementById("btn-next-doc");

  const elViewport = document.getElementById("doc-list-viewport");
  const elSpacer = document.getElementById("doc-list-spacer");
  const elItems = document.getElementById("doc-list-items");

  const elBtnToggleSidebar = document.getElementById("btn-toggle-sidebar");
  const elMidTabGroup = document.getElementById("mid-tab-group");
  const elTabText = document.getElementById("tab-text");
  const elTabSource = document.getElementById("tab-source");
  const elChkSideBySide = document.getElementById("chk-side-by-side");

  const elFindInput = document.getElementById("text-find-input");
  const elFindStatus = document.getElementById("text-find-status");
  const elBtnFindPrev = document.getElementById("btn-find-prev");
  const elBtnFindNext = document.getElementById("btn-find-next");
  const elBtnFindClear = document.getElementById("btn-find-clear");

  const elMatchBanner = document.getElementById("match-banner");
  const elMiddleSplit = document.getElementById("middle-split");
  const elMetaFilename = document.getElementById("meta-filename");
  const elMetaDetails = document.getElementById("meta-details");
  const elKnownDetails = document.getElementById("known-hint-details");
  const elKnownPre = document.getElementById("known-hint-pre");
  const elDocText = document.getElementById("doc-text");

  const elSourceStatusLabel = document.getElementById("source-status-label");
  const elSourceDirectLink = document.getElementById("source-direct-link");
  const elBtnUrlConfig = document.getElementById("btn-url-config");
  const elUrlPatternBox = document.getElementById("url-pattern-box");
  const elUrlPatternInput = document.getElementById("url-pattern-input");
  const elBtnUrlSave = document.getElementById("btn-url-save");
  const elBtnUrlReset = document.getElementById("btn-url-reset");
  const elSourceBody = document.getElementById("source-body");

  const elDocKeyLabel = document.getElementById("doc-key-label");
  const elDocSplitBadge = document.getElementById("doc-split-badge");
  const elDocFormatBadge = document.getElementById("doc-format-badge");
  const elChkRawJson = document.getElementById("chk-raw-json");
  const elRightScroll = document.getElementById("right-scroll");
  const elDocBanners = document.getElementById("doc-banners");
  const elLabelFormView = document.getElementById("label-form-view");
  const elLabelRawView = document.getElementById("label-raw-view");
  const elAuditSections = document.getElementById("audit-sections");

  const elCurrentReviewBanner = document.getElementById("current-review-banner");
  const elReviewField = document.getElementById("review-field");
  const elReviewNote = document.getElementById("review-note");
  const elBtnCorrect = document.getElementById("btn-review-correct");
  const elBtnFix = document.getElementById("btn-review-fix");
  const elChkAutoAdvance = document.getElementById("chk-auto-advance");
  const elSaveFeedback = document.getElementById("review-save-feedback");

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escAttr(str) {
    return esc(str).replace(/\r?\n/g, "&#10;");
  }

  const MONTH_VARIANTS = {
    1: ["January", "Jan\\.?"],
    2: ["February", "Feb\\.?"],
    3: ["March", "Mar\\.?"],
    4: ["April", "Apr\\.?"],
    5: ["May"],
    6: ["June", "Jun\\.?"],
    7: ["July", "Jul\\.?"],
    8: ["August", "Aug\\.?"],
    9: ["September", "Sept?\\.?"],
    10: ["October", "Oct\\.?"],
    11: ["November", "Nov\\.?"],
    12: ["December", "Dec\\.?"],
  };

  function escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function getLatestReview(key) {
    const arr = reviewsByKey.get(key);
    return arr && arr.length ? arr[arr.length - 1] : null;
  }

  function buildSourceUrl(sha, patternOverride) {
    const pat = (patternOverride ?? urlPattern ?? "").trim();
    if (!pat || !sha || sha.length < 4) return null;
    const cleanSha = sha.toLowerCase();
    return pat
      .replace(/\{sha2\}/g, cleanSha.slice(0, 2))
      .replace(/\{sha\}/g, cleanSha)
      .replace(/\{saved_body_hex\}/g, cleanSha);
  }

  // Populate filter <select> options with counts
  function populateSelectOptions() {
    const splits = new Map();
    const formats = new Map();
    const kinds = new Map();

    for (const d of allDocs) {
      splits.set(d.split, (splits.get(d.split) || 0) + 1);
      formats.set(d.format, (formats.get(d.format) || 0) + 1);
      kinds.set(d.kind, (kinds.get(d.kind) || 0) + 1);
    }

    const fill = (selectEl, defaultLabel, map, sortAlpha = true) => {
      const entries = Array.from(map.entries());
      if (sortAlpha) {
        entries.sort((a, b) => a[0].localeCompare(b[0]));
      } else {
        entries.sort((a, b) => b[1] - a[1]);
      }
      selectEl.innerHTML =
        `<option value="">${esc(defaultLabel)} (${allDocs.length})</option>` +
        entries
          .map(([k, c]) => `<option value="${esc(k)}">${esc(k)} (${c})</option>`)
          .join("");
    };

    fill(elFilterSplit, "All splits", splits, true);
    fill(elFilterFormat, "All formats", formats, false);
    fill(elFilterKind, "All kinds / statuses", kinds, true);
  }

  function applyFilters(preserveSelection = true) {
    const q = elDocSearch.value.trim().toLowerCase();
    const splitVal = elFilterSplit.value;
    const formatVal = elFilterFormat.value;
    const kindVal = elFilterKind.value;
    const reqOpen = elChkOpenFindings.checked;
    const reqOwner = elChkNeedsOwner.checked;
    const reqRemoved = elChkRemoved.checked;
    const reqGt10 = elChkGt10.checked;
    const reqUnreviewed = elChkUnreviewed.checked;
    const reqNeedsFix = elChkNeedsFix.checked;
    const reqRulings = elChkRulings.checked;

    filteredDocs = allDocs.filter((d) => {
      if (splitVal && d.split !== splitVal) return false;
      if (formatVal && d.format !== formatVal) return false;
      if (kindVal && d.kind !== kindVal) return false;
      if (reqOpen && !d.has_open_findings) return false;
      if (reqOwner && !(d.needs_owner_count > 0)) return false;
      if (reqRemoved && !d.has_removed_values) return false;
      if (reqGt10 && !d.more_than_10_people) return false;
      if (reqRulings && !d.has_rulings) return false;
      if (reqUnreviewed && reviewsByKey.has(d.key)) return false;
      if (reqNeedsFix) {
        const rev = getLatestReview(d.key);
        if (!rev || rev.verdict !== "needs_fix") return false;
      }
      if (q) {
        const hayKey = d.key.toLowerCase();
        const hayFn = (d.filename || "").toLowerCase();
        if (!hayKey.includes(q) && !hayFn.includes(q)) return false;
      }
      return true;
    });

    elListCount.textContent = `${filteredDocs.length.toLocaleString()} / ${allDocs.length.toLocaleString()}`;
    updateReviewedSummary();

    elSpacer.style.height = `${filteredDocs.length * ROW_HEIGHT}px`;

    if (filteredDocs.length === 0) {
      elItems.innerHTML = `<div class="muted-xs" style="padding:14px;text-align:center;">No matching documents.</div>`;
      return;
    }

    if (!preserveSelection || !selectedKey || !filteredDocs.some((d) => d.key === selectedKey)) {
      selectDocument(filteredDocs[0].key, { scrollList: true });
    } else {
      renderVirtualList();
    }
  }

  function updateReviewedSummary() {
    let totalRev = 0;
    let fixCount = 0;
    for (const d of allDocs) {
      const r = getLatestReview(d.key);
      if (r) {
        totalRev++;
        if (r.verdict === "needs_fix") fixCount++;
      }
    }
    elReviewedSummary.textContent = fixCount
      ? `${totalRev} reviewed (${fixCount} fix)`
      : `${totalRev} reviewed`;
  }

  function renderVirtualList() {
    const total = filteredDocs.length;
    if (total === 0) return;

    const scrollTop = elViewport.scrollTop;
    const viewH = elViewport.clientHeight || 600;
    const startIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
    const endIdx = Math.min(total, Math.ceil((scrollTop + viewH) / ROW_HEIGHT) + OVERSCAN);

    elItems.style.transform = `translateY(${startIdx * ROW_HEIGHT}px)`;

    const html = [];
    for (let i = startIdx; i < endIdx; i++) {
      const d = filteredDocs[i];
      const isSel = d.key === selectedKey;
      const rev = getLatestReview(d.key);
      let revBadge = "";
      if (rev) {
        if (rev.verdict === "label_correct") {
          revBadge = `<span class="mini-flag flag-ok" title="Reviewed: Label correct">✓</span>`;
        } else {
          revBadge = `<span class="mini-flag flag-fix" title="Reviewed: Needs a fix">!</span>`;
        }
      }
      const openBadge = d.has_open_findings
        ? `<span class="mini-flag flag-open" title="${d.open_findings_count} open finding(s)">${d.needs_owner_count > 0 ? "⚑" : "•"}${d.open_findings_count}</span>`
        : "";
      const gt10Badge = d.more_than_10_people
        ? `<span class="mini-flag flag-gt10" title="${d.people_count} people">P:${d.people_count}</span>`
        : "";

      html.push(
        `<div class="doc-row${isSel ? " selected" : ""}" data-key="${esc(d.key)}">` +
          `<div class="doc-row-top">` +
            revBadge +
            `<span class="doc-row-fn" title="${esc(d.filename)}">${esc(d.filename)}</span>` +
            openBadge +
            gt10Badge +
          `</div>` +
          `<div class="doc-row-sub">` +
            `<span class="doc-row-key">${esc(d.key.slice(0, 10))}</span>` +
            `<span>·</span>` +
            `<span>${esc(d.split)}</span>` +
            `<span>·</span>` +
            `<span class="doc-row-kind" title="${esc(d.kind)}">${esc(d.kind)}</span>` +
          `</div>` +
        `</div>`
      );
    }
    elItems.innerHTML = html.join("");
  }

  function ensureSelectedVisibleInList() {
    if (!selectedKey) return;
    const idx = filteredDocs.findIndex((d) => d.key === selectedKey);
    if (idx < 0) return;
    const top = idx * ROW_HEIGHT;
    const bottom = top + ROW_HEIGHT;
    const viewTop = elViewport.scrollTop;
    const viewH = elViewport.clientHeight || 500;
    if (top < viewTop) {
      elViewport.scrollTop = top;
    } else if (bottom > viewTop + viewH) {
      elViewport.scrollTop = bottom - viewH;
    }
    renderVirtualList();
  }

  function stepDocument(delta) {
    if (!filteredDocs.length) return;
    const idx = filteredDocs.findIndex((d) => d.key === selectedKey);
    const nextIdx = idx < 0 ? 0 : Math.max(0, Math.min(filteredDocs.length - 1, idx + delta));
    if (filteredDocs[nextIdx] && filteredDocs[nextIdx].key !== selectedKey) {
      selectDocument(filteredDocs[nextIdx].key, { scrollList: true });
    }
  }

  async function selectDocument(key, opts = {}) {
    if (!key) return;
    selectedKey = key;
    history.replaceState(null, "", `#key=${encodeURIComponent(key)}`);

    if (opts.scrollList) {
      ensureSelectedVisibleInList();
    } else {
      renderVirtualList();
    }

    // Clear find/match banner when switching documents unless find input has persistent query
    hideMatchBanner();
    elSaveFeedback.textContent = "";

    try {
      const resp = await fetch(`data/docs/${encodeURIComponent(key)}.json`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const doc = await resp.json();
      if (selectedKey !== key) return; // superseded by faster navigation
      currentDoc = doc;
      renderDocument(doc);
    } catch (err) {
      elDocText.textContent = `Error loading document ${key}: ${err.message}`;
    }
  }

  function renderDocument(doc) {
    // 1. Text pane metadata + content
    elMetaFilename.textContent = doc.filename || doc.key;
    const charCount = (doc.text || "").length.toLocaleString();
    elMetaDetails.textContent = `${doc.format || "?"} · source: ${doc.text_source || "?"} · ${charCount} chars`;

    if (doc.known && typeof doc.known === "object" && Object.keys(doc.known).length > 0) {
      elKnownDetails.classList.remove("hidden");
      elKnownPre.textContent = JSON.stringify(doc.known, null, 2);
    } else {
      elKnownDetails.classList.add("hidden");
    }

    // Render text (re-apply find box query if user typed one)
    const userFind = elFindInput.value;
    if (userFind.trim()) {
      highlightInText(userFind, { fromFindBox: true });
    } else {
      renderPlainText(doc.text || "");
      elFindStatus.textContent = "";
      document.getElementById("text-scroll").scrollTop = 0;
    }

    // 2. Right pane header & banners
    elDocKeyLabel.textContent = doc.key;
    elDocSplitBadge.textContent = doc.split || "unknown";
    elDocFormatBadge.textContent = doc.format || "?";

    const banners = [];
    if (doc.excluded_reason) {
      banners.push(`<div class="doc-alert"><strong>Excluded:</strong> ${esc(doc.excluded_reason)}</div>`);
    }
    if (doc.seen_template) {
      banners.push(
        `<div class="doc-alert"><strong>Seen template:</strong> <code>${esc(JSON.stringify(doc.seen_template))}</code></div>`
      );
    }
    elDocBanners.innerHTML = banners.join("");

    // 3. Structured Label Form & Raw JSON
    renderLabelForm(doc.label || {});
    let prettyRaw = doc.label_raw || "";
    try {
      prettyRaw = JSON.stringify(doc.label, null, 2);
    } catch (_) {}
    elLabelRawView.textContent = prettyRaw;
    elRightScroll.scrollTop = 0;

    // 4. Collapsible Audit Sections
    renderAuditSections(doc);

    // 5. Review controls state for this doc
    renderReviewFooter(doc.key);

    // 6. Source pane (lazy: load only if visible!)
    resetSourceIfChanged(doc);
    if (isSourceVisible()) {
      loadSourceForCurrentDoc();
    }
  }

  function renderPlainText(text) {
    elDocText.textContent = text;
    matchElements = [];
    activeMatchIdx = -1;
    activeQuery = "";
  }

  // Clickable value renderer
  function renderClickableScalar(val, extraOpts = {}) {
    if (val === null || val === undefined) {
      return `<span class="muted-xs">null</span>`;
    }
    if (typeof val === "boolean") {
      return `<code>${val ? "true" : "false"}</code>`;
    }
    const str = String(val);
    if (!str.trim()) return `<span class="muted-xs">(empty)</span>`;
    const cls = extraOpts.chip ? "val-chip clickable-val" : "clickable-val";
    const fieldAttr = extraOpts.field ? ` data-field="${escAttr(extraOpts.field)}"` : "";
    return `<span class="${cls}" data-search="${escAttr(str)}"${fieldAttr} title="Click to highlight in Text">${esc(str)}</span>`;
  }

  function renderAnyValue(val, fieldName = "") {
    if (val === null || val === undefined) {
      return `<span class="muted-xs">—</span>`;
    }
    if (Array.isArray(val)) {
      if (val.length === 0) return `<span class="muted-xs">[]</span>`;
      if (val.every((x) => typeof x !== "object" || x === null)) {
        return (
          `<div class="val-chip-list">` +
          val.map((item) => renderClickableScalar(item, { chip: true, field: fieldName })).join("") +
          `</div>`
        );
      }
      return val.map((item) => `<div style="margin-bottom:3px;">${renderAnyValue(item, fieldName)}</div>`).join("");
    }
    if (typeof val === "object") {
      const parts = Object.entries(val).map(
        ([k, v]) => `<span class="muted-xs">${esc(k)}:</span> ${renderAnyValue(v, k)}`
      );
      return `<span>{ ${parts.join(", ")} }</span>`;
    }
    return renderClickableScalar(val, { field: fieldName });
  }

  function renderLabelGroup(title, entries, rightBadgeHtml = "") {
    if (!entries.length) return "";
    const rows = entries
      .map(
        ([k, v]) =>
          `<tr>` +
          `<td class="kv-key" data-set-field="${escAttr(k)}" title="Click to set '${escAttr(k)}' in review field">${esc(k)}</td>` +
          `<td class="kv-val">${renderAnyValue(v, k)}</td>` +
          `</tr>`
      )
      .join("");
    return (
      `<section class="label-group">` +
      `<div class="label-group-title"><span>${esc(title)}</span>${rightBadgeHtml}</div>` +
      `<table class="kv-table"><tbody>${rows}</tbody></table>` +
      `</section>`
    );
  }

  function renderPeopleGroup(personas) {
    const list = Array.isArray(personas) ? personas : [];
    const countBadge =
      list.length > 10
        ? `<span class="badge badge-warn">${list.length} people (&gt;10)</span>`
        : `<span class="badge badge-muted">${list.length}</span>`;

    if (list.length === 0) {
      return (
        `<section class="label-group">` +
        `<div class="label-group-title"><span>People</span>${countBadge}</div>` +
        `<div class="muted-xs" style="padding:5px 8px;">None listed</div>` +
        `</section>`
      );
    }

    const coreKeys = new Set(["name", "role", "title", "org", "party_state"]);
    const rowsHtml = [];

    for (let i = 0; i < list.length; i++) {
      const p = list[i] || {};
      rowsHtml.push(
        `<tr>` +
          `<td>${p.name ? renderClickableScalar(p.name, { field: "personas.name" }) : `<span class="muted-xs">—</span>`}</td>` +
          `<td>${p.role ? renderClickableScalar(p.role, { field: "personas.role" }) : `<span class="muted-xs">—</span>`}</td>` +
          `<td>${p.title ? renderClickableScalar(p.title, { field: "personas.title" }) : `<span class="muted-xs">—</span>`}</td>` +
          `<td>${p.org ? renderClickableScalar(p.org, { field: "personas.org" }) : `<span class="muted-xs">—</span>`}</td>` +
          `<td>${p.party_state ? renderClickableScalar(p.party_state, { field: "personas.party_state" }) : `<span class="muted-xs">—</span>`}</td>` +
        `</tr>`
      );

      // Show additional persona attributes (entity_type, creds, sub_org, panel, work_addr, education, prior_roles, etc.) cleanly beneath
      const extras = Object.entries(p).filter(([k, v]) => !coreKeys.has(k) && v !== null && v !== undefined);
      if (extras.length > 0) {
        const extraHtml = extras
          .map(([k, v]) => `<span class="person-extra-tag"><strong>${esc(k)}:</strong> ${renderAnyValue(v, `personas.${k}`)}</span>`)
          .join("");
        rowsHtml.push(`<tr class="person-extra-row"><td colspan="5">${extraHtml}</td></tr>`);
      }
    }

    return (
      `<section class="label-group">` +
      `<div class="label-group-title"><span>People</span>${countBadge}</div>` +
      `<div class="people-table-wrap">` +
        `<table class="people-table">` +
          `<thead><tr><th>Name</th><th>Role</th><th>Title</th><th>Org</th><th>Party/St</th></tr></thead>` +
          `<tbody>${rowsHtml.join("")}</tbody>` +
        `</table>` +
      `</div>` +
      `</section>`
    );
  }

  function renderLabelForm(label) {
    const shown = new Set();
    const pick = (keys) => {
      const out = [];
      for (const k of keys) {
        if (Object.prototype.hasOwnProperty.call(label, k) && label[k] !== undefined) {
          shown.add(k);
          out.push([k, label[k]]);
        }
      }
      return out;
    };

    const gStatus = pick(["status", "text_quality", "error_reason", "primary_kind", "secondary_kinds", "subkind"]);
    const gCongress = pick(["chamber", "congress", "committees", "subcommittees", "issuer_org"]);
    const gDates = pick(["doc_date", "event_date", "due_date", "date_spans", "event_time", "fiscal_years"]);
    const gTitles = pick(["verbatim_title", "event_title", "composed_title", "short_titles"]);
    shown.add("personas");

    const preferredOther = [
      "gist",
      "topics",
      "event_type",
      "venue_kind",
      "venue",
      "refs",
      "programs",
      "orgs_mentioned",
      "places",
      "correspondence_flow",
      "signatory_count",
      "action_summary",
      "disclosure",
    ];
    const gOther = pick(preferredOther);
    for (const k of Object.keys(label)) {
      if (!shown.has(k)) {
        gOther.push([k, label[k]]);
      }
    }

    const html = [
      renderLabelGroup("Status & Kind", gStatus),
      renderLabelGroup("Chamber, Congress & Committees", gCongress),
      renderLabelGroup("Dates", gDates),
      renderLabelGroup("Titles", gTitles),
      renderPeopleGroup(label.personas),
      renderLabelGroup("Other Fields", gOther),
    ].join("");

    elLabelFormView.innerHTML = html;
  }

  function findingStatusBadge(status) {
    if (status === "needs_owner") return `<span class="badge badge-err">needs_owner</span>`;
    if (status === "scope_question") return `<span class="badge badge-warn">scope_question</span>`;
    if (status === "applied") return `<span class="badge badge-ok">applied</span>`;
    return `<span class="badge badge-muted">${esc(status || "unknown")}</span>`;
  }

  function renderAuditSections(doc) {
    const sig = Array.isArray(doc.signal) ? doc.signal : [];
    const chg = Array.isArray(doc.changes) ? doc.changes : [];
    const fnd = Array.isArray(doc.findings) ? doc.findings.slice() : [];
    const rul = Array.isArray(doc.rulings) ? doc.rulings : [];

    // Sort open findings (needs_owner first, then scope_question) to top
    const rank = (s) => (s === "needs_owner" ? 0 : s === "scope_question" ? 1 : 2);
    fnd.sort((a, b) => rank(a.status) - rank(b.status));
    const openFndCount = fnd.filter((x) => x.status === "needs_owner" || x.status === "scope_question").length;

    const parts = [];

    // 1. Removed by clean-up (signal)
    if (sig.length > 0) {
      const items = sig
        .map((s) => {
          const where = s.source || (Array.isArray(s.occurs_in) ? s.occurs_in.join(", ") : "unknown");
          return (
            `<div class="audit-card">` +
              `<div class="audit-card-head">` +
                `<code>${esc(s.field || "?")}</code>` +
                `<span class="muted-xs">from: <strong>${esc(where)}</strong>${s.rule ? ` (${esc(s.rule)})` : ""}</span>` +
              `</div>` +
              `<div>${renderAnyValue(s.value, s.field || "")}</div>` +
            `</div>`
          );
        })
        .join("");
      parts.push(
        `<details class="audit-section" ${sig.length <= 6 ? "open" : ""}>` +
          `<summary><span>Removed by clean-up</span><span class="badge badge-muted">${sig.length}</span></summary>` +
          `<div class="audit-list">${items}</div>` +
        `</details>`
      );
    } else {
      parts.push(
        `<details class="audit-section empty-section">` +
          `<summary><span>Removed by clean-up</span><span class="badge badge-muted">0</span></summary>` +
          `<div class="audit-list muted-xs">None</div>` +
        `</details>`
      );
    }

    // 2. Changes today (normalize_changelog)
    if (chg.length > 0) {
      const items = chg
        .map(
          (c) =>
            `<div class="audit-card">` +
              `<div class="audit-card-head">` +
                `<code>${esc(c.field || "?")}</code>` +
                `<span class="badge badge-muted">${esc(c.rule || "-")}</span>` +
              `</div>` +
              `<div class="diff-line diff-before">− ${renderAnyValue(c.before, c.field || "")}</div>` +
              `<div class="diff-line diff-after">+ ${renderAnyValue(c.after, c.field || "")}</div>` +
            `</div>`
        )
        .join("");
      parts.push(
        `<details class="audit-section" ${chg.length <= 4 ? "open" : ""}>` +
          `<summary><span>Changes today</span><span class="badge badge-muted">${chg.length}</span></summary>` +
          `<div class="audit-list">${items}</div>` +
        `</details>`
      );
    } else {
      parts.push(
        `<details class="audit-section empty-section">` +
          `<summary><span>Changes today</span><span class="badge badge-muted">0</span></summary>` +
          `<div class="audit-list muted-xs">None</div>` +
        `</details>`
      );
    }

    // 3. Reviewer findings
    if (fnd.length > 0) {
      const items = fnd
        .map((f) => {
          const cardCls =
            f.status === "needs_owner"
              ? "audit-card needs-owner-finding"
              : f.status === "scope_question"
              ? "audit-card open-finding"
              : "audit-card";
          const quoteHtml = f.quote
            ? `<div class="audit-quote clickable-val" data-search="${escAttr(f.quote)}" title="Click to highlight quote in Text">${esc(f.quote)}</div>`
            : "";
          const valLine =
            f.label_value !== null && f.label_value !== undefined
              ? `<div class="muted-xs">Label: ${renderAnyValue(f.label_value, f.field || "")}</div>`
              : "";
          const shouldLine =
            f.should_be !== null && f.should_be !== undefined
              ? `<div class="muted-xs">Proposed: ${renderAnyValue(f.should_be, f.field || "")}</div>`
              : "";
          const whyLine = f.why ? `<div style="margin-top:2px;">${esc(f.why)}</div>` : "";
          const resLine = f.reason
            ? `<div class="muted-xs" style="margin-top:2px;">Resolution${f.rule && f.rule !== "-" ? ` (${esc(f.rule)})` : ""}: ${esc(f.reason)}</div>`
            : "";

          return (
            `<div class="${cardCls}">` +
              `<div class="audit-card-head">` +
                `<span><code class="kv-key" style="padding:0;" data-set-field="${escAttr(f.field || "")}" title="Click to set review field">${esc(f.field || "?")}</code> · <strong>${esc(f.type || "?")}</strong></span>` +
                findingStatusBadge(f.status) +
              `</div>` +
              quoteHtml +
              valLine +
              shouldLine +
              whyLine +
              resLine +
            `</div>`
          );
        })
        .join("");
      const badgeHtml =
        openFndCount > 0
          ? `<span class="badge badge-warn">${openFndCount} open / ${fnd.length}</span>`
          : `<span class="badge badge-muted">${fnd.length}</span>`;
      parts.push(
        `<details class="audit-section" ${openFndCount > 0 ? "open" : ""}>` +
          `<summary><span>Reviewer findings</span>${badgeHtml}</summary>` +
          `<div class="audit-list">${items}</div>` +
        `</details>`
      );
    } else {
      parts.push(
        `<details class="audit-section empty-section">` +
          `<summary><span>Reviewer findings</span><span class="badge badge-muted">0</span></summary>` +
          `<div class="audit-list muted-xs">None</div>` +
        `</details>`
      );
    }

    // 4. Rulings (adjudications)
    if (rul.length > 0) {
      const items = rul
        .map((r) => {
          const quoteHtml = r.quote
            ? `<div class="audit-quote clickable-val" data-search="${escAttr(r.quote)}" title="Click to highlight quote in Text">${esc(r.quote)}</div>`
            : "";
          return (
            `<div class="audit-card">` +
              `<div class="audit-card-head">` +
                `<code>${esc(r.rule || "?")}</code>` +
                `<span class="badge badge-ok">${esc(r.verdict || "?")}</span>` +
              `</div>` +
              quoteHtml +
              (r.note ? `<div>${esc(r.note)}</div>` : "") +
              `<div class="muted-xs">${esc(r.ruled_by || "")} · ${esc(r.ruled_at || "")}</div>` +
            `</div>`
          );
        })
        .join("");
      parts.push(
        `<details class="audit-section" open>` +
          `<summary><span>Rulings</span><span class="badge badge-ok">${rul.length}</span></summary>` +
          `<div class="audit-list">${items}</div>` +
        `</details>`
      );
    } else {
      parts.push(
        `<details class="audit-section empty-section">` +
          `<summary><span>Rulings</span><span class="badge badge-muted">0</span></summary>` +
          `<div class="audit-list muted-xs">None</div>` +
        `</details>`
      );
    }

    elAuditSections.innerHTML = parts.join("");
  }

  // Highlight & scroll in Text pane
  function findRangesInText(text, query, fieldHint = "") {
    const trimmed = query.trim();
    if (!trimmed) return { ranges: [], mode: "" };

    const collectRegexRanges = (re) => {
      const out = [];
      let m;
      while ((m = re.exec(text)) !== null) {
        if (m[0].length === 0) {
          re.lastIndex++;
          continue;
        }
        out.push([m.index, m.index + m[0].length]);
        if (out.length >= 500) break;
      }
      return out;
    };

    // 1. Direct case-insensitive substring
    const directRe = new RegExp(escapeRegExp(trimmed), "gi");
    let ranges = collectRegexRanges(directRe);
    if (ranges.length > 0) return { ranges, mode: "exact" };

    // 2. Whitespace-flexible match (handles PDF line wraps & multiple spaces)
    const tokens = trimmed.split(/\s+/).filter(Boolean);
    if (tokens.length > 1) {
      const wsPattern = tokens.map(escapeRegExp).join("(?:\\s+|-\\s*\\n\\s*)");
      const wsRe = new RegExp(wsPattern, "gi");
      ranges = collectRegexRanges(wsRe);
      if (ranges.length > 0) return { ranges, mode: "whitespace" };
    }

    // 3. ISO date fallback (YYYY-MM-DD or YYYY-MM -> printed date in text)
    const dateMatch = trimmed.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?$/);
    if (dateMatch) {
      const y = Number(dateMatch[1]);
      const mo = Number(dateMatch[2]);
      const dy = dateMatch[3] ? Number(dateMatch[3]) : null;
      const mVars = MONTH_VARIANTS[mo];
      if (mVars) {
        const mGroup = mVars.join("|");
        const y2 = String(y).slice(2);
        const datePat = dy
          ? `(?:(?:${mGroup})\\s+0?${dy}(?:st|nd|rd|th)?,?\\s+${y}|\\b0?${dy}\\s+(?:${mGroup}),?\\s+${y}|\\b0?${mo}[/.-]0?${dy}[/.-](?:${y}|${y2})\\b)`
          : `(?:${mGroup}),?\\s+${y}`;
        ranges = collectRegexRanges(new RegExp(datePat, "gi"));
        if (ranges.length > 0) return { ranges, mode: "printed-date" };
      }
    }

    // 4. DocMeta prefixed refs fallback (e.g. "bill:H.R. 1838" -> "H.R. 1838")
    if ((fieldHint === "refs" || /^[a-z_]+:.+/i.test(trimmed)) && trimmed.includes(":")) {
      const stripped = trimmed.replace(/^[a-z_]+:/i, "").trim();
      if (stripped.length >= 2) {
        const stripTokens = stripped.split(/\s+/).filter(Boolean);
        const stripPat = stripTokens.map(escapeRegExp).join("\\s+");
        ranges = collectRegexRanges(new RegExp(stripPat, "gi"));
        if (ranges.length > 0) return { ranges, mode: "ref-stripped" };
      }
    }

    // 5. Congress ordinal fallback (e.g. congress: 114 -> "114th Congress")
    if (fieldHint === "congress" && /^\d{1,3}$/.test(trimmed)) {
      const congPat = `\\b${escapeRegExp(trimmed)}(?:st|nd|rd|th)?\\s+Congress\\b`;
      ranges = collectRegexRanges(new RegExp(congPat, "gi"));
      if (ranges.length > 0) return { ranges, mode: "congress" };
    }

    return { ranges: [], mode: "not-found" };
  }

  function highlightInText(query, opts = {}) {
    if (!currentDoc) return;
    const text = currentDoc.text || "";
    const q = String(query || "");

    if (!q.trim()) {
      renderPlainText(text);
      elFindStatus.textContent = "";
      hideMatchBanner();
      return;
    }

    // Switch to Text tab automatically when clicking a label/quote while viewing Source-only
    if (!opts.fromFindBox && !sideBySide && activeMidTab !== "text") {
      setMidTab("text");
    }

    const { ranges, mode } = findRangesInText(text, q, opts.field || "");
    activeQuery = q;
    activeMatchMode = mode;

    if (ranges.length === 0) {
      renderPlainText(text);
      elFindStatus.textContent = "0 / 0";
      if (!opts.fromFindBox) {
        showMatchBanner(`not found in text — "${truncateStr(q.trim(), 90)}"`, false);
      } else {
        showMatchBanner(`not found in text`, false);
      }
      return;
    }

    // Build highlighted HTML safely
    const parts = [];
    let cursor = 0;
    for (let i = 0; i < ranges.length; i++) {
      const [s, e] = ranges[i];
      if (s < cursor) continue;
      if (s > cursor) parts.push(esc(text.slice(cursor, s)));
      parts.push(`<mark class="${i === 0 ? "active-hit" : ""}" data-hit-idx="${i}">${esc(text.slice(s, e))}</mark>`);
      cursor = e;
    }
    if (cursor < text.length) parts.push(esc(text.slice(cursor)));

    elDocText.innerHTML = parts.join("");
    matchElements = Array.from(elDocText.querySelectorAll("mark"));
    activeMatchIdx = 0;
    updateActiveMatchScroll();

    if (!opts.fromFindBox) {
      const firstMatchedSlice = text.slice(ranges[0][0], ranges[0][1]);
      elFindInput.value = firstMatchedSlice.length <= 120 ? firstMatchedSlice : "";
      const note =
        mode === "whitespace"
          ? " (matched across line/space wrap)"
          : mode === "printed-date"
          ? ` (matched printed date "${truncateStr(firstMatchedSlice, 40)}")`
          : mode === "ref-stripped"
          ? " (matched without ref prefix)"
          : mode === "congress"
          ? " (matched Congress ordinal)"
          : "";
      showMatchBanner(
        `Highlighted "${truncateStr(q.trim(), 70)}" — match 1 of ${matchElements.length}${note}`,
        true
      );
    } else {
      hideMatchBanner();
    }
  }

  function stepMatch(delta) {
    if (!matchElements.length) return;
    if (activeMatchIdx >= 0 && matchElements[activeMatchIdx]) {
      matchElements[activeMatchIdx].classList.remove("active-hit");
    }
    activeMatchIdx = (activeMatchIdx + delta + matchElements.length) % matchElements.length;
    updateActiveMatchScroll();
  }

  function updateActiveMatchScroll() {
    if (!matchElements.length || activeMatchIdx < 0) return;
    const el = matchElements[activeMatchIdx];
    el.classList.add("active-hit");
    elFindStatus.textContent = `${activeMatchIdx + 1} / ${matchElements.length}`;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function showMatchBanner(msg, found) {
    elMatchBanner.textContent = msg;
    elMatchBanner.className = `match-banner ${found ? "found" : "not-found"}`;
  }

  function hideMatchBanner() {
    elMatchBanner.className = "match-banner hidden";
    elMatchBanner.textContent = "";
  }

  function truncateStr(s, maxLen) {
    const clean = s.replace(/\s+/g, " ");
    return clean.length > maxLen ? clean.slice(0, maxLen - 1) + "…" : clean;
  }

  // Source PDF / Non-PDF handling
  function isSourceVisible() {
    return sideBySide || activeMidTab === "source";
  }

  function revokeActiveBlob() {
    if (activeBlobUrl) {
      URL.revokeObjectURL(activeBlobUrl);
      activeBlobUrl = null;
    }
  }

  function resetSourceIfChanged(doc) {
    if (loadedSourceKey === doc.key && loadedSourcePattern === urlPattern) return;
    if (sourceAbortCtrl) {
      sourceAbortCtrl.abort();
      sourceAbortCtrl = null;
    }
    revokeActiveBlob();
    loadedSourceKey = null;
    elSourceBody.innerHTML = `<div class="source-placeholder">Source ready to load.</div>`;
    elSourceDirectLink.classList.add("hidden");
  }

  async function decompressGzipIfNeeded(arrayBuffer, mimeType) {
    const bytes = new Uint8Array(arrayBuffer);
    const isGzip = bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
    if (isGzip && typeof DecompressionStream !== "undefined") {
      const ds = new DecompressionStream("gzip");
      const stream = new Blob([arrayBuffer]).stream().pipeThrough(ds);
      return await new Response(stream, { headers: { "Content-Type": mimeType } }).blob();
    }
    return new Blob([arrayBuffer], { type: mimeType });
  }

  async function loadSourceForCurrentDoc(forceUnpackLarge = false) {
    if (!currentDoc) return;
    const doc = currentDoc;
    if (loadedSourceKey === doc.key && loadedSourcePattern === urlPattern && !forceUnpackLarge) {
      return;
    }

    if (sourceAbortCtrl) sourceAbortCtrl.abort();
    revokeActiveBlob();

    const sha = doc.saved_body_hex;
    const primaryUrl = buildSourceUrl(sha);

    if (!primaryUrl) {
      elSourceStatusLabel.textContent = "Source file URL not configured";
      elSourceDirectLink.classList.add("hidden");
      elUrlPatternBox.classList.remove("hidden");
      elSourceBody.innerHTML =
        `<div class="source-card">` +
          `<strong>Source file URL not found</strong>` +
          `<div class="muted-xs">${sha ? `saved_body_hex: <code>${esc(sha)}</code>` : "Document has no saved_body_hex."}</div>` +
          `<div class="muted-xs">Set a URL pattern above using <code>{sha}</code> and <code>{sha2}</code>.</div>` +
        `</div>`;
      return;
    }

    elSourceDirectLink.href = primaryUrl;
    elSourceDirectLink.classList.remove("hidden");

    const fmt = (doc.format || "").toLowerCase();

    // Non-PDF sources (HTML, XML, DOCX, DOC, TEXT, etc.): link that opens in a new tab
    if (fmt !== "pdf") {
      loadedSourceKey = doc.key;
      loadedSourcePattern = urlPattern;
      const fallbackNoGz = primaryUrl.endsWith(".gz") ? primaryUrl.slice(0, -3) : null;
      elSourceStatusLabel.textContent = `Non-PDF source (${fmt.toUpperCase()})`;
      elSourceBody.innerHTML =
        `<div class="source-card">` +
          `<strong>${esc(doc.filename || doc.key)}</strong>` +
          `<div class="muted-xs">Format: <strong>${esc(fmt.toUpperCase())}</strong> · SHA-256: <code>${esc(sha.slice(0, 16))}…</code></div>` +
          `<div class="source-card-actions">` +
            `<a class="btn-primary-link" href="${esc(primaryUrl)}" target="_blank" rel="noopener noreferrer">Open source in new tab ↗</a>` +
            `<button type="button" id="btn-unpack-download" class="btn-sm">Unpack &amp; download ${esc(doc.filename || "file")}</button>` +
            (fmt === "html" || fmt === "xml" || fmt === "text"
              ? `<button type="button" id="btn-sandbox-preview" class="btn-sm">Preview unpacked (sandboxed)</button>`
              : "") +
          `</div>` +
          (fallbackNoGz
            ? `<div class="muted-xs">Uncompressed fallback: <a href="${esc(fallbackNoGz)}" target="_blank" rel="noopener noreferrer">${esc(fallbackNoGz.split("/").pop())} ↗</a></div>`
            : "") +
        `</div>`;

      const btnDl = document.getElementById("btn-unpack-download");
      if (btnDl) {
        btnDl.addEventListener("click", () => unpackAndDownloadNonPdf(doc, primaryUrl));
      }
      const btnPrev = document.getElementById("btn-sandbox-preview");
      if (btnPrev) {
        btnPrev.addEventListener("click", () => previewSandboxedMarkup(doc, primaryUrl));
      }
      return;
    }

    // PDF source: render inside <iframe> in the browser
    loadedSourceKey = doc.key;
    loadedSourcePattern = urlPattern;

    // If URL does not end with .gz, load directly in <iframe>
    if (!primaryUrl.endsWith(".gz")) {
      elSourceStatusLabel.textContent = `PDF (${doc.filename || doc.key})`;
      elSourceBody.innerHTML = `<iframe class="source-iframe" src="${esc(primaryUrl)}" title="Source PDF"></iframe>`;
      return;
    }

    // .gz content-addressed R2 PDF: fetch directly in browser, gunzip via DecompressionStream, display in <iframe>
    const ctrl = new AbortController();
    sourceAbortCtrl = ctrl;
    elSourceStatusLabel.textContent = "Loading source PDF…";
    elSourceBody.innerHTML = `<div class="source-placeholder">Fetching &amp; unpacking PDF from archive…</div>`;

    try {
      const resp = await fetch(primaryUrl, { signal: ctrl.signal });
      if (ctrl.signal.aborted) return;

      // 22 archival PDFs are stored uncompressed without .gz suffix
      if (resp.status === 404) {
        const bareUrl = primaryUrl.slice(0, -3);
        elSourceDirectLink.href = bareUrl;
        elSourceStatusLabel.textContent = `PDF (uncompressed stream)`;
        elSourceBody.innerHTML = `<iframe class="source-iframe" src="${esc(bareUrl)}" title="Source PDF"></iframe>`;
        return;
      }

      if (!resp.ok) {
        throw new Error(`Archive returned HTTP ${resp.status}`);
      }

      const contentLen = Number(resp.headers.get("Content-Length") || 0);
      if (contentLen > MAX_AUTO_GZ_BYTES && !forceUnpackLarge) {
        const mb = (contentLen / (1024 * 1024)).toFixed(1);
        ctrl.abort();
        elSourceStatusLabel.textContent = `Large PDF (${mb} MB compressed)`;
        elSourceBody.innerHTML =
          `<div class="source-card">` +
            `<strong>Large compressed PDF (${esc(mb)} MB)</strong>` +
            `<div class="source-card-actions">` +
              `<button type="button" id="btn-force-pdf" class="btn-sm">Fetch &amp; render anyway</button>` +
              `<a class="btn-primary-link" href="${esc(primaryUrl)}" target="_blank" rel="noopener noreferrer">Download .gz ↗</a>` +
            `</div>` +
          `</div>`;
        document.getElementById("btn-force-pdf")?.addEventListener("click", () => loadSourceForCurrentDoc(true));
        return;
      }

      const buf = await resp.arrayBuffer();
      if (ctrl.signal.aborted) return;

      const pdfBlob = await decompressGzipIfNeeded(buf, "application/pdf");
      if (ctrl.signal.aborted) return;

      activeBlobUrl = URL.createObjectURL(pdfBlob);
      const sizeKb = Math.round(pdfBlob.size / 1024).toLocaleString();
      elSourceStatusLabel.textContent = `PDF · ${sizeKb} KB`;
      elSourceBody.innerHTML = `<iframe class="source-iframe" src="${esc(activeBlobUrl)}" title="Source PDF"></iframe>`;
    } catch (err) {
      if (ctrl.signal.aborted) return;
      elSourceStatusLabel.textContent = "Source load error";
      elSourceBody.innerHTML =
        `<div class="source-card">` +
          `<strong>Could not load PDF in pane</strong>` +
          `<div class="muted-xs">${esc(err.message)}</div>` +
          `<div class="source-card-actions">` +
            `<a class="btn-primary-link" href="${esc(primaryUrl)}" target="_blank" rel="noopener noreferrer">Open URL in new tab ↗</a>` +
          `</div>` +
        `</div>`;
    }
  }

  async function fetchUnpackedNonPdfBlob(primaryUrl, mimeType) {
    let resp = await fetch(primaryUrl);
    if (resp.status === 404 && primaryUrl.endsWith(".gz")) {
      resp = await fetch(primaryUrl.slice(0, -3));
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const buf = await resp.arrayBuffer();
    return await decompressGzipIfNeeded(buf, mimeType);
  }

  async function unpackAndDownloadNonPdf(doc, primaryUrl) {
    try {
      elSourceStatusLabel.textContent = "Unpacking source…";
      const blob = await fetchUnpackedNonPdfBlob(primaryUrl, "application/octet-stream");
      const dlUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = dlUrl;
      a.download = doc.filename || `${doc.key}.${doc.format || "bin"}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(dlUrl), 5000);
      elSourceStatusLabel.textContent = `Downloaded ${doc.filename || doc.key}`;
    } catch (err) {
      elSourceStatusLabel.textContent = `Unpack failed: ${err.message}`;
    }
  }

  async function previewSandboxedMarkup(doc, primaryUrl) {
    try {
      elSourceStatusLabel.textContent = "Unpacking preview…";
      const blob = await fetchUnpackedNonPdfBlob(primaryUrl, "text/plain; charset=utf-8");
      const rawText = await blob.text();
      const fmt = (doc.format || "").toLowerCase();
      const iframe = document.createElement("iframe");
      iframe.className = "source-iframe";
      iframe.setAttribute("sandbox", ""); // strictly blocks all scripts and same-origin access
      if (fmt === "html") {
        iframe.srcdoc = rawText;
      } else {
        iframe.srcdoc = `<pre style="font:12px monospace;white-space:pre-wrap;word-break:break-word;margin:12px;">${esc(rawText)}</pre>`;
      }
      elSourceBody.innerHTML = "";
      elSourceBody.appendChild(iframe);
      elSourceStatusLabel.textContent = `Sandboxed ${fmt.toUpperCase()} preview`;
    } catch (err) {
      elSourceStatusLabel.textContent = `Preview failed: ${err.message}`;
    }
  }

  // Middle tabs & side-by-side layout
  function setMidTab(tab) {
    activeMidTab = tab;
    elTabText.classList.toggle("active", tab === "text");
    elTabText.setAttribute("aria-selected", String(tab === "text"));
    elTabSource.classList.toggle("active", tab === "source");
    elTabSource.setAttribute("aria-selected", String(tab === "source"));
    updateMiddleLayout();
  }

  function updateMiddleLayout() {
    elMidTabGroup.classList.toggle("disabled", sideBySide);
    if (sideBySide) {
      elMiddleSplit.className = "middle-split mode-both";
    } else if (activeMidTab === "source") {
      elMiddleSplit.className = "middle-split mode-source";
    } else {
      elMiddleSplit.className = "middle-split mode-text";
    }
    if (isSourceVisible()) {
      loadSourceForCurrentDoc();
    }
  }

  // Review saving & display
  function renderReviewFooter(key) {
    const latest = getLatestReview(key);
    const history = reviewsByKey.get(key) || [];
    if (!latest) {
      elCurrentReviewBanner.className = "current-review-banner hidden";
      elCurrentReviewBanner.textContent = "";
      elReviewField.value = "";
      elReviewNote.value = "";
      return;
    }

    const isOk = latest.verdict === "label_correct";
    const labelText = isOk ? "✓ Label correct" : "! Needs a fix";
    const fieldPart = latest.field ? ` [${latest.field}]` : "";
    const notePart = latest.note ? ` — ${latest.note}` : "";
    const timeShort = (latest.timestamp || "").replace("T", " ").slice(0, 19);

    elCurrentReviewBanner.className = `current-review-banner ${isOk ? "is-correct" : "is-fix"}`;
    elCurrentReviewBanner.innerHTML =
      `<span><strong>${esc(labelText)}</strong>${esc(fieldPart)}${esc(notePart)}</span>` +
      `<span class="muted-xs">${esc(timeShort)}${history.length > 1 ? ` (${history.length}×)` : ""}</span>`;

    elReviewField.value = latest.field || "";
    elReviewNote.value = latest.note || "";
  }

  async function submitReview(verdict) {
    if (!selectedKey) return;
    const payload = {
      key: selectedKey,
      verdict,
      field: elReviewField.value.trim() || null,
      note: elReviewNote.value.trim() || null,
      timestamp: new Date().toISOString(),
    };

    elSaveFeedback.textContent = "Saving…";
    try {
      const resp = await fetch("/api/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const saved = data.review || payload;

      if (!reviewsByKey.has(saved.key)) reviewsByKey.set(saved.key, []);
      reviewsByKey.get(saved.key).push(saved);

      renderReviewFooter(saved.key);
      updateReviewedSummary();
      renderVirtualList();
      elSaveFeedback.textContent = "Saved ✓";

      if (elChkAutoAdvance.checked) {
        stepDocument(1);
      } else if (elChkUnreviewed.checked || elChkNeedsFix.checked) {
        applyFilters(true);
      }
    } catch (err) {
      elSaveFeedback.textContent = `Save failed: ${err.message}`;
    }
  }

  // Event listeners
  function bindEvents() {
    elViewport.addEventListener("scroll", () => renderVirtualList(), { passive: true });
    window.addEventListener("resize", () => renderVirtualList(), { passive: true });

    elItems.addEventListener("click", (e) => {
      const row = e.target.closest(".doc-row");
      if (row && row.dataset.key) {
        selectDocument(row.dataset.key, { scrollList: false });
      }
    });

    elDocSearch.addEventListener("input", () => applyFilters(true));
    elFilterSplit.addEventListener("change", () => applyFilters(true));
    elFilterFormat.addEventListener("change", () => applyFilters(true));
    elFilterKind.addEventListener("change", () => applyFilters(true));
    elChkOpenFindings.addEventListener("change", () => applyFilters(true));
    elChkNeedsOwner.addEventListener("change", () => applyFilters(true));
    elChkRemoved.addEventListener("change", () => applyFilters(true));
    elChkGt10.addEventListener("change", () => applyFilters(true));
    elChkUnreviewed.addEventListener("change", () => applyFilters(true));
    elChkNeedsFix.addEventListener("change", () => applyFilters(true));
    elChkRulings.addEventListener("change", () => applyFilters(true));

    elBtnResetFilters.addEventListener("click", () => {
      elDocSearch.value = "";
      elFilterSplit.value = "";
      elFilterFormat.value = "";
      elFilterKind.value = "";
      elChkOpenFindings.checked = false;
      elChkNeedsOwner.checked = false;
      elChkRemoved.checked = false;
      elChkGt10.checked = false;
      elChkUnreviewed.checked = false;
      elChkNeedsFix.checked = false;
      elChkRulings.checked = false;
      applyFilters(true);
    });

    elBtnPrevDoc.addEventListener("click", () => stepDocument(-1));
    elBtnNextDoc.addEventListener("click", () => stepDocument(1));

    elBtnToggleSidebar.addEventListener("click", () => {
      elApp.classList.toggle("sidebar-collapsed");
    });

    elTabText.addEventListener("click", () => setMidTab("text"));
    elTabSource.addEventListener("click", () => setMidTab("source"));
    elChkSideBySide.addEventListener("change", () => {
      sideBySide = elChkSideBySide.checked;
      updateMiddleLayout();
    });

    // Find in text
    elFindInput.addEventListener("input", () => {
      highlightInText(elFindInput.value, { fromFindBox: true });
    });
    elFindInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        stepMatch(e.shiftKey ? -1 : 1);
      } else if (e.key === "Escape") {
        elFindInput.value = "";
        highlightInText("", { fromFindBox: true });
        elFindInput.blur();
      }
    });
    elBtnFindPrev.addEventListener("click", () => stepMatch(-1));
    elBtnFindNext.addEventListener("click", () => stepMatch(1));
    elBtnFindClear.addEventListener("click", () => {
      elFindInput.value = "";
      highlightInText("", { fromFindBox: true });
    });

    // Source URL pattern config
    elUrlPatternInput.value = urlPattern;
    elBtnUrlConfig.addEventListener("click", () => {
      elUrlPatternBox.classList.toggle("hidden");
      elUrlPatternInput.value = urlPattern;
    });
    elBtnUrlSave.addEventListener("click", () => {
      urlPattern = elUrlPatternInput.value.trim();
      localStorage.setItem(STORAGE_URL_KEY, urlPattern);
      loadedSourceKey = null;
      if (isSourceVisible()) loadSourceForCurrentDoc();
    });
    elBtnUrlReset.addEventListener("click", () => {
      urlPattern = DEFAULT_URL_PATTERN;
      elUrlPatternInput.value = urlPattern;
      localStorage.removeItem(STORAGE_URL_KEY);
      loadedSourceKey = null;
      if (isSourceVisible()) loadSourceForCurrentDoc();
    });

    // Right pane toggles & click-to-highlight delegation
    elChkRawJson.addEventListener("change", () => {
      rawJsonMode = elChkRawJson.checked;
      elLabelFormView.classList.toggle("hidden", rawJsonMode);
      elLabelRawView.classList.toggle("hidden", !rawJsonMode);
    });

    elDocKeyLabel.addEventListener("click", () => {
      if (!selectedKey) return;
      navigator.clipboard?.writeText(selectedKey);
      const prev = elDocKeyLabel.textContent;
      elDocKeyLabel.textContent = `${selectedKey} (copied)`;
      setTimeout(() => {
        if (elDocKeyLabel.textContent.includes("(copied)")) {
          elDocKeyLabel.textContent = selectedKey;
        }
      }, 900);
    });

    document.getElementById("right-pane").addEventListener("click", (e) => {
      const setFieldEl = e.target.closest("[data-set-field]");
      if (setFieldEl) {
        const f = setFieldEl.getAttribute("data-set-field");
        if (f) {
          elReviewField.value = f;
          elReviewNote.focus();
        }
        return;
      }
      const target = e.target.closest(".clickable-val");
      if (!target) return;
      const searchStr = target.getAttribute("data-search");
      const fieldHint = target.getAttribute("data-field") || "";
      if (searchStr) {
        highlightInText(searchStr, { fromFindBox: false, field: fieldHint });
      }
    });

    // Review controls
    elBtnCorrect.addEventListener("click", () => submitReview("label_correct"));
    elBtnFix.addEventListener("click", () => submitReview("needs_fix"));
    elReviewNote.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        submitReview("needs_fix");
      }
    });

    // Global keyboard shortcuts: j / k (next/prev), 1 / 2 (review), / (search), [ (sidebar)
    document.addEventListener("keydown", (e) => {
      const tag = (e.target && e.target.tagName) || "";
      const inInput = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.target?.isContentEditable;
      if (inInput || e.metaKey || e.ctrlKey || e.altKey) {
        if (e.key === "Escape" && inInput) {
          e.target.blur();
        }
        return;
      }

      if (e.key === "j") {
        e.preventDefault();
        stepDocument(1);
      } else if (e.key === "k") {
        e.preventDefault();
        stepDocument(-1);
      } else if (e.key === "1") {
        e.preventDefault();
        submitReview("label_correct");
      } else if (e.key === "2") {
        e.preventDefault();
        submitReview("needs_fix");
      } else if (e.key === "/") {
        e.preventDefault();
        elDocSearch.focus();
        elDocSearch.select();
      } else if (e.key === "[") {
        e.preventDefault();
        elApp.classList.toggle("sidebar-collapsed");
      } else if (e.key === "Escape") {
        hideMatchBanner();
        if (elFindInput.value) {
          elFindInput.value = "";
          highlightInText("", { fromFindBox: true });
        }
      }
    });
  }

  async function init() {
    bindEvents();
    try {
      const [indexResp, revResp] = await Promise.all([
        fetch("data/index.json"),
        fetch("/api/reviews"),
      ]);
      if (!indexResp.ok) throw new Error(`Failed to load data/index.json (HTTP ${indexResp.status})`);
      allDocs = await indexResp.json();
      for (const d of allDocs) {
        docIndexByKey.set(d.key, d);
      }

      if (revResp.ok) {
        const revList = await revResp.json();
        const items = Array.isArray(revList) ? revList : revList.reviews || [];
        for (const r of items) {
          if (r && r.key) {
            if (!reviewsByKey.has(r.key)) reviewsByKey.set(r.key, []);
            reviewsByKey.get(r.key).push(r);
          }
        }
      }

      populateSelectOptions();

      // Check URL hash #key=...
      const hashMatch = location.hash.match(/key=([0-9a-fA-F]+)/);
      const initialKey = hashMatch && docIndexByKey.has(hashMatch[1]) ? hashMatch[1] : null;
      if (initialKey) {
        selectedKey = initialKey;
        applyFilters(true);
        await selectDocument(initialKey, { scrollList: true });
      } else {
        applyFilters(false);
      }
    } catch (err) {
      elDocText.textContent = `Initialization error: ${err.message}. Did you run build_bundle.py?`;
    }
  }

  init();
})();
