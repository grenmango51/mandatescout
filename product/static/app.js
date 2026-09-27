/**
 * MandateScout — simple client (vanilla ES2017, no build step).
 * API contract: PRODUCT_SPEC.md / product/README.md.
 */

(function () {
  'use strict';

  const EXAMPLES = [
    { label: 'Cloud software', request: 'Find Finnish cloud & devops software companies (sector 62)' },
    { label: 'Industrial machinery', request: 'Find Finnish industrial automation machinery and equipment manufacturers (sector 28)' },
    { label: 'CNC machining', request: 'Find 10 Finnish metal manufacturing companies with CNC machining evidence' },
    { label: 'Cybersecurity', request: 'Find Finnish cybersecurity software firms (sector 62)' }
  ];

  const PREFERRED_EXAMPLE_RUNS = ['run_20260926_203346_d9ab05', 'run_20260927_020133_2514c0'];

  const GHOST_WIDTHS = [72, 54, 80, 62, 48, 70, 58, 66, 50, 76];

  const SESSION_JOB_KEY = 'ms_active_job_id';
  const SESSION_REQ_KEY = 'ms_active_request';
  const SESSION_BUYER_KEY = 'ms_active_buyer_id';

  const state = {
    buyers: [],
    runs: [],
    currentRunId: null,
    currentRunBuyerId: null,
    isSavedRun: false,
    companies: [],
    lastGoodCompanies: [],
    lastGoodRun: null,
    coverageView: 'all', // 'evidence' | 'all'
    currentKeywords: [],
    currentRefinements: [],
    selectedCompanyIds: new Set(),
    activeCompany: null,
    sortField: 'relevance_score',
    sortAsc: false,
    filterText: '',
    isLoading: false,
    hasRun: false,
    notes: [],
    lastFocus: null
  };

  const $ = (id) => document.getElementById(id);

  const el = {
    body: document.body,
    topbarSlot: $('topbar-slot'),
    startSlot: $('start-slot'),
    search: $('search'),
    agentRequestInput: $('agent-request-input'),
    btnAgentResearch: $('btn-agent-research'),
    agentSpinner: $('agent-spinner'),
    agentBtnText: $('agent-btn-text'),
    btnToggleFilters: $('btn-toggle-filters'),
    btnTheme: $('btn-theme'),
    progressLine: $('progress-line'),
    progressFill: $('progress-fill'),

    advancedFiltersPanel: $('advanced-filters-panel'),
    searchForm: $('search-form'),
    buyerSelect: $('buyer-select'),
    buyerCard: $('buyer-card'),
    buyerCardName: $('buyer-card-name'),
    buyerCardUrl: $('buyer-card-url'),
    buyerCardDate: $('buyer-card-date'),
    buyerCardThesis: $('buyer-card-thesis'),
    buyerCriteriaList: $('buyer-criteria-list'),
    searchQuery: $('search-query'),
    industryCode: $('industry-code'),
    limitSelect: $('limit-select'),
    keywordsInput: $('keywords-input'),
    refreshCheckbox: $('refresh-checkbox'),
    btnResetFilters: $('btn-reset-filters'),
    btnRunSearch: $('btn-run-search'),

    startView: $('start-view'),
    exampleList: $('example-list'),
    savedExample: $('saved-example'),
    btnOpenExample: $('btn-open-example'),

    resultsView: $('results-view'),
    agentSpinnerInline: $('agent-spinner-inline'),
    summaryText: $('summary-text'),
    btnNotes: $('btn-notes'),
    notesList: $('notes-list'),

    coverageToggle: $('coverage-toggle'),
    btnViewEvidence: $('btn-view-evidence'),
    btnViewAll: $('btn-view-all'),
    evidenceCountBadge: $('evidence-count-badge'),
    allCountBadge: $('all-count-badge'),

    searchDetails: $('search-details'),
    metaSourceMode: $('meta-source-mode'),
    metaSourceModeVal: $('meta-source-mode-val'),
    metaQueryTime: $('meta-query-time'),
    metaQueryTimeVal: $('meta-query-time-val'),
    metaDuration: $('meta-duration'),
    metaDurationVal: $('meta-duration-val'),
    metaPlanner: $('meta-planner'),
    metaPlannerVal: $('meta-planner-val'),
    metaFilters: $('meta-filters'),
    metaFiltersVal: $('meta-filters-val'),
    metaBuyer: $('meta-buyer'),
    metaBuyerVal: $('meta-buyer-val'),

    selectionInfo: $('selection-info'),
    selectionCounter: $('selection-counter'),
    btnClearSelection: $('btn-clear-selection'),
    tableFilterInput: $('table-filter-input'),
    runsHistorySelect: $('runs-history-select'),
    btnExport: $('btn-export'),
    exportMenu: $('export-menu'),
    exportScope: $('export-scope'),
    btnDownloadBrief: $('btn-download-brief'),
    btnCopyMd: $('btn-copy-md'),
    btnExportCsv: $('btn-export-csv'),
    briefNotes: $('brief-notes'),
    followupRow: $('followup-row'),
    followupChipsContainer: $('followup-chips-container'),

    gridViewport: $('grid-viewport'),
    resultsTable: $('results-table'),
    resultsTbody: $('results-tbody'),
    headerSelectAll: $('header-select-all'),

    btnHow: $('btn-how'),
    apiStatusBadge: $('api-status-badge'),
    alertContainer: $('alert-container'),

    drawerBackdrop: $('drawer-backdrop'),
    evidenceDrawer: $('evidence-drawer'),
    drawerCompanyName: $('drawer-company-name'),
    drawerSubtitle: $('drawer-subtitle'),
    drawerExclusionBox: $('drawer-exclusion-box'),
    drawerExclusionText: $('drawer-exclusion-text'),
    drawerEvidenceList: $('drawer-evidence-list'),
    drawerMatchedKeywords: $('drawer-matched-keywords'),
    drawerMissingCriteria: $('drawer-missing-criteria'),
    drawerBusinessId: $('drawer-business-id'),
    drawerLegalForm: $('drawer-legal-form'),
    drawerStatus: $('drawer-status'),
    drawerIndustry: $('drawer-industry'),
    drawerWebsiteUrl: $('drawer-website-url'),
    drawerWebsiteBadge: $('drawer-website-badge'),
    drawerWebsiteTime: $('drawer-website-time'),
    drawerRegistryUrl: $('drawer-registry-url'),
    drawerRegistryTime: $('drawer-registry-time'),
    btnCloseDrawer: $('btn-close-drawer'),
    btnDrawerClose: $('btn-drawer-close'),
    btnDrawerSelectToggle: $('btn-drawer-select-toggle'),

    howSheet: $('how-sheet'),
    btnCloseHow: $('btn-close-how'),
    benchmarkBody: $('benchmark-body')
  };

  /* ────────────────────────────────────────────────────────────────────────
     Utilities
     ──────────────────────────────────────────────────────────────────────── */

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function icon(name, cls) {
    return `<svg class="icon${cls ? ' ' + cls : ''}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  }

  function plural(n, one, many) {
    return `${n} ${n === 1 ? one : (many || one + 's')}`;
  }

  function domainOf(url) {
    return url ? String(url).replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/.*$/, '') : '';
  }

  function titleCase(text) {
    if (!text) return '';
    return String(text).toLowerCase().replace(/(^|[\s-])(\S)/g, (m, sep, ch) => sep + ch.toUpperCase());
  }

  function formatDate(value) {
    const d = new Date(value);
    if (isNaN(d)) return '';
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function websiteState(status) {
    if (status === 'fetched') return { dot: 'dot-ok', label: 'Website read' };
    if (status === 'unavailable') return { dot: 'dot-warn', label: 'Website could not be opened' };
    return { dot: '', label: 'No website on record' };
  }

  function wordCounts(company) {
    const hit = Array.isArray(company.matched_keywords) ? company.matched_keywords.length : 0;
    const miss = Array.isArray(company.missing_criteria) ? company.missing_criteria.length : 0;
    return { hit, total: hit + miss };
  }

  function isTypingTarget(target) {
    if (!target) return false;
    const tag = target.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
  }

  function openModal() {
    if (!el.evidenceDrawer.classList.contains('hidden')) return el.evidenceDrawer;
    if (!el.howSheet.classList.contains('hidden')) return el.howSheet;
    return null;
  }

  function triggerDownload(content, mime, filename) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    if (!ok) throw new Error('Copying is not available in this browser.');
  }

  /* ────────────────────────────────────────────────────────────────────────
     Toasts (confirmations and errors only; warnings become inline notes)
     ──────────────────────────────────────────────────────────────────────── */

  function showAlert(message, type) {
    type = type || 'error';
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.innerHTML = `
      <span class="toast-dot" aria-hidden="true"></span>
      <div class="toast-title">${escapeHtml(message)}</div>
      <button type="button" class="toast-close" aria-label="Dismiss">${icon('x', 'icon-xs')}</button>`;
    toast.querySelector('.toast-close').addEventListener('click', () => toast.remove());
    el.alertContainer.appendChild(toast);
    while (el.alertContainer.children.length > 3) el.alertContainer.firstElementChild.remove();
    const ttl = type === 'success' ? 4000 : type === 'warning' ? 8000 : 0;
    if (ttl) setTimeout(() => { if (toast.parentElement) toast.remove(); }, ttl);
  }

  function clearAlerts() {
    el.alertContainer.innerHTML = '';
  }

  /* ────────────────────────────────────────────────────────────────────────
     Modes
     ──────────────────────────────────────────────────────────────────────── */

  function setMode(mode) {
    const results = mode === 'results';
    el.body.classList.toggle('mode-start', !results);
    el.startView.classList.toggle('hidden', results);
    el.resultsView.classList.toggle('hidden', !results);
    const slot = results ? el.topbarSlot : el.startSlot;
    if (el.search.parentElement !== slot) slot.appendChild(el.search);
  }

  /* ────────────────────────────────────────────────────────────────────────
     Health, buyers, saved runs
     ──────────────────────────────────────────────────────────────────────── */

  function setStatus(ok, label, title) {
    el.apiStatusBadge.classList.toggle('is-ok', ok);
    el.apiStatusBadge.classList.toggle('is-warn', !ok);
    el.apiStatusBadge.textContent = label || (ok ? 'Connected' : 'Server not reachable');
    el.apiStatusBadge.title = title || (ok ? 'The local server is running' : 'Start the server with Start-MandateScout.cmd');
  }

  async function apiFetch(url, options) {
    try {
      const res = await fetch(url, options);
      setStatus(true);
      return res;
    } catch (err) {
      setStatus(false, 'Server not reachable', 'Network connection to the server failed');
      throw err;
    }
  }

  async function checkHealth() {
    try {
      const res = await fetch('/api/health');
      const data = res.ok ? await res.json() : null;
      const ok = !!(data && data.ok);
      setStatus(ok);
      return ok;
    } catch (_) {
      setStatus(false, 'Server not reachable', 'Start the server with Start-MandateScout.cmd');
      return false;
    }
  }

  async function loadBuyers() {
    try {
      const res = await apiFetch('/api/buyers');
      if (!res.ok) return;
      const data = await res.json();
      state.buyers = data.buyers || [];
      el.buyerSelect.innerHTML = '<option value="">None</option>';
      state.buyers.forEach(buyer => {
        const opt = document.createElement('option');
        opt.value = buyer.id;
        opt.textContent = buyer.status === 'unavailable' ? `${buyer.name} (unavailable)` : buyer.name;
        opt.disabled = buyer.status === 'unavailable';
        el.buyerSelect.appendChild(opt);
      });
    } catch (err) {
      console.warn('Buyer profiles could not be loaded:', err.message);
    }
  }

  function showBuyer(buyer) {
    if (!buyer || buyer.status === 'unavailable') {
      el.buyerCard.classList.add('hidden');
      return;
    }
    el.buyerCardName.textContent = buyer.name;
    el.buyerCardUrl.href = buyer.source_url || '#';
    el.buyerCardUrl.classList.toggle('hidden', !buyer.source_url);

    if (el.buyerCardDate) {
      el.buyerCardDate.textContent = buyer.retrieved_at ? '· Checked ' + formatDate(buyer.retrieved_at) : '';
    }
    if (el.buyerCardThesis) {
      const thesisText = buyer.assumptions_note || (buyer.criteria && buyer.criteria[0] && buyer.criteria[0].source_excerpt) || '';
      el.buyerCardThesis.textContent = thesisText;
      el.buyerCardThesis.classList.toggle('hidden', !thesisText);
    }

    el.buyerCriteriaList.innerHTML = '';
    (buyer.criteria || []).forEach(crit => {
      const span = document.createElement('span');
      span.className = 'tag';
      span.textContent = crit.label || crit.source_excerpt || crit.id;
      span.title = crit.source_excerpt || '';
      el.buyerCriteriaList.appendChild(span);
    });
    el.buyerCard.classList.remove('hidden');
  }

  function onBuyerChange() {
    const buyer = state.buyers.find(b => b.id === el.buyerSelect.value) || null;
    showBuyer(buyer);
    if (!buyer || buyer.status === 'unavailable') return;
    if (buyer.keywords && buyer.keywords.length) el.keywordsInput.value = buyer.keywords.join(', ');
    if (buyer.industry_codes && buyer.industry_codes.length) el.industryCode.value = buyer.industry_codes[0];
  }

  async function loadRunsHistory() {
    try {
      const res = await fetch('/api/runs');
      if (!res.ok) return;
      const data = await res.json();
      state.runs = (data.runs || []).filter(r => r.run_id && r.count > 0);
      el.runsHistorySelect.innerHTML = '<option value="">Past searches</option>';
      state.runs.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r.run_id;
        const what = r.query ? `“${r.query}”` : 'Industry search';
        const when = formatDate(r.queried_at);
        opt.textContent = `${what} · ${plural(r.count, 'company', 'companies')}${when ? ' · ' + when : ''}`;
        el.runsHistorySelect.appendChild(opt);
      });
      el.savedExample.classList.toggle('hidden', state.runs.length === 0);
    } catch (_) {}
  }

  function pickExampleRun() {
    for (const id of PREFERRED_EXAMPLE_RUNS) {
      if (state.runs.some(r => r.run_id === id)) return id;
    }
    return state.runs.length ? state.runs[0].run_id : null;
  }

  /* ────────────────────────────────────────────────────────────────────────
     Progress
     ──────────────────────────────────────────────────────────────────────── */

  function friendlyStage(stage, message) {
    switch (stage) {
      case 'planning': return 'Understanding your request…';
      case 'prh_search': return 'Searching the Finnish company register…';
      case 'website_enrichment': {
        const m = /for (.+?)\.{0,3}$/.exec(message || '');
        return m ? `Reading company websites… ${m[1]}` : 'Reading company websites…';
      }
      case 'scoring': return 'Checking what we found…';
      case 'completed': return 'Done';
      default: return 'Working…';
    }
  }

  function setProgress(pct, text) {
    el.progressLine.classList.remove('hidden');
    el.progressFill.style.width = `${pct}%`;
    el.agentSpinnerInline.classList.remove('hidden');
    el.summaryText.textContent = text;
  }

  function hideProgress() {
    el.agentSpinnerInline.classList.add('hidden');
    el.progressFill.style.width = '100%';
    setTimeout(() => {
      if (state.isLoading) return;
      el.progressLine.classList.add('hidden');
      el.progressFill.style.width = '0';
    }, 600);
  }

  function setLoading(loading) {
    state.isLoading = loading;
    el.btnAgentResearch.disabled = loading;
    el.btnRunSearch.disabled = loading;
    el.agentSpinner.classList.toggle('hidden', !loading);
    el.agentBtnText.textContent = loading ? 'Searching' : 'Search';
    el.exampleList.querySelectorAll('button').forEach(b => { b.disabled = loading; });
    el.followupChipsContainer.querySelectorAll('button').forEach(b => { b.disabled = loading; });
    if (loading) {
      closeExportMenu();
      setNotes([]);
      renderGhostRows(10);
    }
    syncSelectionUI();
  }

  /* ────────────────────────────────────────────────────────────────────────
     Summary, notes, follow-ups
     ──────────────────────────────────────────────────────────────────────── */

  function industryPhrase(code) {
    const counts = {};
    state.companies.forEach(c => {
      if (c.industry_label) counts[c.industry_label] = (counts[c.industry_label] || 0) + 1;
    });
    const top = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0];
    if (top) return top.toLowerCase();
    return code ? `industry ${code}` : '';
  }

  function updateCoverageBadges() {
    const total = state.companies.length;
    const matched = state.companies.filter(c => wordCounts(c).hit > 0).length;
    if (el.evidenceCountBadge) el.evidenceCountBadge.textContent = String(matched);
    if (el.allCountBadge) el.allCountBadge.textContent = String(total);
    if (el.btnViewEvidence) el.btnViewEvidence.classList.toggle('is-active', state.coverageView === 'evidence');
    if (el.btnViewAll) el.btnViewAll.classList.toggle('is-active', state.coverageView === 'all');
  }

  function renderSummary(opts) {
    opts = opts || {};
    const total = state.companies.length;
    if (total === 0) {
      el.summaryText.innerHTML = opts.isRestored
        ? '<strong>Search failed.</strong> Retained previous results.'
        : '<strong>No companies found.</strong> Try a broader description or industry code.';
      updateCoverageBadges();
      return;
    }
    const read = state.companies.filter(c => c.website_status === 'fetched').length;
    const matched = state.companies.filter(c => wordCounts(c).hit > 0).length;
    const savedDate = opts.savedAt ? formatDate(opts.savedAt) : '';
    const saved = opts.savedAt ? ` <span class="muted">· Saved${savedDate ? ' ' + escapeHtml(savedDate) : ''}</span>` : '';
    const restoredNote = opts.isRestored ? ' <span class="pill pill-warn">Retained previous results</span>' : '';

    const hasKw = state.currentKeywords && state.currentKeywords.length > 0;
    if (hasKw) {
      if (state.coverageView === 'evidence') {
        el.summaryText.innerHTML =
          `Showing <strong>${escapeHtml(plural(matched, 'evidence-positive company', 'evidence-positive companies'))}</strong> of ${total} reviewed` +
          ` · ${read} websites read${saved}${restoredNote}`;
      } else {
        el.summaryText.innerHTML =
          `Showing all <strong>${escapeHtml(plural(total, 'reviewed company', 'reviewed companies'))}</strong>` +
          ` · ${matched} with evidence · ${read} websites read${saved}${restoredNote}`;
      }
    } else {
      el.summaryText.innerHTML =
        `Showing <strong>${escapeHtml(plural(total, 'company', 'companies'))}</strong>` +
        ` · ${read} websites read${saved}${restoredNote}`;
    }
    el.summaryText.title = industryPhrase(opts.industryCode);
    updateCoverageBadges();
  }

  function renderSearchDetails(data) {
    if (!data || !el.searchDetails) return;
    const mode = (data.source_mode || 'live').toLowerCase();
    el.metaSourceModeVal.textContent = mode.toUpperCase();
    el.metaSourceMode.className = `detail-chip ${mode === 'live' ? 'detail-badge-live' : mode === 'cached' ? 'detail-badge-cached' : 'detail-badge-mixed'}`;

    const qDate = data.queried_at && data.queried_at !== 'unknown' ? formatDate(data.queried_at) : 'Active search';
    el.metaQueryTimeVal.textContent = qDate;

    const stats = data.stats || {};
    const dur = stats.elapsed_seconds !== undefined
      ? `${stats.elapsed_seconds}s`
      : data.elapsed_seconds !== undefined
        ? `${data.elapsed_seconds}s`
        : data.elapsed_ms !== undefined
          ? `${(data.elapsed_ms / 1000).toFixed(1)}s`
          : '—';
    el.metaDurationVal.textContent = dur;

    // Planner label / fallback without stale planner claims
    let plannerText = 'None (direct search)';
    if (data.planner) {
      plannerText = data.planner.planner_label || 'Deterministic Rule-Based Planner';
      if (data.planner.blocker_reported) {
        plannerText += ' (Fallback)';
      }
    } else if (stats.planner_mode && stats.planner_mode !== 'None (Direct Search)') {
      plannerText = stats.planner_mode;
    }
    el.metaPlannerVal.textContent = plannerText;

    // Actual request / filters
    const filterParts = [];
    if (data.query) filterParts.push(`"${data.query}"`);
    if (data.industry_code) filterParts.push(`sector ${data.industry_code}`);
    if (data.keywords && data.keywords.length) filterParts.push(`keywords: ${data.keywords.join(', ')}`);
    const lim = data.limit || (data.planner && data.planner.limit) || (data.companies ? data.companies.length : 10);
    filterParts.push(`limit ${lim}`);
    const scannedCount = stats.scanned_companies || stats.scanned || stats.companies_found;
    if (scannedCount) filterParts.push(`${scannedCount} pool candidates`);
    el.metaFiltersVal.textContent = filterParts.join(' · ') || '—';

    // Buyer source date & thesis
    if (data.buyer_id) {
      const b = state.buyers.find(x => x.id === data.buyer_id);
      if (b) {
        const bDate = b.retrieved_at ? ` · Source: ${formatDate(b.retrieved_at)}` : '';
        el.metaBuyerVal.textContent = `${b.name}${bDate}`;
        el.metaBuyer.classList.remove('hidden');
      } else {
        el.metaBuyerVal.textContent = data.buyer_id;
        el.metaBuyer.classList.remove('hidden');
      }
    } else {
      el.metaBuyer.classList.add('hidden');
    }

    el.searchDetails.classList.remove('hidden');
  }

  // Backend warnings are written for analysts; restate the known ones in plain words.
  function plainNote(text) {
    let m = /^Query term '(.+?)' matched against PRH registered trade names/.exec(text);
    if (m) return `Only company names containing “${m[1]}” were searched. Companies with other names are not included.`;
    m = /^Official PRH classification filter applied: mainBusinessLine=([^.\s]+)/.exec(text);
    if (m) return `Only companies registered under industry code ${m[1]} were included. The code is our best guess from your description.`;
    m = /^Live PRH query failed .*?cache from (.+?)\.?$/.exec(text);
    if (m) return `The company register could not be reached, so saved data from ${formatDate(m[1]) || m[1]} is shown.`;
    return String(text).replace(/\bPRH\b/g, 'the company register');
  }

  function setNotes(notes) {
    state.notes = notes.filter(Boolean).map(plainNote);
    el.notesList.innerHTML = state.notes.map(n => `<li>${escapeHtml(n)}</li>`).join('');
    const n = state.notes.length;
    el.btnNotes.classList.toggle('hidden', n === 0);
    el.btnNotes.textContent = n === 1 ? '1 note' : `${n} notes`;
    el.btnNotes.setAttribute('aria-expanded', 'false');
    el.notesList.classList.add('hidden');
  }

  function flagNotes() {
    const flagged = state.companies.filter(c => c.excluded_reason || c.corporate_change_flag).length;
    return flagged
      ? [`${plural(flagged, 'company mentions', 'companies mention')} a merger or acquisition on its website. Check who owns it before pitching.`]
      : [];
  }

  function setFollowups(items, baseRequest) {
    // Obsolete consultancy code mapping: 62200 -> 62020, 70200 -> 70220
    const sanitized = (items || []).map(t =>
      String(t).replace(/62200/g, '62020').replace(/70200/g, '70220')
    );
    state.currentRefinements = sanitized;

    el.followupChipsContainer.innerHTML = '';
    sanitized.forEach(text => {
      const clean = text.replace(/^Refine:\s*/i, '');
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'followup';
      chip.textContent = clean;
      chip.title = clean;
      chip.addEventListener('click', () => {
        const currentReq = el.agentRequestInput.value.trim() || baseRequest;
        const fullRequest = `${currentReq}\nRefinement: ${clean}`;
        el.agentRequestInput.value = fullRequest;
        runAgentResearch(fullRequest);
      });
      el.followupChipsContainer.appendChild(chip);
    });
    el.followupRow.classList.toggle('hidden', el.followupChipsContainer.children.length === 0);
  }

  function applyRun(companies, runId, buyerId, saved, runData) {
    state.companies = Array.isArray(companies) ? companies : [];
    state.lastGoodCompanies = state.companies.slice();
    state.lastGoodRun = {
      companies: state.companies.slice(),
      runId: runId || null,
      buyerId: buyerId || null,
      saved: !!saved,
      runData: runData || null,
      keywords: state.currentKeywords.slice()
    };
    state.currentRunId = runId || null;
    state.currentRunBuyerId = buyerId || null;
    state.isSavedRun = !!saved;
    state.selectedCompanyIds.clear();
    state.filterText = '';
    el.tableFilterInput.value = '';
    state.hasRun = true;
    updateCoverageBadges();
  }

  /* ────────────────────────────────────────────────────────────────────────
     Research
     ──────────────────────────────────────────────────────────────────────── */

  function handleSearchError(err) {
    console.error('Search error:', err);
    state.hasRun = true;
    if (state.lastGoodCompanies && state.lastGoodCompanies.length > 0) {
      state.companies = state.lastGoodCompanies;
      renderSummary({ isRestored: true });
      showAlert(`${err.message || 'Search failed.'} Previous results retained.`, 'warning');
    } else {
      state.companies = [];
      el.summaryText.innerHTML = '<strong>The search did not finish.</strong> ' + escapeHtml(err.message || '');
      showAlert(err.message || 'Something went wrong during the search.', 'error');
    }
  }

  async function pollJob(jobId, requestText, buyerId) {
    const startTime = Date.now();
    const MAX_DURATION_MS = 120000; // 120s bounded polling timeout
    const MAX_CONSECUTIVE_ERRORS = 6; // Bounded retry count
    let consecutiveErrors = 0;
    let job = null;

    while (true) {
      if (Date.now() - startTime > MAX_DURATION_MS) {
        sessionStorage.removeItem(SESSION_JOB_KEY);
        throw new Error('Search polling timed out after 2 minutes. The server is still processing the job.');
      }

      await new Promise(r => setTimeout(r, 700));

      let pollRes;
      try {
        pollRes = await fetch(`/api/agent/job?job_id=${encodeURIComponent(jobId)}`);
        setStatus(true);
      } catch (netErr) {
        consecutiveErrors++;
        setStatus(false, 'Reconnecting…', 'Network connection interrupted');
        if (consecutiveErrors <= MAX_CONSECUTIVE_ERRORS) {
          setProgress(
            Math.min(95, 20 + consecutiveErrors * 10),
            `Network glitch. Reconnecting to search (attempt ${consecutiveErrors}/${MAX_CONSECUTIVE_ERRORS})…`
          );
          await new Promise(r => setTimeout(r, Math.min(3000, 1000 * consecutiveErrors)));
          continue;
        }
        throw new Error('Lost connection to the local server. Polling paused.');
      }

      if (!pollRes.ok) {
        if (pollRes.status >= 500) {
          consecutiveErrors++;
          if (consecutiveErrors <= MAX_CONSECUTIVE_ERRORS) {
            await new Promise(r => setTimeout(r, 1000 * consecutiveErrors));
            continue;
          }
        }
        sessionStorage.removeItem(SESSION_JOB_KEY);
        throw new Error(`Lost track of the search (error ${pollRes.status}).`);
      }

      consecutiveErrors = 0;
      job = await pollRes.json();

      if (job.status === 'completed') {
        sessionStorage.removeItem(SESSION_JOB_KEY);
        break;
      }
      if (job.status === 'failed') {
        sessionStorage.removeItem(SESSION_JOB_KEY);
        throw new Error(job.error || 'The search failed.');
      }
      setProgress(Math.min(95, Math.max(8, job.progress_pct || 10)), friendlyStage(job.stage, job.stage_message));
    }

    // Process completed job
    const results = job.results || {};
    const plan = job.plan || {};
    const companies = (results.reviewed_companies && results.reviewed_companies.length > 0)
      ? results.reviewed_companies
      : (results.companies || []);
    state.currentKeywords = plan.keywords || results.keywords || [];

    // Default view: evidence-positive only when keywords exist
    state.coverageView = (state.currentKeywords && state.currentKeywords.length > 0) ? 'evidence' : 'all';

    applyRun(companies, results.run_id, buyerId, false, results);

    el.searchQuery.value = plan.query || '';
    el.industryCode.value = plan.industry_code || '';
    el.keywordsInput.value = (plan.keywords || []).join(', ');
    el.limitSelect.value = String(plan.limit || 10);

    const searchDetailsData = {
      source_mode: results.source_mode || 'live',
      queried_at: results.queried_at || new Date().toISOString(),
      elapsed_seconds: job.elapsed_seconds || (results.stats && results.stats.elapsed_seconds),
      elapsed_ms: results.elapsed_ms,
      planner: plan,
      query: plan.query,
      industry_code: plan.industry_code,
      keywords: plan.keywords,
      limit: plan.limit || 10,
      request: requestText,
      buyer_id: buyerId
    };
    renderSearchDetails(searchDetailsData);

    renderSummary({ industryCode: plan.industry_code });
    setNotes([].concat(
      results.warnings || [],
      plan.blocker_reported ? ['The AI assistant was unavailable, so built-in rules chose the search terms.'] : [],
      flagNotes()
    ));

    setFollowups(plan.followup_refinements, requestText);
    loadRunsHistory();
  }

  async function runAgentResearch(customText) {
    if (state.isLoading) return;
    clearAlerts();

    const requestText = (typeof customText === 'string' ? customText : el.agentRequestInput.value).trim();
    if (!requestText) {
      el.agentRequestInput.focus();
      el.agentRequestInput.placeholder = 'Type what you are looking for, or pick an example below';
      return;
    }
    // Keep full request text visible in input
    el.agentRequestInput.value = requestText;
    const buyerId = el.buyerSelect.value || null;

    setMode('results');
    state.lastGoodCompanies = state.companies.slice();
    setLoading(true);
    setProgress(8, friendlyStage('planning'));

    try {
      const initRes = await apiFetch('/api/agent/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request: requestText, buyer_id: buyerId, refresh: el.refreshCheckbox.checked })
      });

      let jobId = null;
      if (initRes.status === 409) {
        // Reconnect to existing ongoing job
        const e = await initRes.json();
        jobId = e.active_job_id;
        if (!jobId) throw new Error(e.error || 'Another search is in progress.');
        showAlert(`Connected to ongoing research job (${jobId}).`, 'info');
      } else if (!initRes.ok) {
        let msg = `The search could not start (error ${initRes.status}).`;
        try {
          const e = await initRes.json();
          if (e.error) msg = e.error;
        } catch (_) {}
        throw new Error(msg);
      } else {
        const body = await initRes.json();
        jobId = body.job_id;
      }

      sessionStorage.setItem(SESSION_JOB_KEY, jobId);
      sessionStorage.setItem(SESSION_REQ_KEY, requestText);
      sessionStorage.setItem(SESSION_BUYER_KEY, buyerId || '');

      await pollJob(jobId, requestText, buyerId);

    } catch (err) {
      handleSearchError(err);
    } finally {
      setLoading(false);
      hideProgress();
      renderResults();
    }
  }

  async function runSearch() {
    if (state.isLoading) return;
    clearAlerts();

    const query = el.searchQuery.value.trim();
    const keywords = el.keywordsInput.value.split(',').map(k => k.trim()).filter(Boolean);
    const industryCode = el.industryCode.value.trim();
    const limit = parseInt(el.limitSelect.value, 10) || 10;
    const buyerId = el.buyerSelect.value || null;

    if (!query && !industryCode && keywords.length === 0) {
      showAlert('Fill in a company name, an industry code or some words first.', 'warning');
      return;
    }

    setMode('results');
    state.lastGoodCompanies = state.companies.slice();
    setLoading(true);
    setProgress(30, 'Searching the register and reading websites…');

    try {
      const response = await apiFetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ buyer_id: buyerId, query, keywords, industry_code: industryCode, limit, refresh: el.refreshCheckbox.checked })
      });
      if (!response.ok) {
        let msg = `The search failed (error ${response.status}).`;
        try {
          const e = await response.json();
          if (e.error) msg = e.details ? `${e.error}: ${e.details}` : e.error;
        } catch (_) {}
        throw new Error(msg);
      }
      const data = await response.json();
      const companies = (data.reviewed_companies && data.reviewed_companies.length > 0)
        ? data.reviewed_companies
        : (data.companies || []);
      state.currentKeywords = keywords;
      state.coverageView = (keywords.length > 0) ? 'evidence' : 'all';

      applyRun(companies, data.run_id, buyerId, false, data);

      const searchDetailsData = {
        source_mode: data.source_mode || 'live',
        queried_at: data.queried_at || new Date().toISOString(),
        elapsed_seconds: data.stats && data.stats.elapsed_seconds,
        elapsed_ms: data.elapsed_ms,
        planner: null, // No stale planner claim
        query,
        industry_code: industryCode,
        keywords,
        limit,
        request: data.request || `${query} (Sector ${industryCode})`,
        buyer_id: buyerId
      };
      renderSearchDetails(searchDetailsData);

      renderSummary({ industryCode });
      setNotes([].concat(data.warnings || [], flagNotes()));
      loadRunsHistory();
    } catch (err) {
      handleSearchError(err);
    } finally {
      setLoading(false);
      hideProgress();
      renderResults();
    }
  }

  async function openSavedRun(runId) {
    if (!runId || state.isLoading) return;
    clearAlerts();
    closeExportMenu();
    try {
      const res = await apiFetch(`/api/run?run_id=${encodeURIComponent(runId)}`);
      if (!res.ok) throw new Error('That saved search could not be found.');
      const data = await res.json();

      const companies = (data.reviewed_companies && data.reviewed_companies.length > 0)
        ? data.reviewed_companies
        : (data.companies || []);
      state.currentKeywords = data.keywords || [];
      state.coverageView = (state.currentKeywords.length > 0) ? 'evidence' : 'all';

      applyRun(companies, data.run_id || runId, data.buyer_id, true, data);
      el.searchQuery.value = data.query || '';
      el.buyerSelect.value = data.buyer_id || '';
      showBuyer(state.buyers.find(b => b.id === data.buyer_id) || null);
      // Buyer presets must not overwrite the saved run's actual search inputs.
      el.industryCode.value = data.industry_code || '';
      el.keywordsInput.value = (data.keywords || []).join(', ');

      // Restore saved limit and request
      const savedLimit = data.limit || (data.planner && data.planner.limit) || (companies ? companies.length : 10);
      el.limitSelect.value = String(savedLimit);

      const request = data.request || data.original_request || (data.planner && data.planner.request) || data.query || '';
      el.agentRequestInput.value = request;

      setMode('results');
      setFollowups(data.planner ? data.planner.followup_refinements : [], request);

      const searchDetailsData = {
        source_mode: data.source_mode || 'cached',
        queried_at: data.queried_at || 'unknown',
        elapsed_seconds: data.stats && data.stats.elapsed_seconds,
        elapsed_ms: data.elapsed_ms,
        planner: data.planner || null, // No stale planner claim
        query: data.query,
        industry_code: data.industry_code,
        keywords: data.keywords,
        limit: savedLimit,
        request: request,
        buyer_id: data.buyer_id
      };
      renderSearchDetails(searchDetailsData);

      renderSummary({ industryCode: data.industry_code, savedAt: data.queried_at || 'unknown' });
      setNotes([].concat(data.warnings || [], flagNotes()));
      el.runsHistorySelect.value = '';
      renderResults();
    } catch (err) {
      showAlert(err.message, 'error');
    }
  }

  /* ────────────────────────────────────────────────────────────────────────
     Table
     ──────────────────────────────────────────────────────────────────────── */

  function renderExamples() {
    el.exampleList.innerHTML = '';
    EXAMPLES.forEach(ex => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'example';
      btn.title = ex.request;
      btn.innerHTML = `${escapeHtml(ex.label)}${icon('arrow')}`;
      btn.addEventListener('click', () => {
        el.buyerSelect.value = '';
        showBuyer(null);
        el.agentRequestInput.value = ex.request;
        runAgentResearch(ex.request);
      });
      el.exampleList.appendChild(btn);
    });
  }

  function renderGhostRows(count) {
    const rows = [];
    for (let i = 0; i < count; i++) {
      const w = GHOST_WIDTHS[i % GHOST_WIDTHS.length];
      rows.push(`
        <tr class="ghost-row" aria-hidden="true">
          <td><span class="sk sk-box"></span></td>
          <td><span class="sk" style="width:${w}%"></span></td>
          <td><span class="sk" style="width:${100 - w / 2}%"></span></td>
          <td><span class="sk" style="width:60%"></span></td>
          <td><span class="sk" style="width:${w}%"></span></td>
          <td><span class="sk" style="width:70%"></span></td>
          <td></td>
        </tr>`);
    }
    el.resultsTbody.innerHTML = rows.join('');
    el.gridViewport.classList.add('is-loading');
  }

  function messageRow(title, body) {
    return `<tr class="message-row"><td colspan="7"><div class="message"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(body)}</span></div></td></tr>`;
  }

  function updateSortIndicators() {
    el.resultsTable.querySelectorAll('th.sortable').forEach(th => {
      const active = th.dataset.sort === state.sortField;
      th.setAttribute('aria-sort', active ? (state.sortAsc ? 'ascending' : 'descending') : 'none');
    });
  }

  function getDisplayList() {
    const filter = state.filterText.trim().toLowerCase();
    let list = state.companies;
    if (state.coverageView === 'evidence') {
      list = list.filter(c => wordCounts(c).hit > 0);
    }
    if (filter) {
      list = list.filter(c => {
        return [c.name, c.business_id, c.city, c.industry_code, c.industry_label, c.website]
          .map(v => (v || '').toLowerCase()).join(' ').includes(filter);
      });
    }
    list = list.slice();
    list.sort((a, b) => {
      let va = a[state.sortField];
      let vb = b[state.sortField];
      if (va === null || va === undefined) va = '';
      if (vb === null || vb === undefined) vb = '';
      if (typeof va === 'number' && typeof vb === 'number') return state.sortAsc ? va - vb : vb - va;
      return state.sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
    });
    return list;
  }

  function matchCell(company) {
    const ws = company.website_status;
    if (ws === 'no_website') {
      return '<span class="match-text is-zero" title="No registered website on record to evaluate words">— (No website)</span>';
    }
    if (ws === 'unavailable') {
      return '<span class="match-text is-warn" title="Website could not be opened; keyword matches not evaluated"><span class="dot dot-warn" aria-hidden="true"></span>Unread</span>';
    }
    const { hit, total } = wordCounts(company);
    if (total === 0) return '<span class="match-text is-zero">—</span>';
    const bars = [];
    for (let i = 0; i < Math.min(total, 6); i++) bars.push(`<span class="${i < hit ? 'on' : ''}"></span>`);
    const isZero = hit === 0;
    const titleText = isZero
      ? `Website was read: 0 of ${total} search words found`
      : `${hit} of ${total} search words appear on the website. This does not measure buyer fit.`;
    return `
      <div class="cell-match" title="${escapeHtml(titleText)}">
        <span class="match-bar" aria-hidden="true">${bars.join('')}</span>
        <span class="match-text${isZero ? ' is-zero' : ''}">${hit} of ${total}</span>
      </div>`;
  }

  function webCell(company) {
    const ws = websiteState(company.website_status);
    const domain = domainOf(company.website);
    const retDate = company.website_retrieved_at ? formatDate(company.website_retrieved_at) : '';
    const title = retDate ? `${ws.label} · Checked ${retDate}` : ws.label;
    const inner = domain
      ? `<a href="${escapeHtml(company.website)}" target="_blank" rel="noopener noreferrer">${escapeHtml(domain)}</a>`
      : '<span class="muted">None</span>';
    return `<div class="cell-web" title="${escapeHtml(title)}"><span class="dot ${ws.dot}" aria-label="${escapeHtml(ws.label)}"></span>${inner}</div>`;
  }

  function renderResults() {
    updateSortIndicators();
    el.gridViewport.classList.remove('is-loading');
    if (!state.hasRun) {
      el.resultsTbody.innerHTML = '';
      syncSelectionUI();
      return;
    }

    const list = getDisplayList();
    if (list.length === 0) {
      if (state.companies.length === 0) {
        el.resultsTbody.innerHTML = messageRow('No companies to show', 'Try describing the business more broadly, or pick one of the examples.');
      } else if (state.coverageView === 'evidence' && !state.filterText) {
        el.resultsTbody.innerHTML = messageRow(
          'No keyword matches found on websites',
          `None of the ${state.companies.length} reviewed companies had search words on their website. Click "All candidates" above to inspect all reviewed companies.`
        );
      } else {
        el.resultsTbody.innerHTML = messageRow('Nothing matches your filter', 'Clear the filter box to see companies.');
      }
      syncSelectionUI();
      return;
    }

    const frag = document.createDocumentFragment();
    list.forEach(company => {
      const tr = document.createElement('tr');
      tr.className = 'data-row';
      tr.tabIndex = 0;
      tr.dataset.id = company.business_id;
      const flagged = company.excluded_reason || company.corporate_change_flag;
      const industry = company.industry_label || (company.industry_code ? `Industry ${company.industry_code}` : '—');

      tr.innerHTML = `
        <td><input type="checkbox" class="row-select-checkbox" aria-label="Select ${escapeHtml(company.name)}"></td>
        <td>
          <div class="cell-company">
            <span class="company-name" title="${escapeHtml(company.name)}">${escapeHtml(company.name)}</span>
            ${flagged ? '<span class="pill pill-flag" title="The website mentions a merger or acquisition"><i></i>Check ownership</span>' : ''}
          </div>
        </td>
        <td class="cell-industry" title="${escapeHtml(industry)}${company.industry_code ? ' (' + escapeHtml(company.industry_code) + ')' : ''}">${escapeHtml(industry)}</td>
        <td class="${company.city ? '' : 'cell-muted'}">${escapeHtml(titleCase(company.city) || '—')}</td>
        <td>${webCell(company)}</td>
        <td>${matchCell(company)}</td>
        <td><button type="button" class="open-btn" aria-label="Open details for ${escapeHtml(company.name)}">${icon('arrow')}</button></td>`;

      tr.querySelector('.row-select-checkbox').addEventListener('change', (e) => {
        toggleSelectCompany(company.business_id, e.target.checked);
      });
      tr.querySelector('.open-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        openDrawer(company);
      });
      tr.addEventListener('click', (e) => {
        if (e.target.closest('input, a, button')) return;
        openDrawer(company);
      });
      tr.addEventListener('keydown', (e) => {
        if (e.target !== tr) return;
        if (e.key === 'Enter') {
          e.preventDefault();
          openDrawer(company);
        } else if (e.key === ' ') {
          e.preventDefault();
          toggleSelectCompany(company.business_id, !state.selectedCompanyIds.has(company.business_id));
        } else if (e.key === 'ArrowDown' && tr.nextElementSibling) {
          e.preventDefault();
          tr.nextElementSibling.focus();
        } else if (e.key === 'ArrowUp' && tr.previousElementSibling) {
          e.preventDefault();
          tr.previousElementSibling.focus();
        }
      });
      frag.appendChild(tr);
    });

    el.resultsTbody.innerHTML = '';
    el.resultsTbody.appendChild(frag);
    syncSelectionUI();
  }

  /* ────────────────────────────────────────────────────────────────────────
     Selection & export scope
     ──────────────────────────────────────────────────────────────────────── */

  function toggleSelectCompany(id, selected) {
    if (selected) state.selectedCompanyIds.add(id);
    else state.selectedCompanyIds.delete(id);
    syncSelectionUI();
  }

  function syncSelectionUI() {
    const total = state.companies.length;
    const n = state.selectedCompanyIds.size;
    const hasData = state.hasRun && total > 0 && !state.isLoading;
    const displayList = getDisplayList();
    const listCount = displayList.length;
    const selectedInView = displayList.filter(c => state.selectedCompanyIds.has(c.business_id)).length;

    el.selectionInfo.classList.toggle('hidden', n === 0);
    el.selectionCounter.textContent = `${n} selected`;
    el.btnExport.disabled = !hasData;
    el.tableFilterInput.disabled = !hasData;
    el.headerSelectAll.disabled = !hasData || listCount === 0;
    el.headerSelectAll.checked = hasData && listCount > 0 && selectedInView === listCount;
    el.headerSelectAll.indeterminate = selectedInView > 0 && selectedInView < listCount;
    el.exportScope.textContent = n > 0
      ? `Export the ${plural(n, 'selected company', 'selected companies')}`
      : `Export all ${plural(total, 'company', 'companies')} (tick rows to pick fewer)`;

    el.resultsTbody.querySelectorAll('tr.data-row').forEach(tr => {
      const on = state.selectedCompanyIds.has(tr.dataset.id);
      tr.classList.toggle('row-selected', on);
      const cb = tr.querySelector('.row-select-checkbox');
      if (cb) cb.checked = on;
    });

    if (state.activeCompany) {
      const isIn = state.selectedCompanyIds.has(state.activeCompany.business_id);
      el.btnDrawerSelectToggle.textContent = isIn ? 'Remove from selection' : 'Add to selection';
      el.btnDrawerSelectToggle.classList.toggle('btn-primary', !isIn);
    }
  }

  function openExportMenu() {
    if (el.btnExport.disabled) return;
    el.exportMenu.classList.remove('hidden');
    el.btnExport.setAttribute('aria-expanded', 'true');
    el.btnDownloadBrief.focus();
  }

  function closeExportMenu(returnFocus) {
    if (el.exportMenu.classList.contains('hidden')) return;
    el.exportMenu.classList.add('hidden');
    el.btnExport.setAttribute('aria-expanded', 'false');
    if (returnFocus) el.btnExport.focus();
  }

  /* ────────────────────────────────────────────────────────────────────────
     Company panel
     ──────────────────────────────────────────────────────────────────────── */

  function showBackdrop() {
    el.drawerBackdrop.classList.remove('hidden');
    document.body.classList.add('has-modal');
  }

  function evidenceLabel(item) {
    const c = String(item.criterion || '');
    const kw = /^Keyword match:\s*'?(.+?)'?$/i.exec(c);
    if (kw) return `Mentions “${kw[1]}”`;
    if (/corporate[- ]change/i.test(c)) return 'Mentions a merger or ownership change';
    return c || 'From the website';
  }

  function evidenceHtml(company) {
    // Register facts are already listed under "Register details".
    const items = (Array.isArray(company.evidence) ? company.evidence : []).filter(i => i.kind !== 'source_fact');
    if (items.length === 0) {
      const why = company.website_status === 'fetched'
        ? 'The website does not mention any of your search words.'
        : company.website_status === 'unavailable'
          ? 'We could not open this company’s website.'
          : 'This company has no website on record.';
      return `<li class="ev-empty">${escapeHtml(why)}</li>`;
    }
    return items.map(item => `
      <li>
        <div class="ev-word">${escapeHtml(evidenceLabel(item))}</div>
        <blockquote class="ev-quote">${escapeHtml(item.excerpt || '')}</blockquote>
        ${item.source_url ? `<div class="ev-source">Source: <a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer" class="link">${escapeHtml(item.source_url)}</a></div>` : ''}
      </li>`).join('');
  }

  function openDrawer(company) {
    if (!openModal()) state.lastFocus = document.activeElement;
    closeExportMenu();
    state.activeCompany = company;

    const ws = websiteState(company.website_status);
    el.drawerCompanyName.textContent = company.name;
    el.drawerSubtitle.textContent = [titleCase(company.city), company.industry_label, ws.label].filter(Boolean).join(' · ');

    const flag = !!(company.excluded_reason || company.corporate_change_flag);
    el.drawerExclusionBox.classList.toggle('hidden', !flag);
    el.drawerExclusionText.textContent = flag ? 'The website mentions a merger or acquisition. Confirm who owns the company before pitching.' : '';
    el.drawerExclusionBox.title = company.excluded_reason || '';

    el.drawerEvidenceList.innerHTML = evidenceHtml(company);

    const matched = company.matched_keywords || [];
    const missing = company.missing_criteria || [];
    el.drawerMatchedKeywords.innerHTML = matched.length
      ? matched.map(k => `<span class="tag tag-match">${icon('check', 'icon-xs')}${escapeHtml(k)}</span>`).join('')
      : '<span class="muted">None</span>';

    if (company.website_status === 'unavailable') {
      el.drawerMissingCriteria.innerHTML = '<span class="muted">Not evaluated (website could not be opened)</span>';
    } else if (company.website_status === 'no_website') {
      el.drawerMissingCriteria.innerHTML = '<span class="muted">Not evaluated (no website on record)</span>';
    } else {
      el.drawerMissingCriteria.innerHTML = missing.length
        ? missing.map(k => `<span class="tag tag-missing">${escapeHtml(k)}</span>`).join('')
        : '<span class="muted">None</span>';
    }

    el.drawerBusinessId.textContent = company.business_id || '—';
    el.drawerLegalForm.textContent = company.legal_form || 'Limited company (Oy)';
    el.drawerStatus.textContent = company.status || 'Active';
    el.drawerIndustry.textContent = [company.industry_code, company.industry_label].filter(Boolean).join(' · ') || '—';
    el.drawerWebsiteUrl.href = company.website || '#';
    el.drawerWebsiteUrl.textContent = company.website || 'None on record';
    el.drawerWebsiteBadge.textContent = company.website ? `(${ws.label.toLowerCase()})` : '';
    el.drawerWebsiteBadge.className = 'muted';
    if (el.drawerWebsiteTime) {
      el.drawerWebsiteTime.textContent = (company.website_retrieved_at ? formatDate(company.website_retrieved_at) : null) || company.website_retrieved_at || '—';
    }
    el.drawerRegistryUrl.href = company.registry_url || '#';
    el.drawerRegistryUrl.textContent = company.registry_url ? domainOf(company.registry_url) + ' record' : '—';
    el.drawerRegistryTime.textContent = (company.registry_retrieved_at ? formatDate(company.registry_retrieved_at) : null) || company.registry_retrieved_at || '—';

    el.howSheet.classList.add('hidden');
    showBackdrop();
    el.evidenceDrawer.classList.remove('hidden');
    el.evidenceDrawer.querySelector('.drawer-body').scrollTop = 0;
    el.evidenceDrawer.querySelector('.d-more').open = false;
    syncSelectionUI();
    el.btnCloseDrawer.focus();
  }

  function closeModals() {
    const wasOpen = !!openModal();
    state.activeCompany = null;
    el.drawerBackdrop.classList.add('hidden');
    document.body.classList.remove('has-modal');
    el.evidenceDrawer.classList.add('hidden');
    el.howSheet.classList.add('hidden');
    syncSelectionUI();
    if (wasOpen && state.lastFocus && document.contains(state.lastFocus)) state.lastFocus.focus();
    state.lastFocus = null;
  }

  function openHow() {
    if (!openModal()) state.lastFocus = document.activeElement;
    closeExportMenu();
    el.evidenceDrawer.classList.add('hidden');
    state.activeCompany = null;
    showBackdrop();
    el.howSheet.classList.remove('hidden');
    el.btnCloseHow.focus();
    loadBenchmark();
  }

  function trapFocus(e) {
    const modal = openModal();
    if (!modal || e.key !== 'Tab') return;
    const focusables = Array.from(modal.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'))
      .filter(n => n.offsetParent !== null);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  async function loadBenchmark() {
    el.benchmarkBody.innerHTML = '<p class="d-text">Loading…</p>';
    try {
      const res = await fetch('/api/benchmark');
      if (!res.ok) throw new Error(`error ${res.status}`);
      const data = await res.json();
      const b = data.benchmark;
      if (!b || data.status === 'pending') {
        el.benchmarkBody.innerHTML = '<p class="d-text">No test results yet.</p>';
        return;
      }
      const runs = b.runs || [];
      const totals = b.totals || {};
      const n = (v, d) => (v === undefined || v === null ? '—' : d !== undefined ? Number(v).toFixed(d) : String(v));
      let html = '<p class="d-text">We ran the same searches against live data and counted the results.</p>';
      html += `
        <table class="bench-table" style="margin-top:12px">
          <thead><tr><th>Search</th><th class="num">Seconds</th><th class="num">Companies</th><th class="num">Sites read</th><th class="num">With matches</th></tr></thead>
          <tbody>
            ${runs.map(r => `<tr>
              <td>${escapeHtml(r.label || r.query || 'Search')}</td>
              <td class="num">${n(r.elapsed_seconds, 1)}</td>
              <td class="num">${n(r.returned_companies)}</td>
              <td class="num">${n(r.fetched_websites)}</td>
              <td class="num">${n(r.keyword_evidence_companies)}</td>
            </tr>`).join('')}
            ${totals.returned_companies !== undefined ? `<tr class="totals">
              <td>Total</td>
              <td class="num">${n(totals.elapsed_seconds, 1)}</td>
              <td class="num">${n(totals.returned_companies)}</td>
              <td class="num">${n(totals.fetched_websites)}</td>
              <td class="num">${n(totals.keyword_evidence_companies)}</td>
            </tr>` : ''}
          </tbody>
        </table>`;
      if (b.generated_at) html += `<p class="bench-note">Measured ${escapeHtml(formatDate(b.generated_at) || b.generated_at)}.</p>`;
      el.benchmarkBody.innerHTML = html;
    } catch (err) {
      el.benchmarkBody.innerHTML = `<p class="d-text">Test results could not be loaded (${escapeHtml(err.message)}).</p>`;
    }
  }

  /* ────────────────────────────────────────────────────────────────────────
     Exports
     ──────────────────────────────────────────────────────────────────────── */

  function exportTargets() {
    if (state.selectedCompanyIds.size === 0) return state.companies;
    return state.companies.filter(c => state.selectedCompanyIds.has(c.business_id));
  }

  async function fetchBrief() {
    const ids = exportTargets().map(c => c.business_id);
    if (ids.length === 0) throw new Error('There are no companies to put in the report.');
    const res = await fetch('/api/brief', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        run_id: state.currentRunId,
        business_ids: ids,
        // Buyer context is frozen to the run so a later selector change cannot relabel the export.
        buyer_id: state.currentRunBuyerId || null,
        notes: el.briefNotes.value.trim()
      })
    });
    if (!res.ok) {
      let msg = `The report could not be created (error ${res.status}).`;
      try {
        const e = await res.json();
        if (e.error) msg = e.error;
      } catch (_) {}
      throw new Error(msg);
    }
    const data = await res.json();
    return {
      markdown: data.markdown || '',
      filename: data.filename || `mandatescout-report-${new Date().toISOString().substring(0, 10)}.md`
    };
  }

  async function withBusy(button, busyLabel, fn) {
    if (button.disabled) return;
    const label = button.querySelector('.menu-label');
    const original = label ? label.textContent : '';
    button.disabled = true;
    if (label) label.textContent = busyLabel;
    try {
      await fn();
    } finally {
      button.disabled = false;
      if (label) label.textContent = original;
    }
  }

  function downloadBrief() {
    return withBusy(el.btnDownloadBrief, 'Preparing…', async () => {
      try {
        const { markdown, filename } = await fetchBrief();
        triggerDownload(markdown, 'text/markdown;charset=utf-8;', filename);
        closeExportMenu(true);
        showAlert('Report downloaded.', 'success');
      } catch (err) {
        showAlert(err.message || 'The report could not be downloaded.', 'error');
      }
    });
  }

  function copyBrief() {
    return withBusy(el.btnCopyMd, 'Copying…', async () => {
      try {
        const { markdown } = await fetchBrief();
        await copyText(markdown);
        closeExportMenu(true);
        showAlert('Report copied. Paste it anywhere.', 'success');
      } catch (err) {
        showAlert(err.message || 'The report could not be copied.', 'error');
      }
    });
  }

  function exportCsv() {
    const targets = exportTargets();
    if (targets.length === 0) return;

    const headers = [
      'Business ID', 'Company Name', 'Legal Form', 'Legal Form Code', 'Status', 'City',
      'Industry Code', 'Industry Taxonomy', 'Industry Label', 'Website', 'Website Status',
      'Keyword Coverage (%)', 'Evidence Count', 'Matched Keywords', 'Missing Criteria',
      'Registry URL', 'Registry Retrieved At', 'Website Retrieved At', 'Financials',
      'Ownership Status', 'Owner Intent', 'Excluded Reason'
    ];

    function csvEscape(val) {
      if (val === null || val === undefined) return '""';
      let str = String(val);
      // Spreadsheet formula-injection guard.
      if (/^[=+\-@\t\r]/.test(str)) str = "'" + str;
      return `"${str.replace(/"/g, '""')}"`;
    }

    const rows = [headers.map(csvEscape).join(',')];
    targets.forEach(c => {
      rows.push([
        c.business_id, c.name, c.legal_form, c.legal_form_code || '16', c.status, c.city,
        c.industry_code, c.industry_taxonomy || 'TOIMI4', c.industry_label, c.website, c.website_status,
        c.relevance_score,
        Array.isArray(c.evidence) ? c.evidence.length : 0,
        Array.isArray(c.matched_keywords) ? c.matched_keywords.join('; ') : '',
        Array.isArray(c.missing_criteria) ? c.missing_criteria.join('; ') : '',
        c.registry_url, c.registry_retrieved_at, c.website_retrieved_at,
        'UNKNOWN (Not in open registry)', c.ownership_status || 'UNKNOWN', 'UNKNOWN',
        c.excluded_reason || ''
      ].map(csvEscape).join(','));
    });

    triggerDownload(rows.join('\r\n'), 'text/csv;charset=utf-8;', `mandatescout-companies-${new Date().toISOString().substring(0, 10)}.csv`);
    closeExportMenu(true);
    showAlert(`Spreadsheet with ${plural(targets.length, 'company', 'companies')} downloaded.`, 'success');
  }

  /* ────────────────────────────────────────────────────────────────────────
     Theme, keys, wiring
     ──────────────────────────────────────────────────────────────────────── */

  function toggleTheme() {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('ms-theme', next); } catch (_) {}
  }

  function toggleAdvanced(force) {
    const open = typeof force === 'boolean' ? force : el.advancedFiltersPanel.classList.contains('hidden');
    el.advancedFiltersPanel.classList.toggle('hidden', !open);
    el.btnToggleFilters.setAttribute('aria-expanded', String(open));
    if (open) el.buyerSelect.focus();
  }

  function onGlobalKeydown(e) {
    if (e.key === 'Escape') {
      if (openModal()) {
        e.preventDefault();
        closeModals();
        return;
      }
      if (!el.exportMenu.classList.contains('hidden')) {
        e.preventDefault();
        closeExportMenu(true);
        return;
      }
    }
    trapFocus(e);
    if (e.ctrlKey || e.metaKey || e.altKey || isTypingTarget(e.target) || openModal()) return;
    if (e.key === '/') {
      e.preventDefault();
      el.agentRequestInput.focus();
      el.agentRequestInput.select();
    }
  }

  function setupEventListeners() {
    el.btnAgentResearch.addEventListener('click', () => runAgentResearch());
    el.agentRequestInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        runAgentResearch();
      }
    });

    el.btnToggleFilters.addEventListener('click', () => toggleAdvanced());
    el.btnTheme.addEventListener('click', toggleTheme);
    el.searchForm.addEventListener('submit', (e) => {
      e.preventDefault();
      toggleAdvanced(false);
      runSearch();
    });
    el.btnResetFilters.addEventListener('click', () => {
      el.searchForm.reset();
      showBuyer(null);
    });
    el.buyerSelect.addEventListener('change', onBuyerChange);

    if (el.btnViewEvidence) {
      el.btnViewEvidence.addEventListener('click', () => {
        state.coverageView = 'evidence';
        updateCoverageBadges();
        renderSummary({ industryCode: el.industryCode.value });
        renderResults();
      });
    }
    if (el.btnViewAll) {
      el.btnViewAll.addEventListener('click', () => {
        state.coverageView = 'all';
        updateCoverageBadges();
        renderSummary({ industryCode: el.industryCode.value });
        renderResults();
      });
    }

    el.btnOpenExample.addEventListener('click', () => openSavedRun(pickExampleRun()));
    el.runsHistorySelect.addEventListener('change', (e) => openSavedRun(e.target.value));

    el.btnNotes.addEventListener('click', () => {
      const open = el.notesList.classList.contains('hidden');
      el.notesList.classList.toggle('hidden', !open);
      el.btnNotes.setAttribute('aria-expanded', String(open));
    });

    el.tableFilterInput.addEventListener('input', (e) => {
      state.filterText = e.target.value;
      renderResults();
    });
    el.tableFilterInput.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && e.target.value) {
        e.stopPropagation();
        e.target.value = '';
        state.filterText = '';
        renderResults();
      }
    });

    el.headerSelectAll.addEventListener('change', (e) => {
      const displayList = getDisplayList();
      if (e.target.checked) displayList.forEach(c => state.selectedCompanyIds.add(c.business_id));
      else displayList.forEach(c => state.selectedCompanyIds.delete(c.business_id));
      syncSelectionUI();
    });
    el.btnClearSelection.addEventListener('click', () => {
      state.selectedCompanyIds.clear();
      syncSelectionUI();
    });

    el.btnExport.addEventListener('click', () => {
      if (el.exportMenu.classList.contains('hidden')) openExportMenu();
      else closeExportMenu();
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.menu-wrap')) closeExportMenu();
    });
    el.btnDownloadBrief.addEventListener('click', downloadBrief);
    el.btnCopyMd.addEventListener('click', copyBrief);
    el.btnExportCsv.addEventListener('click', exportCsv);

    el.btnCloseDrawer.addEventListener('click', closeModals);
    el.btnDrawerClose.addEventListener('click', closeModals);
    el.drawerBackdrop.addEventListener('click', closeModals);
    el.btnDrawerSelectToggle.addEventListener('click', () => {
      if (!state.activeCompany) return;
      const id = state.activeCompany.business_id;
      toggleSelectCompany(id, !state.selectedCompanyIds.has(id));
    });
    el.btnHow.addEventListener('click', openHow);
    el.btnCloseHow.addEventListener('click', closeModals);

    el.resultsTable.querySelectorAll('th.sortable').forEach(th => {
      th.querySelector('.th-btn').addEventListener('click', () => {
        const field = th.dataset.sort;
        if (state.sortField === field) state.sortAsc = !state.sortAsc;
        else {
          state.sortField = field;
          state.sortAsc = field !== 'relevance_score';
        }
        renderResults();
      });
    });

    window.addEventListener('keydown', onGlobalKeydown);
  }

  async function init() {
    renderExamples();
    setupEventListeners();
    syncSelectionUI();
    el.agentRequestInput.focus();

    const healthy = await checkHealth();
    setInterval(checkHealth, 15000);

    if (!healthy) {
      const retry = setInterval(async () => {
        if (await checkHealth()) {
          clearInterval(retry);
          loadBuyers();
          loadRunsHistory();
        }
      }, 5000);
    }
    await loadBuyers();
    await loadRunsHistory();

    // Resume active research job if present in sessionStorage
    const resumeJobId = sessionStorage.getItem(SESSION_JOB_KEY);
    if (resumeJobId) {
      const resumeReq = sessionStorage.getItem(SESSION_REQ_KEY) || '';
      const resumeBuyer = sessionStorage.getItem(SESSION_BUYER_KEY) || null;
      if (resumeReq) el.agentRequestInput.value = resumeReq;
      if (resumeBuyer) el.buyerSelect.value = resumeBuyer;

      try {
        const chk = await fetch(`/api/agent/job?job_id=${encodeURIComponent(resumeJobId)}`);
        if (chk.ok) {
          const job = await chk.json();
          if (job.status === 'queued' || job.status === 'running') {
            setMode('results');
            setLoading(true);
            setProgress(Math.min(95, Math.max(8, job.progress_pct || 10)), friendlyStage(job.stage, job.stage_message));
            showAlert('Resumed active research search from session.', 'info');
            pollJob(resumeJobId, resumeReq, resumeBuyer).finally(() => {
              setLoading(false);
              hideProgress();
              renderResults();
            });
          } else if (job.status === 'completed') {
            sessionStorage.removeItem(SESSION_JOB_KEY);
            const results = job.results || {};
            const plan = job.plan || {};
            const companies = (results.reviewed_companies && results.reviewed_companies.length > 0)
              ? results.reviewed_companies
              : (results.companies || []);
            state.currentKeywords = plan.keywords || results.keywords || [];
            state.coverageView = (state.currentKeywords && state.currentKeywords.length > 0) ? 'evidence' : 'all';
            applyRun(companies, results.run_id, resumeBuyer, false, results);
            setMode('results');
            renderSummary({ industryCode: plan.industry_code });
            renderResults();
          } else {
            sessionStorage.removeItem(SESSION_JOB_KEY);
          }
        } else {
          sessionStorage.removeItem(SESSION_JOB_KEY);
        }
      } catch (_) {
        // Tolerated on resume
      }
    }

    // Support ?run_id= URL parameter for deep-linking and verification
    const urlParams = new URLSearchParams(window.location.search);
    const initialRunId = urlParams.get('run_id');
    if (initialRunId) {
      await loadRun(initialRunId);
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
