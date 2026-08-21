import json

with open('events.json') as f:
    events = json.load(f)

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CIB Healthcare News Tracker</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;0,700;0,900;1,600&family=PT+Serif:ital,wght@0,400;0,700;1,400&family=Source+Sans+3:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

  :root{
    --paper: #FCFBF8;
    --ink: #121212;
    --ink-dim: #5A5A56;
    --rule: #121212;
    --rule-light: #D6D3C9;
    --red: #A81C1C;
    --red-tint: #F6E8E8;
    --green: #2B5C3F;
    --green-tint: #E7EFE9;
    --gold: #8A6014;
    --gold-tint: #F2ECDA;
    --font-display: 'Playfair Display', Georgia, serif;
    --font-body: 'PT Serif', Georgia, serif;
    --font-sans: 'Source Sans 3', system-ui, sans-serif;
    --font-mono: 'IBM Plex Mono', monospace;
  }

  *{ box-sizing: border-box; }
  html, body{ margin:0; padding:0; }
  body{
    background: var(--paper);
    color: var(--ink);
    font-family: var(--font-body);
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
  }
  a{ color: inherit; }

  /* ===== TOP BAR / TICKER ===== */
  .topbar{
    border-bottom: 1px solid var(--rule);
    background: var(--ink);
    color: var(--paper);
    font-family: var(--font-sans);
    font-size: 11.5px;
    letter-spacing: 0.03em;
    overflow: hidden;
    white-space: nowrap;
    padding: 7px 0;
  }
  .ticker-track{
    display: inline-block;
    padding-left: 100%;
    animation: scroll-left 80s linear infinite;
  }
  .ticker-track span{ margin-right: 44px; }
  .ticker-track a{ color: inherit; text-decoration: none; }
  .ticker-track a:hover{ text-decoration: underline; }
  .ticker-track .dir-neg{ color: #E8A0A0; font-weight: 700; margin-right: 6px; }
  .ticker-track .dir-pos{ color: #A7CBAF; font-weight: 700; margin-right: 6px; }
  .ticker-track .dir-mix{ color: #E3C97A; font-weight: 700; margin-right: 6px; }
  @keyframes scroll-left{ 0%{transform:translateX(0);} 100%{transform:translateX(-100%);} }

  /* ===== MASTHEAD ===== */
  header{
    max-width: 1240px;
    margin: 0 auto;
    padding: 30px 32px 0;
    text-align: center;
  }
  .eyebrow{
    font-family: var(--font-sans);
    font-size: 11px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: var(--red);
    font-weight: 600;
  }
  h1{
    font-family: var(--font-display);
    font-weight: 900;
    font-size: 52px;
    margin: 6px 0 8px;
    letter-spacing: -0.01em;
    color: var(--ink);
  }
  .subhead{
    font-family: var(--font-sans);
    color: var(--ink-dim);
    font-size: 13.5px;
    max-width: 560px;
    margin: 0 auto 18px;
    line-height: 1.5;
  }
  .rule-thick{ border: none; border-top: 3px solid var(--rule); margin: 0; }
  .rule-thin{ border: none; border-top: 1px solid var(--rule); margin: 0; }

  .stat-strip{
    display:flex; justify-content:center; gap: 46px;
    padding: 14px 0; font-family: var(--font-sans);
    border-bottom: 1px solid var(--rule-light);
  }
  .stat{ text-align:center; }
  .stat .num{ font-family: var(--font-display); font-size: 26px; font-weight: 700; color: var(--ink); display:block; line-height:1; }
  .stat .num.neg{ color: var(--red); }
  .stat .label{ font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-dim); }

  /* ===== CONTROLS ===== */
  .controls-wrap{
    max-width: 1240px; margin: 0 auto; padding: 16px 32px 0;
    font-family: var(--font-sans);
  }
  .controls{ display:flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 8px; }
  .search-box{ flex: 1; min-width: 200px; position: relative; }
  .search-box input{
    width: 100%; background: var(--paper); border: 1px solid var(--rule);
    color: var(--ink); font-family: var(--font-sans); font-size: 13px;
    padding: 8px 12px 8px 30px; outline: none;
  }
  .search-box input::placeholder{ color: var(--ink-dim); }
  .search-box::before{
    content:""; position:absolute; left:11px; top:50%; width:11px; height:11px;
    transform:translateY(-50%); border:1.5px solid var(--ink-dim); border-radius:50%;
  }
  .search-box::after{
    content:""; position:absolute; left:20px; top:63%; width:5px; height:1.5px;
    background: var(--ink-dim); transform: rotate(45deg);
  }
  .filter-chip{
    font-family: var(--font-sans); font-size: 11.5px; font-weight: 600; padding: 7px 12px;
    background: var(--paper); border: 1px solid var(--rule); color: var(--ink);
    cursor: pointer; letter-spacing: 0.02em; text-transform: uppercase;
  }
  .filter-chip:hover{ background: #EFEDE4; }
  .filter-chip.active{ background: var(--ink); border-color: var(--ink); color: var(--paper); }
  .filter-chip.chip-primary{ border-color: var(--red); color: var(--red); font-weight: 700; }
  .filter-chip.chip-primary:hover{ background: #F7EDEC; }
  .filter-chip.chip-primary.active{ background: var(--red); border-color: var(--red); color: #fff; }
  .chip-divider{
    display:inline-block; width:1px; align-self:stretch;
    background: var(--rule-light); margin: 0 4px;
  }
  .borrower-row{ cursor: pointer; }
  .borrower-row:hover span:first-child{ text-decoration: underline; }
  .borrower-row.selected{ background: #F7EDEC; }
  .borrower-row.selected span:first-child{ color: var(--red); font-weight: 700; }
  .active-borrower-bar{
    font-family: var(--font-sans); font-size: 12px; color: var(--ink);
    background: #F7EDEC; border-left: 3px solid var(--red);
    padding: 9px 14px; margin: 16px 0 4px;
  }
  .active-borrower-bar button{
    background:none; border:none; color: var(--red); cursor:pointer;
    font-family: var(--font-sans); font-size: 11px; font-weight:700;
    text-transform:uppercase; letter-spacing:0.05em; margin-left:10px;
  }
  .controls-row2{ display:flex; gap: 8px; flex-wrap: wrap; align-items: center; padding-bottom: 14px; }
  .controls-row2 .filter-chip.dir-negative.active{ background: var(--red); border-color: var(--red); }
  .controls-row2 .filter-chip.dir-positive.active{ background: var(--green); border-color: var(--green); }
  .controls-row2 .filter-chip.dir-mixed.active{ background: var(--gold); border-color: var(--gold); }
  .row2-label{ font-family: var(--font-sans); font-size: 10.5px; color: var(--ink-dim); letter-spacing: 0.08em; text-transform: uppercase; margin-right: 2px; }

  /* ===== LAYOUT ===== */
  .layout{
    max-width: 1240px; margin: 0 auto 70px; padding: 0 32px;
    display: grid; grid-template-columns: 1fr 280px; gap: 0;
    border-top: 3px solid var(--rule);
  }
  .feed{ border-right: 1px solid var(--rule-light); padding-right: 34px; }
  .day-marker{
    font-family: var(--font-sans); font-size: 11px; letter-spacing: 0.14em;
    color: var(--paper); background: var(--ink); text-transform: uppercase;
    padding: 5px 10px; display: inline-block; margin: 22px 0 4px;
  }
  .feed > .day-marker:first-child{ margin-top: 18px; }

  .article{
    padding: 20px 0;
    border-bottom: 1px solid var(--rule-light);
    display: grid;
    grid-template-columns: 1fr 46px;
    gap: 16px;
    align-items: start;
  }
  .risk-score{
    font-family: var(--font-mono); font-size: 15px; font-weight: 700;
    width: 40px; height: 40px; border: 1.5px solid var(--ink);
    display:flex; align-items:center; justify-content:center; color: var(--ink);
    justify-self: end;
  }
  .risk-high{ border-color: var(--red); color: var(--red); }
  .risk-med{ border-color: var(--gold); color: var(--gold); }
  .risk-low{ border-color: var(--green); color: var(--green); }

  .article-tag-row{ display:flex; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; align-items: center; font-family: var(--font-sans); }
  .article-tag{
    font-size: 10px; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; color: var(--red);
  }
  .rank-badge{ font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-dim); }

  .dir-tag{ font-family: var(--font-sans); font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; padding: 1px 7px; border: 1px solid; }
  .dir-tag.Negative{ color: var(--red); border-color: var(--red); }
  .dir-tag.Positive{ color: var(--green); border-color: var(--green); }
  .dir-tag.Mixed{ color: var(--gold); border-color: var(--gold); }

  .article h3{
    font-family: var(--font-display); font-weight: 700; font-size: 22px;
    margin: 0 0 8px; line-height: 1.25; color: var(--ink);
  }
  .article h3 a{ text-decoration: none; }
  .article h3 a:hover{ text-decoration: underline; text-decoration-thickness: 1.5px; }
  .article p{
    font-family: var(--font-body); font-size: 14.5px; color: #333330;
    line-height: 1.62; margin: 0 0 10px; max-width: 66ch;
  }
  .article-meta{
    font-family: var(--font-sans); font-size: 11px; color: var(--ink-dim);
    display:flex; gap: 14px; flex-wrap: wrap; text-transform: uppercase; letter-spacing: 0.03em;
  }
  .article-meta .source{ color: var(--ink); font-weight: 700; }
  .article-meta a{ color: var(--red); text-decoration: none; font-weight: 600; }
  .article-meta a:hover{ text-decoration: underline; }
  .article-meta .unverified{ color: var(--gold); font-weight: 700; }

  .borrower-badge{
    display:inline-block; background: var(--ink); color: var(--paper);
    font-family: var(--font-sans); font-size: 10px; font-weight: 700;
    letter-spacing: 0.08em; text-transform: uppercase; padding: 3px 9px;
    margin-bottom: 8px;
  }
  .trade-tag{
    font-family: var(--font-sans); font-size: 10px; color: var(--gold);
    font-weight: 600; letter-spacing: 0.04em;
  }
  .borrower-row{
    display:flex; justify-content: space-between; align-items: baseline;
    padding: 7px 0; border-bottom: 1px dotted var(--rule-light);
    font-family: var(--font-body); font-size: 12.5px;
  }
  .borrower-row:last-child{ border-bottom: none; }
  .borrower-row.has-hits{ font-weight: 700; }
  .borrower-row .count{ font-family: var(--font-mono); font-size: 11.5px; }
  .borrower-row .count.zero{ color: var(--rule-light); }
  .borrower-row .count.hit{ color: var(--red); }

  .empty-state{
    padding: 46px 26px; text-align: center; color: var(--ink-dim);
    font-family: var(--font-sans); font-size: 13px; line-height: 1.65;
    max-width: 520px; margin: 20px auto; border: 1px dashed var(--rule-light);
  }
  .empty-state strong{ color: var(--ink); font-size: 14px; }

  /* ===== SIDEBAR ===== */
  .sidebar{ padding-left: 30px; }
  .panel{ padding-bottom: 26px; margin-bottom: 26px; border-bottom: 1px solid var(--rule-light); }
  .panel:last-child{ border-bottom: none; }
  .panel-title{
    font-family: var(--font-sans); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--ink); font-weight: 700; margin: 0 0 14px; padding-top: 18px;
    border-top: 3px solid var(--rule);
  }
  .panel:first-child .panel-title{ margin-top: 0; }
  .source-row{
    display:flex; justify-content: space-between; align-items: baseline;
    padding: 7px 0; border-bottom: 1px dotted var(--rule-light);
    font-family: var(--font-body); font-size: 13px;
  }
  .source-row:last-child{ border-bottom: none; }
  .source-row .count{ font-family: var(--font-mono); color: var(--ink-dim); font-size: 11.5px; }
  .feed-note{ font-family: var(--font-sans); font-size: 12px; color: var(--ink-dim); line-height: 1.6; }
  .feed-note code{ font-family: var(--font-mono); background: #EFEDE4; padding: 1px 5px; font-size: 11px; color: var(--gold); }

  @media (max-width: 900px){
    .layout{ grid-template-columns: 1fr; }
    .feed{ border-right: none; padding-right: 0; }
    .sidebar{ padding-left: 0; margin-top: 20px; }
    h1{ font-size: 34px; }
    .stat-strip{ gap: 24px; }
    .article{ grid-template-columns: 1fr; }
    .risk-score{ justify-self: start; }
  }
</style>
</head>
<body>

  <div class="topbar"><div class="ticker-track" id="tickerTrack"></div></div>

  <header>
    <div class="eyebrow">Sector Desk · Daily Edition</div>
    <h1>CIB Healthcare News Tracker</h1>
    <div class="subhead">Source-audited enforcement, Medicaid policy, and CMS actions with credit read-through — newest first.</div>
  </header>
  <hr class="rule-thick">
  <div class="stat-strip">
    <div class="stat"><span class="num" id="statTotal">0</span><span class="label">Events Tracked</span></div>
    <div class="stat"><span class="num neg" id="statHigh">0</span><span class="label">High Severity</span></div>
    <div class="stat"><span class="num neg" id="statBorrower">0</span><span class="label">Borrower Mentions</span></div>
    <div class="stat"><span class="num" id="statSources">0</span><span class="label">Sources</span></div>
  </div>

  <div class="controls-wrap">
    <div class="controls">
      <div class="search-box"><input type="text" id="searchInput" placeholder="Search headlines, states, agencies..."></div>
      <button class="filter-chip chip-primary active" data-filter="gov">Regulatory &amp; Enforcement</button>
      <button class="filter-chip chip-primary" data-filter="borrower">Borrower News</button>
      <button class="filter-chip chip-primary" data-filter="industry">Industry &amp; Trade</button>
      <span class="chip-divider"></span>
      <button class="filter-chip" data-filter="fraud">Fraud / Enforcement</button>
      <button class="filter-chip" data-filter="medicaid">Medicaid Policy</button>
      <button class="filter-chip" data-filter="cms">CMS / Medicare</button>
      <button class="filter-chip" data-filter="disaster">Disaster</button>
      <button class="filter-chip" data-filter="regulation">Regulation</button>
    </div>
    <div class="controls-row2">
      <span class="row2-label">Credit Direction</span>
      <button class="filter-chip dir-negative active" data-dir="all">All</button>
      <button class="filter-chip dir-negative" data-dir="Negative">Negative</button>
      <button class="filter-chip dir-mixed" data-dir="Mixed">Mixed</button>
      <button class="filter-chip dir-positive" data-dir="Positive">Positive</button>
      <span class="row2-label" style="margin-left:14px;">Sort</span>
      <button class="filter-chip sort-chip active" data-sort="date">Newest First</button>
      <button class="filter-chip sort-chip" data-sort="impact">Most Impactful</button>
    </div>
  </div>

  <div class="layout">
    <div class="feed" id="feed"></div>
    <div class="sidebar">
      <div class="panel">
        <div class="panel-title">Borrower Watch</div>
        <div id="borrowerList"></div>
      </div>
      <div class="panel">
        <div class="panel-title">Source Agencies</div>
        <div id="sourceList"></div>
      </div>
      <div class="panel">
        <div class="panel-title">About This Feed</div>
        <div class="feed-note">
          Built from a source-audited event log — every headline links to the original government or agency source. Risk scores (0–10) and credit direction reflect this tracker's internal weighting methodology, not the source itself.
        </div>
      </div>
    </div>
  </div>

<script>
  const EVENTS = __EVENTS_JSON__;

  const BORROWERS = ["Drumm Merger / Cuarzo","PACS Holdings","New Day Healthcare",
    "Purpose Healing","Pathnostics","CCGEN Jefferson / Autumn Lake",
    "Complete Care at Glendale","HCS-Girling","Quipt Home Medical",
    "Diversified Healthcare Trust","Oxford Finance"];

  const GOV_CATEGORIES = ["fraud","medicaid","cms","regulation","disaster","other"];

  const CAT_LABELS = { borrower:"Borrower News", industry:"Industry / Trade", fraud:"Fraud / Enforcement", medicaid:"Medicaid Policy", cms:"CMS / Medicare", disaster:"Disaster", regulation:"Regulation", other:"Other" };

  function riskClass(score){
    if(score >= 7) return "risk-high";
    if(score >= 4) return "risk-med";
    return "risk-low";
  }

  // Null-safe DOM helpers: a missing element must never abort the whole script.
  function setText(id, value){
    const el = document.getElementById(id);
    if(el) el.textContent = value;
  }
  function setHTML(id, value){
    const el = document.getElementById(id);
    if(el) el.innerHTML = value;
  }

  const SOURCES = [...new Set(EVENTS.map(e => e.sourceAgency).filter(Boolean))].sort();

  setHTML('tickerTrack', EVENTS.slice(0, 10).map(e => {
    const dirClass = e.creditDirection === 'Negative' ? 'dir-neg' : e.creditDirection === 'Positive' ? 'dir-pos' : 'dir-mix';
    const arrow = e.creditDirection === 'Negative' ? '▲ RISK' : e.creditDirection === 'Positive' ? '▽ EASED' : '◆ MIXED';
    return `<span><span class="${dirClass}">${arrow}</span><a href="${e.sourceURL || '#'}" target="_blank" rel="noopener" style="text-decoration:none;">${e.headline}</a> — ${e.sourceAgency}</span>`;
  }).join(''));

  function renderBorrowerList(){
    setHTML('borrowerList', BORROWERS.map((b, i) => {
      const n = EVENTS.filter(e => (e.borrowers || []).includes(b)).length;
      const sel = activeBorrower === b ? 'selected' : '';
      return `<div class="borrower-row ${n ? 'has-hits' : ''} ${sel}" data-borrower-index="${i}">
        <span>${b}</span>
        <span class="count ${n ? 'hit' : 'zero'}">${n || '—'}</span></div>`;
    }).join(''));

    const list = document.getElementById('borrowerList');
    if(!list) return;
    Array.prototype.forEach.call(list.querySelectorAll('.borrower-row'), row => {
      row.addEventListener('click', () => {
        const name = BORROWERS[parseInt(row.getAttribute('data-borrower-index'), 10)];
        activeBorrower = (activeBorrower === name) ? null : name;
        renderBorrowerList();
        renderFeed();
      });
    });
  }

  setHTML('sourceList', SOURCES.map(s => {
    const count = EVENTS.filter(e => e.sourceAgency === s).length;
    return `<div class="source-row"><span>${s}</span><span class="count">${count}</span></div>`;
  }).join(''));

  setText('statTotal', EVENTS.length);
  setText('statHigh', EVENTS.filter(e => e.severity === 'High').length);
  setText('statSources', SOURCES.length);
  setText('statBorrower', EVENTS.filter(e => (e.borrowers || []).length).length);
  document.getElementById('statBorrower').textContent =
    EVENTS.filter(e => (e.borrowers || []).length).length;

  const feed = document.getElementById('feed') || document.createElement('div');
  let activeFilter = 'gov';
  let activeBorrower = null;
  let activeDir = 'all';
  let searchTerm = '';
  let sortMode = 'date';

  function impactTier(score){
    if(score >= 10) return "Critical Impact — Risk Score 10+";
    if(score >= 7) return "High Impact — Risk Score 7–9";
    if(score >= 4) return "Elevated Impact — Risk Score 4–6";
    return "Lower Impact — Risk Score 0–3";
  }

  function renderFeed(){
    let filtered = EVENTS.filter(e => {
      if(activeBorrower){
        if(!(e.borrowers || []).includes(activeBorrower)) return false;
      }
      const matchesFilter =
        activeBorrower ? true :
        activeFilter === 'gov' ? GOV_CATEGORIES.indexOf(e.broadCategory) !== -1 :
        e.broadCategory === activeFilter;
      const matchesDir = activeDir === 'all' || e.creditDirection === activeDir;
      const haystack = [e.headline, e.detail, e.sourceAgency, e.state, e.jurisdiction, e.category].join(' ').toLowerCase();
      const matchesSearch = haystack.includes(searchTerm.toLowerCase());
      return matchesFilter && matchesDir && matchesSearch;
    });

    if(sortMode === 'impact'){
      filtered = filtered.slice().sort((a,b) => (b.riskScore ?? 0) - (a.riskScore ?? 0));
    }

    const borrowerBar = activeBorrower
      ? `<div class="active-borrower-bar">Showing all coverage for <strong>${activeBorrower}</strong>
         <button id="clearBorrower">Clear</button></div>`
      : '';

    if(filtered.length === 0){
      let msg;
      if(activeBorrower){
        msg = `<strong>No coverage yet for ${activeBorrower}.</strong><br><br>
          This borrower is being monitored across government and trade-press
          sources. Items will appear here automatically when it is named.`;
      } else if(activeFilter === 'borrower'){
        msg = `<strong>No borrower mentions yet.</strong><br><br>
          The tracker is monitoring ${BORROWERS.length} portfolio borrowers across
          government and trade-press sources. Items will appear here automatically
          when a borrower is named in the news.<br><br>
          Existing events predate borrower tracking, so this section starts empty.`;
      } else if(activeFilter === 'industry'){
        msg = `<strong>No trade-press items yet.</strong><br><br>
          Industry coverage from Skilled Nursing News, Home Health Care News,
          Hospice News and others will appear here once the next scheduled
          fetch runs.`;
      } else if(searchTerm){
        msg = `No events match &ldquo;${searchTerm}&rdquo;. Try a broader term or clear the search.`;
      } else {
        msg = `No events match this filter. Try selecting &ldquo;Regulatory &amp; Enforcement.&rdquo;`;
      }
      feed.innerHTML = borrowerBar + `<div class="empty-state">${msg}</div>`;
      wireClearBorrower();
      return;
    }

    let html = '';
    let lastGroup = null;
    filtered.forEach((e, i) => {
      const groupKey = sortMode === 'impact' ? impactTier(e.riskScore ?? 0) : e.date;
      if(groupKey !== lastGroup){
        html += `<div class="day-marker">${groupKey}</div>`;
        lastGroup = groupKey;
      }
      const rankBadge = sortMode === 'impact' ? `<span class="rank-badge">#${i+1}</span>` : '';
      html += `
        <div class="article">
          <div>
            ${(e.borrowers && e.borrowers.length) ? `<div class="borrower-badge">Portfolio Borrower &bull; ${e.borrowers.join(', ')}</div>` : ''}
            <div class="article-tag-row">
              ${rankBadge}
              <span class="article-tag">${CAT_LABELS[e.broadCategory] || e.category}</span>
              <span class="dir-tag ${e.creditDirection}">${e.creditDirection}</span>
            </div>
            <h3><a href="${e.sourceURL || '#'}" target="_blank" rel="noopener">${e.headline}</a></h3>
            <p>${e.detail}</p>
            <div class="article-meta">
              <span class="source">${e.sourceAgency}</span>
              <span>${e.jurisdiction}${e.state && e.state !== e.jurisdiction ? ' · ' + e.state : ''}</span>
              ${sortMode === 'date' ? '' : `<span>${e.date}</span>`}
              ${(e.sourceVerification && e.sourceVerification !== 'Primary') ? `<span class="unverified">⚑ Secondary source — pending primary verification</span>` : ''}
              ${(e.sourceVerification || '').indexOf('Trade press') === 0 ? '<span class="trade-tag">Trade press</span>' : ''}
              <a href="${e.sourceURL || '#'}" target="_blank" rel="noopener">Read source →</a>
            </div>
          </div>
          <div class="risk-score ${riskClass(e.riskScore)}">${e.riskScore ?? '–'}</div>
        </div>`;
    });
    feed.innerHTML = borrowerBar + html;
    wireClearBorrower();
  }

  function wireClearBorrower(){
    const btn = document.getElementById('clearBorrower');
    if(btn) btn.addEventListener('click', () => {
      activeBorrower = null;
      renderBorrowerList();
      renderFeed();
    });
  }

  document.querySelectorAll('.controls .filter-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.controls .filter-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      activeBorrower = null;
      renderBorrowerList();
      renderFeed();
    });
  });

  document.querySelectorAll('.controls-row2 .filter-chip[data-dir]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.controls-row2 .filter-chip[data-dir]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeDir = btn.dataset.dir;
      renderFeed();
    });
  });

  const searchEl = document.getElementById('searchInput');
  if(searchEl) searchEl.addEventListener('input', (e) => {
    searchTerm = e.target.value;
    renderFeed();
  });

  document.querySelectorAll('.sort-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.sort-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      sortMode = btn.dataset.sort;
      renderFeed();
    });
  });

  renderBorrowerList();
  renderFeed();
</script>
</body>
</html>
"""

html = TEMPLATE.replace("__EVENTS_JSON__", json.dumps(events))
with open('index.html', 'w') as f:
    f.write(html)

print("done, size:", len(html))
