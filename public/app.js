const $ = (id) => document.getElementById(id);

function fmtNum(x, digits = 2) {
  const n = Number(x);
  if (!Number.isFinite(n)) return String(x);
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function clamp(n, a, b){ return Math.max(a, Math.min(b, n)); }

function parseNumOrNull(v){
  if (v == null) return null;
  const s = String(v).trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function isoToDateSafe(s){
  try{
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }catch{
    return null;
  }
}

function timeAgo(date){
  if (!date) return '—';
  const ms = Date.now() - date.getTime();
  const sec = Math.round(ms / 1000);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

  const abs = Math.abs(sec);
  if (abs < 10) return 'a few seconds ago';
  if (abs < 60) return rtf.format(-sec, 'second');

  const min = Math.round(sec / 60);
  const absMin = Math.abs(min);
  if (absMin < 60) return rtf.format(-min, 'minute');

  const hr = Math.round(min / 60);
  const absHr = Math.abs(hr);
  if (absHr < 24) return rtf.format(-hr, 'hour');

  const day = Math.round(hr / 24);
  return rtf.format(-day, 'day');
}

function getCssVar(name){
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function drawSpark(svg, points, latestPoint) {
  svg.innerHTML = '';
  const W = 1000, H = 260, pad = 18;

  const gridStroke = getCssVar('--chartGrid') || 'rgba(128,128,128,0.22)';
  const textFill = getCssVar('--chartText') || 'rgba(128,128,128,0.78)';
  const lineColor = getCssVar('--chart') || 'currentColor';

  // If only 0/1 points, draw a single dot (nice empty-state)
  if (!points || points.length < 2) {
    const p = latestPoint && Number.isFinite(Number(latestPoint.gsr)) ? latestPoint : (points && points[0]);
    if (!p) return;

    const dot = document.createElementNS('http://www.w3.org/2000/svg','circle');
    dot.setAttribute('cx', String(W/2));
    dot.setAttribute('cy', String(H/2));
    dot.setAttribute('r', '7');
    dot.setAttribute('fill', lineColor);
    dot.setAttribute('opacity', '0.95');
    svg.appendChild(dot);

    const t = document.createElementNS('http://www.w3.org/2000/svg','text');
    t.textContent = `GSR ${fmtNum(Number(p.gsr), 4)}`;
    t.setAttribute('x', String(W/2));
    t.setAttribute('y', String(H/2 + 28));
    t.setAttribute('fill', textFill);
    t.setAttribute('font-size', '16');
    t.setAttribute('font-family', getCssVar('--mono') || 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace');
    t.setAttribute('text-anchor', 'middle');
    svg.appendChild(t);

    return;
  }

  const ys = points.map(p => Number(p.gsr)).filter(Number.isFinite);
  if (ys.length < 2) return;

  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanY = (maxY - minY) || 1;

  const toX = (i) => pad + (i * (W - 2*pad)) / (points.length - 1);
  const toY = (v) => (H - pad) - ((v - minY) * (H - 2*pad)) / spanY;

  // Background grid
  const grid = document.createElementNS('http://www.w3.org/2000/svg','path');
  let gridD = '';
  for (let i=0;i<5;i++) {
    const y = pad + i * (H-2*pad)/4;
    gridD += `M ${pad} ${y} L ${W-pad} ${y} `;
  }
  grid.setAttribute('d', gridD);
  grid.setAttribute('stroke', gridStroke);
  grid.setAttribute('stroke-width', '1');
  grid.setAttribute('fill', 'none');
  svg.appendChild(grid);

  // Line
  const path = document.createElementNS('http://www.w3.org/2000/svg','path');
  let d = '';
  for (let i=0;i<points.length;i++) {
    const v = Number(points[i].gsr);
    const x = toX(i);
    const y = toY(v);
    d += (i===0 ? `M ${x} ${y}` : ` L ${x} ${y}`);
  }
  path.setAttribute('d', d);
  path.setAttribute('stroke', lineColor);
  path.setAttribute('stroke-width', '2.5');
  path.setAttribute('fill', 'none');
  path.setAttribute('opacity', '0.95');
  svg.appendChild(path);

  // Min/Max labels
  const mkText = (txt, x, y, anchor='start') => {
    const t = document.createElementNS('http://www.w3.org/2000/svg','text');
    t.textContent = txt;
    t.setAttribute('x', String(x));
    t.setAttribute('y', String(y));
    t.setAttribute('fill', textFill);
    t.setAttribute('font-size', '16');
    t.setAttribute('font-family', getCssVar('--mono') || 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace');
    t.setAttribute('text-anchor', anchor);
    return t;
  }
  svg.appendChild(mkText(`max ${fmtNum(maxY,2)}`, W-pad, pad, 'end'));
  svg.appendChild(mkText(`min ${fmtNum(minY,2)}`, W-pad, H-pad, 'end'));
}

/* -------------------------
   Alerts (local-only, UI)
-------------------------- */

const ALERTS_KEY = 'gsr_alerts_v1';
const ALERT_LAST_KEY = 'gsr_alerts_last_v1';

function defaultAlerts(){
  return {
    enabled: false,
    sound: false,
    gsrBelow: null,
    gsrAbove: null,
    goldBelow: null,
    goldAbove: null,
    silverBelow: null,
    silverAbove: null
  };
}

function loadAlerts(){
  try{
    const raw = localStorage.getItem(ALERTS_KEY);
    if (!raw) return defaultAlerts();
    const obj = JSON.parse(raw);
    return { ...defaultAlerts(), ...obj };
  }catch{
    return defaultAlerts();
  }
}

function saveAlerts(obj){
  localStorage.setItem(ALERTS_KEY, JSON.stringify(obj));
}

function loadLastAlertMap(){
  try{
    const raw = localStorage.getItem(ALERT_LAST_KEY);
    if (!raw) return {};
    return JSON.parse(raw) || {};
  }catch{
    return {};
  }
}

function saveLastAlertMap(map){
  localStorage.setItem(ALERT_LAST_KEY, JSON.stringify(map));
}

function setPill(){
  const a = loadAlerts();
  const pill = $('alertPill');
  if (!pill) return;
  pill.textContent = `Alerts: ${a.enabled ? 'On' : 'Off'}`;
}

function showToast(title, body){
  const toast = $('toast');
  $('toastTitle').textContent = title;
  $('toastBody').textContent = body;
  toast.hidden = false;

  // auto-hide after 10s
  window.clearTimeout(showToast._t);
  showToast._t = window.setTimeout(() => { toast.hidden = true; }, 10000);
}

function beep(){
  try{
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = 'sine';
    o.frequency.value = 880;
    g.gain.value = 0.0001;
    o.connect(g);
    g.connect(ctx.destination);
    o.start();
    g.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
    o.stop(ctx.currentTime + 0.36);
  }catch{}
}

function hydrateAlertsUI(){
  const a = loadAlerts();

  $('alertsEnabled').checked = !!a.enabled;
  $('soundEnabled').checked = !!a.sound;

  $('gsrBelow').value = a.gsrBelow ?? '';
  $('gsrAbove').value = a.gsrAbove ?? '';
  $('goldBelow').value = a.goldBelow ?? '';
  $('goldAbove').value = a.goldAbove ?? '';
  $('silverBelow').value = a.silverBelow ?? '';
  $('silverAbove').value = a.silverAbove ?? '';

  $('alertsStatus').textContent = a.enabled
    ? 'Alerts enabled. This page must be open for alerts to trigger.'
    : 'Alerts are currently disabled on this device.';

  setPill();
}

function readAlertsFromUI(){
  return {
    enabled: $('alertsEnabled').checked,
    sound: $('soundEnabled').checked,
    gsrBelow: parseNumOrNull($('gsrBelow').value),
    gsrAbove: parseNumOrNull($('gsrAbove').value),
    goldBelow: parseNumOrNull($('goldBelow').value),
    goldAbove: parseNumOrNull($('goldAbove').value),
    silverBelow: parseNumOrNull($('silverBelow').value),
    silverAbove: parseNumOrNull($('silverAbove').value),
  };
}

function shouldTriggerOncePerDay(key){
  const map = loadLastAlertMap();
  const now = Date.now();
  const last = map[key] || 0;
  const oneDay = 24 * 60 * 60 * 1000;
  if (now - last < oneDay) return false;
  map[key] = now;
  saveLastAlertMap(map);
  return true;
}

function checkAlerts(latest){
  const a = loadAlerts();
  if (!a.enabled) return;

  const gsr = Number(latest.gsr);
  const gold = Number(latest.gold_usd);
  const silver = Number(latest.silver_usd);

  const triggers = [];

  const pushTrigger = (k, title, body) => {
    if (shouldTriggerOncePerDay(k)) triggers.push({ title, body });
  };

  if (Number.isFinite(gsr)) {
    if (a.gsrBelow != null && gsr < a.gsrBelow) pushTrigger(`gsr_below_${a.gsrBelow}`, 'GSR Alert', `GSR is ${fmtNum(gsr,4)} (below ${fmtNum(a.gsrBelow,4)}).`);
    if (a.gsrAbove != null && gsr > a.gsrAbove) pushTrigger(`gsr_above_${a.gsrAbove}`, 'GSR Alert', `GSR is ${fmtNum(gsr,4)} (above ${fmtNum(a.gsrAbove,4)}).`);
  }

  if (Number.isFinite(gold)) {
    if (a.goldBelow != null && gold < a.goldBelow) pushTrigger(`gold_below_${a.goldBelow}`, 'Gold Alert', `Gold is $${fmtNum(gold,2)} (below $${fmtNum(a.goldBelow,2)}).`);
    if (a.goldAbove != null && gold > a.goldAbove) pushTrigger(`gold_above_${a.goldAbove}`, 'Gold Alert', `Gold is $${fmtNum(gold,2)} (above $${fmtNum(a.goldAbove,2)}).`);
  }

  if (Number.isFinite(silver)) {
    if (a.silverBelow != null && silver < a.silverBelow) pushTrigger(`silver_below_${a.silverBelow}`, 'Silver Alert', `Silver is $${fmtNum(silver,2)} (below $${fmtNum(a.silverBelow,2)}).`);
    if (a.silverAbove != null && silver > a.silverAbove) pushTrigger(`silver_above_${a.silverAbove}`, 'Silver Alert', `Silver is $${fmtNum(silver,2)} (above $${fmtNum(a.silverAbove,2)}).`);
  }

  if (triggers.length) {
    const first = triggers[0];
    showToast(first.title, first.body);
    if (a.sound) beep();
  }
}

/* -------------------------
   Delta vs yesterday
-------------------------- */

function computeDelta(latest, history){
  const latestDate = latest?.date;
  const latestGsr = Number(latest?.gsr);
  if (!Number.isFinite(latestGsr)) return null;

  const hist = Array.isArray(history) ? history.slice() : [];
  if (!hist.length) return null;

  // Determine previous day gsr
  // history typically includes latest day; we handle both cases.
  let prev = null;

  if (hist.length >= 2) {
    const last = hist[hist.length - 1];
    const prevCand = hist[hist.length - 2];

    if (last?.date === latestDate) {
      prev = prevCand;
    } else {
      prev = last;
    }
  } else {
    // Only 1 point: no delta possible
    return null;
  }

  const prevGsr = Number(prev?.gsr);
  if (!Number.isFinite(prevGsr)) return null;

  const diff = latestGsr - prevGsr;
  const pct = prevGsr === 0 ? null : (diff / prevGsr) * 100;

  return { diff, pct, prevDate: prev?.date || null };
}

function setDeltaUI(delta){
  const wrap = $('gsrDeltaWrap');
  const dEl = $('gsrDelta');
  const pEl = $('gsrDeltaPct');

  wrap.classList.remove('deltaGood','deltaBad','deltaFlat');
  if (!delta) {
    dEl.textContent = '—';
    pEl.textContent = '';
    wrap.classList.add('deltaFlat');
    return;
  }

  const sign = delta.diff > 0 ? '+' : (delta.diff < 0 ? '−' : '');
  const diffAbs = Math.abs(delta.diff);

  dEl.textContent = `${sign}${fmtNum(diffAbs, 4)}`;
  if (delta.pct == null) {
    pEl.textContent = '';
  } else {
    const pctSign = delta.pct > 0 ? '+' : (delta.pct < 0 ? '−' : '');
    pEl.textContent = `(${pctSign}${fmtNum(Math.abs(delta.pct), 2)}%)`;
  }

  if (Math.abs(delta.diff) < 1e-12) wrap.classList.add('deltaFlat');
  else if (delta.diff > 0) wrap.classList.add('deltaGood');
  else wrap.classList.add('deltaBad');
}

/* -------------------------
   Cron run-now helper
-------------------------- */

async function runCronNow(){
  // This endpoint is typically protected. We'll try with a prompt using ?secret=...
  const secret = window.prompt('Enter CRON secret to run now (this will call /api/cron_gsr?secret=...)');
  if (!secret) return;

  $('runNowBtn').disabled = true;
  $('runNowBtn').textContent = 'Running…';

  try{
    const res = await fetch(`/api/cron_gsr?secret=${encodeURIComponent(secret)}`, { cache:'no-store' });
    const out = await res.json().catch(() => ({}));
    if (res.ok && out.ok) {
      showToast('Cron triggered', 'Success. Refreshing data now…');
      await load();
    } else {
      showToast('Cron failed', out?.error ? String(out.error) : `HTTP ${res.status}`);
    }
  }catch(e){
    showToast('Cron failed', e?.message || String(e));
  }finally{
    $('runNowBtn').disabled = false;
    $('runNowBtn').textContent = 'Run Cron Now';
  }
}

/* -------------------------
   Main load
-------------------------- */

async function load() {
  $('refreshBtn').disabled = true;
  $('refreshBtn').textContent = 'Refreshing…';

  try {
    const res = await fetch('/api/latest', { cache: 'no-store' });
    const data = await res.json();

    if (!data.ok) {
      $('gsr').textContent = '—';
      $('gold').textContent = '—';
      $('silver').textContent = '—';
      $('date').textContent = '—';
      $('fetchedAt').textContent = '—';
      $('updatedHuman').textContent = '—';
      $('historyTable').innerHTML = '';
      $('range').textContent = data.error ? `Error: ${data.error}` : 'No data';
      $('emptyState').hidden = false;
      drawSpark($('spark'), [], null);
      setDeltaUI(null);
      return;
    }

    const latest = data.latest;

    $('gsr').textContent = fmtNum(latest.gsr, 4);
    $('gold').textContent = fmtNum(latest.gold_usd, 2);
    $('silver').textContent = fmtNum(latest.silver_usd, 2);
    $('date').textContent = latest.date;
    $('fetchedAt').textContent = latest.fetched_at_utc;

    const fetchedDate = isoToDateSafe(latest.fetched_at_utc);
    $('updatedHuman').textContent = fetchedDate ? timeAgo(fetchedDate) : '—';

    const hist = Array.isArray(data.history) ? data.history : [];

    // Table
    const tbody = hist.slice().reverse().map(r => `<tr><td>${r.date}</td><td>${fmtNum(r.gsr, 4)}</td></tr>`).join('');
    $('historyTable').innerHTML = tbody;

    // Range label
    const first = hist[0]?.date;
    const last = hist[hist.length - 1]?.date;
    $('range').textContent = (first && last) ? `${first} → ${last} (${hist.length} days)` : `${hist.length} days`;

    // Empty state & chart
    const onlyOne = hist.length < 2;
    $('emptyState').hidden = !onlyOne;
    drawSpark($('spark'), hist, latest);

    // Delta vs yesterday
    const delta = computeDelta(latest, hist);
    setDeltaUI(delta);

    // Alerts check (local only)
    checkAlerts(latest);

    // Alerts status line
    const a = loadAlerts();
    $('alertsStatus').textContent = a.enabled
      ? 'Alerts enabled. This page must be open for alerts to trigger. (Triggers at most once/day per threshold.)'
      : 'Alerts are currently disabled on this device.';

    setPill();
  } catch (e) {
    $('range').textContent = `Error: ${e?.message || e}`;
    showToast('Load failed', e?.message || String(e));
  } finally {
    $('refreshBtn').disabled = false;
    $('refreshBtn').textContent = 'Refresh';
  }
}

/* -------------------------
   Wire up events
-------------------------- */

function wire(){
  $('refreshBtn').addEventListener('click', load);

  $('toastClose').addEventListener('click', () => {
    $('toast').hidden = true;
  });

  $('saveAlertsBtn').addEventListener('click', () => {
    const a = readAlertsFromUI();
    saveAlerts(a);
    hydrateAlertsUI();
    showToast('Saved', 'Alert thresholds saved to this device.');
  });

  $('testAlertBtn').addEventListener('click', () => {
    showToast('Test Alert', 'If alerts are enabled, this is what an alert looks like.');
    const a = loadAlerts();
    if (a.sound) beep();
  });

  $('runNowBtn').addEventListener('click', runCronNow);

  // Update "time ago" every 15s (nice Apple-like touch)
  setInterval(() => {
    const raw = $('fetchedAt')?.textContent;
    const d = isoToDateSafe(raw);
    if (d) $('updatedHuman').textContent = timeAgo(d);
  }, 15000);
}

(function init(){
  wire();
  hydrateAlertsUI();
  load();
})();
