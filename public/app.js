/* global Chart */
/* MetalMetric app.js — premium charts upgrade (keeps existing data + ranges) */

const $ = (id) => document.getElementById(id);

function fmtNum(x, digits = 2) {
  const n = Number(x);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  });
}
function fmtUSD(x, digits = 2) {
  const n = Number(x);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  });
}
function parseISODate(d) {
  // "YYYY-MM-DD" -> Date (UTC midnight)
  const [y, m, day] = String(d || "").split("-").map((v) => parseInt(v, 10));
  return new Date(Date.UTC(y || 1970, (m || 1) - 1, day || 1, 0, 0, 0));
}
function isoFromDate(dt) {
  if (!(dt instanceof Date) || isNaN(dt.getTime())) return "";
  return dt.toISOString().slice(0, 10);
}
function timeAgo(iso) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (sec < 10) return "a few seconds ago";
  if (sec < 60) return `${sec} seconds ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} minute${min === 1 ? "" : "s"} ago`;
  const hr = Math.floor(min / 60);
  if (hr < 48) return `${hr} hour${hr === 1 ? "" : "s"} ago`;
  const day = Math.floor(hr / 24);
  return `${day} day${day === 1 ? "" : "s"} ago`;
}

// Keep MAX fast
function downsample(points, maxPts = 3000) {
  if (!Array.isArray(points) || points.length <= maxPts) return points || [];
  const out = [];
  const step = (points.length - 1) / (maxPts - 1);
  for (let i = 0; i < maxPts; i++) out.push(points[Math.round(i * step)]);
  return out;
}

function setActiveRange(range) {
  document.querySelectorAll(".segBtn").forEach((b) => {
    b.classList.toggle("isActive", b.dataset.range === range);
  });
}
function filterByRange(history, range) {
  if (!history || history.length === 0) return [];
  if (range === "MAX") return history;
  const end = parseISODate(history[history.length - 1].date);
  const start = new Date(end.getTime());
  if (range === "1M") start.setUTCMonth(start.getUTCMonth() - 1);
  if (range === "3M") start.setUTCMonth(start.getUTCMonth() - 3);
  if (range === "6M") start.setUTCMonth(start.getUTCMonth() - 6);
  if (range === "1Y") start.setUTCFullYear(start.getUTCFullYear() - 1);
  return history.filter((r) => parseISODate(r.date) >= start);
}
function desiredLimitForRange(range) {
  if (range === "1M") return 3000;
  if (range === "3M") return 9000;
  if (range === "6M") return 18000;
  if (range === "1Y") return 30000;
  if (range === "MAX") return 80000;
  return 5000;
}
function sortHistoryAsc(hist) {
  return (hist || []).slice().sort((a, b) => (String(a?.date || "") < String(b?.date || "") ? -1 : 1));
}

/* -----------------------------
   Premium charts: theme + sync
   ----------------------------- */

let ENTITLEMENT_TIER = "elite"; // safe default (unlocked) if /api/entitlement isn't implemented
let FULL_HISTORY = [];
let CURRENT_RANGE = "1M";

let CHART_GSR = null;
let CHART_GOLD = null;
let CHART_SILVER = null;

const MM_CHARTS = []; // { key, chart }

function isDarkMode() {
  const el = document.documentElement;
  const t = (el.getAttribute("data-theme") || "").toLowerCase();
  if (t) return t.includes("dark");
  return el.classList.contains("dark");
}

function getChartPalette() {
  // Pull from CSS vars if present; otherwise fallback.
  const cs = getComputedStyle(document.documentElement);
  const grid = (cs.getPropertyValue("--mm-grid") || "").trim();
  const tick = (cs.getPropertyValue("--mm-tick") || "").trim();
  const text = (cs.getPropertyValue("--mm-text") || "").trim();
  const bg = (cs.getPropertyValue("--mm-bg") || "").trim();

  if (grid || tick || text || bg) {
    return {
      grid: grid || (isDarkMode() ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.08)"),
      tick: tick || (isDarkMode() ? "rgba(255,255,255,0.78)" : "rgba(0,0,0,0.72)"),
      text: text || (isDarkMode() ? "rgba(255,255,255,0.92)" : "rgba(0,0,0,0.92)"),
      tooltipBg: isDarkMode() ? "rgba(10,12,16,0.92)" : "rgba(255,255,255,0.95)",
      tooltipBorder: isDarkMode() ? "rgba(255,255,255,0.14)" : "rgba(0,0,0,0.10)"
    };
  }

  return {
    grid: isDarkMode() ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.08)",
    tick: isDarkMode() ? "rgba(255,255,255,0.78)" : "rgba(0,0,0,0.72)",
    text: isDarkMode() ? "rgba(255,255,255,0.92)" : "rgba(0,0,0,0.92)",
    tooltipBg: isDarkMode() ? "rgba(10,12,16,0.92)" : "rgba(255,255,255,0.95)",
    tooltipBorder: isDarkMode() ? "rgba(255,255,255,0.14)" : "rgba(0,0,0,0.10)"
  };
}

function applyChartTheme(chart) {
  if (!chart) return;
  const pal = getChartPalette();

  chart.options.scales.x.grid.color = pal.grid;
  chart.options.scales.y.grid.color = pal.grid;

  chart.options.scales.x.ticks.color = pal.tick;
  chart.options.scales.y.ticks.color = pal.tick;

  chart.options.plugins.tooltip.backgroundColor = pal.tooltipBg;
  chart.options.plugins.tooltip.borderColor = pal.tooltipBorder;
  chart.options.plugins.tooltip.titleColor = pal.text;
  chart.options.plugins.tooltip.bodyColor = pal.text;

  chart.update("none");
}

function applyAllChartThemes() {
  [CHART_GSR, CHART_GOLD, CHART_SILVER].forEach(applyChartTheme);
}

/* Crosshair draw plugin (synced hover) */
const mmCrosshairPlugin = {
  id: "mmCrosshairPlugin",
  afterDraw(chart) {
    const x = chart.$mmCrosshairX;
    if (typeof x !== "number") return;
    const { ctx, chartArea } = chart;
    if (!chartArea) return;

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.lineWidth = 1;
    ctx.strokeStyle = isDarkMode() ? "rgba(200,180,255,0.35)" : "rgba(90,60,180,0.22)";
    ctx.stroke();
    ctx.restore();
  }
};

/* Glow-on-hover plugin (subtle “breathe”) */
const mmGlowPlugin = {
  id: "mmGlowPlugin",
  beforeDatasetsDraw(chart) {
    const active = chart.getActiveElements ? chart.getActiveElements() : (chart._active || []);
    if (!active || !active.length) return;

    const { ctx } = chart;
    ctx.save();
    ctx.shadowBlur = 18;
    ctx.shadowColor = isDarkMode() ? "rgba(140,110,255,0.35)" : "rgba(120,90,220,0.22)";
  },
  afterDatasetsDraw(chart) {
    const active = chart.getActiveElements ? chart.getActiveElements() : (chart._active || []);
    if (!active || !active.length) return;
    chart.ctx.restore();
  }
};

try { Chart.register(mmCrosshairPlugin); } catch {}
try { Chart.register(mmGlowPlugin); } catch {}

function destroyCharts() {
  try { CHART_GSR?.$mmCleanup?.(); } catch {}
  try { CHART_GOLD?.$mmCleanup?.(); } catch {}
  try { CHART_SILVER?.$mmCleanup?.(); } catch {}

  try { CHART_GSR?.destroy(); } catch {}
  try { CHART_GOLD?.destroy(); } catch {}
  try { CHART_SILVER?.destroy(); } catch {}

  CHART_GSR = CHART_GOLD = CHART_SILVER = null;
  MM_CHARTS.length = 0;
}

function buildSeries(points, key) {
  return points
    .map(p => {
      const x = parseISODate(p.date);
      const y = Number(p[key]);
      return { x, y };
    })
    .filter(pt => pt.x instanceof Date && !isNaN(pt.x.getTime()) && Number.isFinite(pt.y));
}

function pickTimeUnit(range) {
  if (range === "1M") return "day";
  if (range === "3M") return "week";
  if (range === "6M") return "month";
  if (range === "1Y") return "month";
  return "year";
}

function findNearestIndex(xs, target) {
  // xs = sorted numbers
  if (!xs || xs.length === 0) return -1;
  let lo = 0, hi = xs.length - 1;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (xs[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  const i = lo;
  if (i <= 0) return 0;
  if (i >= xs.length) return xs.length - 1;
  const a = xs[i - 1], b = xs[i];
  return (Math.abs(a - target) <= Math.abs(b - target)) ? (i - 1) : i;
}

function setPointDetails(html) {
  const el = $("pointDetails");
  if (!el) return;
  if (!html) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  el.innerHTML = html;
  el.classList.remove("hidden");
  window.clearTimeout(el.$mmT);
  el.$mmT = window.setTimeout(() => setPointDetails(""), 4500);
}

function syncHoverFromX(xMs) {
  // Update all charts to nearest x
  MM_CHARTS.forEach(({ chart }) => {
    try {
      const data = chart.data?.datasets?.[0]?.data || [];
      const xs = chart.$mmXs || (chart.$mmXs = data.map(d => (d?.x instanceof Date ? d.x.getTime() : NaN)).filter(Number.isFinite));
      if (!xs.length) return;

      const idx = findNearestIndex(xs, xMs);
      const meta = chart.getDatasetMeta(0);
      const el = meta?.data?.[idx];
      if (!el) return;

      chart.setActiveElements([{ datasetIndex: 0, index: idx }]);
      chart.tooltip.setActiveElements([{ datasetIndex: 0, index: idx }], { x: el.x, y: el.y });
      chart.$mmCrosshairX = el.x;
      chart.update("none");
    } catch {}
  });
}

function clearHoverSync() {
  MM_CHARTS.forEach(({ chart }) => {
    try {
      chart.setActiveElements([]);
      chart.tooltip.setActiveElements([], { x: 0, y: 0 });
      chart.$mmCrosshairX = null;
      chart.update("none");
    } catch {}
  });
}

function wireChartInteractions(key, chart, getSnapshotRowByDate) {
  if (!chart?.canvas) return;

  const canvas = chart.canvas;

  const onMove = (ev) => {
    // Locked charts (free) should not run interactions
    if (ENTITLEMENT_TIER === "free") return;

    const rect = canvas.getBoundingClientRect();
    const clientX = ev.touches?.[0]?.clientX ?? ev.clientX;
    if (!Number.isFinite(clientX)) return;

    const xPixel = clientX - rect.left;
    const xVal = chart.scales.x.getValueForPixel(xPixel);
    const xMs = (xVal instanceof Date) ? xVal.getTime() : Number(xVal);

    if (!Number.isFinite(xMs)) return;
    syncHoverFromX(xMs);
  };

  const onLeave = () => {
    if (ENTITLEMENT_TIER === "free") return;
    clearHoverSync();
  };

  const onClick = () => {
    if (ENTITLEMENT_TIER === "free") return;

    try {
      const active = chart.getActiveElements();
      const a = active?.[0];
      if (!a) return;

      const d = chart.data.datasets[0].data[a.index];
      const dt = d?.x instanceof Date ? isoFromDate(d.x) : "";
      if (!dt) return;

      const row = getSnapshotRowByDate(dt);
      if (!row) return;

      setPointDetails(
        `<div><strong>${row.date}</strong></div>
         <div>GSR: <strong>${fmtNum(row.gsr, 4)}</strong> &nbsp; Gold: <strong>${fmtUSD(row.gold_usd, 2)}</strong> &nbsp; Silver: <strong>${fmtUSD(row.silver_usd, 2)}</strong></div>`
      );
    } catch {}
  };

  // Touch + mouse
  canvas.addEventListener("mousemove", onMove, { passive: true });
  canvas.addEventListener("touchmove", onMove, { passive: true });
  canvas.addEventListener("mouseleave", onLeave, { passive: true });
  canvas.addEventListener("touchend", onLeave, { passive: true });
  canvas.addEventListener("click", onClick);

  // Double click = reset zoom (dopamine snap)
  canvas.addEventListener("dblclick", () => {
    if (typeof chart.resetZoom === "function") chart.resetZoom();
  });

  chart.$mmCleanup = () => {
    canvas.removeEventListener("mousemove", onMove);
    canvas.removeEventListener("touchmove", onMove);
    canvas.removeEventListener("mouseleave", onLeave);
    canvas.removeEventListener("touchend", onLeave);
    canvas.removeEventListener("click", onClick);
  };
}

function makeLineChart(canvasId, label, series, yFmtFn, unit, key, getSnapshotRowByDate) {
  const el = $(canvasId);
  if (!el) return null;

  const ctx = el.getContext("2d");
  const pal = getChartPalette();

  // Note: We intentionally keep dataset styling conservative to avoid breaking rendering.
  const chart = new Chart(ctx, {
    type: "line",
    data: {
      datasets: [{
        label,
        data: series,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHitRadius: 14,
        tension: 0.18
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      normalized: true,
      parsing: false,
      interaction: { mode: "index", intersect: false },
      animation: {
        duration: 520,
        easing: "easeInOutQuart"
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: true,
          backgroundColor: pal.tooltipBg,
          borderColor: pal.tooltipBorder,
          borderWidth: 1,
          titleColor: pal.text,
          bodyColor: pal.text,
          callbacks: {
            title: (items) => {
              const d = items?.[0]?.raw?.x;
              return d instanceof Date ? isoFromDate(d) : "";
            },
            label: (item) => `${label}: ${yFmtFn(item?.raw?.y)}`
          }
        },

        // Zoom / pan (plugin ignores if not loaded)
        zoom: {
          pan: {
            enabled: ENTITLEMENT_TIER !== "free",
            mode: "x",
            modifierKey: "shift"
          },
          zoom: {
            wheel: { enabled: ENTITLEMENT_TIER !== "free", modifierKey: "ctrl" },
            pinch: { enabled: ENTITLEMENT_TIER !== "free" },
            drag: { enabled: ENTITLEMENT_TIER !== "free" },
            mode: "x"
          }
        },

        // Annotation (only used in expanded mode if you later enable it)
        annotation: { annotations: {} }
      },
      scales: {
        x: {
          type: "time",
          time: {
            unit,
            tooltipFormat: "yyyy-MM-dd",
            displayFormats: {
              day: "MMM d",
              week: "MMM d",
              month: "MMM yyyy",
              year: "yyyy"
            }
          },
          ticks: {
            maxTicksLimit: 8,
            autoSkip: true,
            color: pal.tick
          },
          grid: { color: pal.grid }
        },
        y: {
          ticks: {
            callback: (v) => yFmtFn(v),
            color: pal.tick
          },
          grid: { color: pal.grid }
        }
      }
    }
  });

  MM_CHARTS.push({ key, chart });

  // Interactions: synced hover + click details
  wireChartInteractions(key, chart, getSnapshotRowByDate);

  return chart;
}

function applyEntitlementToUI() {
  const root = document.documentElement;
  root.setAttribute("data-tier", ENTITLEMENT_TIER);

  const overlay = $("chartsLockOverlay");
  const chartsWrap = $("chartsWrap");
  if (!overlay || !chartsWrap) return;

  const dismissed = localStorage.getItem("mm_lock_dismissed") === "1";
  if (ENTITLEMENT_TIER === "free" && !dismissed) {
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
    chartsWrap.style.filter = "blur(4px) saturate(0.9)";
    chartsWrap.style.opacity = "0.85";
    chartsWrap.style.pointerEvents = "none";
  } else {
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
    chartsWrap.style.filter = "";
    chartsWrap.style.opacity = "";
    chartsWrap.style.pointerEvents = "";
  }
}

async function fetchEntitlementSafe() {
  // If endpoint missing, keep unlocked (elite) so you don’t “lock yourself out”.
  try {
    const res = await fetch(`/api/entitlement?_t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json().catch(() => null);
    const tier = String(data?.tier || "").toLowerCase();
    if (tier === "free" || tier === "pro" || tier === "elite") {
      ENTITLEMENT_TIER = tier;
    }
  } catch {}
}

/* -----------------------------
   Existing render logic (kept)
   ----------------------------- */

function renderCharts(history) {
  const empty = $("emptyState");
  const chartsWrap = $("chartsWrap");

  if (!empty || !chartsWrap) return;

  if (!history || history.length < 2) {
    empty.classList.remove("hidden");
    chartsWrap.classList.add("hidden");
    $("rangeLabel").textContent = history?.length ? `${history[0].date} → ${history[0].date} (1 pt)` : "—";
    destroyCharts();
    $("historyTable").innerHTML = "";
    return;
  }

  empty.classList.add("hidden");
  chartsWrap.classList.remove("hidden");

  const first = history[0].date;
  const last = history[history.length - 1].date;
  $("rangeLabel").textContent = `${first} → ${last} (${history.length} pts)`;

  const showGsr = $("showGsr").checked;
  const showGold = $("showGold").checked;
  const showSilver = $("showSilver").checked;

  $("chartGsr").classList.toggle("hidden", !showGsr);
  $("chartGold").classList.toggle("hidden", !showGold);
  $("chartSilver").classList.toggle("hidden", !showSilver);

  // Preserve your original behavior (destroy + rebuild) to avoid breaking history rendering.
  destroyCharts();

  const unit = pickTimeUnit(CURRENT_RANGE);
  const pts = (CURRENT_RANGE === "MAX") ? downsample(history, 3000) : history;

  // For click popover, we want a quick lookup by date:
  const byDate = new Map(pts.map(r => [r.date, r]));
  const getRow = (isoDate) => byDate.get(isoDate) || null;

  if (showGsr) {
    CHART_GSR = makeLineChart(
      "chartGsrCanvas",
      "GSR",
      buildSeries(pts, "gsr"),
      (v) => fmtNum(v, 2),
      unit,
      "gsr",
      getRow
    );
  }
  if (showGold) {
    CHART_GOLD = makeLineChart(
      "chartGoldCanvas",
      "Gold Spot (USD)",
      buildSeries(pts, "gold_usd"),
      (v) => fmtUSD(v, 2),
      unit,
      "gold",
      getRow
    );
  }
  if (showSilver) {
    CHART_SILVER = makeLineChart(
      "chartSilverCanvas",
      "Silver Spot (USD)",
      buildSeries(pts, "silver_usd"),
      (v) => fmtUSD(v, 2),
      unit,
      "silver",
      getRow
    );
  }

  // Ensure chart text/grid recolors immediately on theme toggle
  applyAllChartThemes();

  // Table: last 200 rows, newest first
  const tail = history.slice(-200).slice().reverse();
  $("historyTable").innerHTML = tail.map(r => (
    `<tr>
      <td>${r.date}</td>
      <td>${fmtNum(r.gsr, 4)}</td>
      <td>${fmtUSD(r.gold_usd, 2)}</td>
      <td>${fmtUSD(r.silver_usd, 2)}</td>
    </tr>`
  )).join("");
}

function setNoData(errMsg) {
  $("gsr").textContent = "—";
  $("gold").textContent = "—";
  $("silver").textContent = "—";
  $("fetchedAt").textContent = "—";
  $("source").textContent = "—";
  $("utcDate").textContent = "—";
  $("lastUpdatedHuman").textContent = "—";
  $("deltaAbs").textContent = "—";
  $("deltaPct").textContent = "—";
  $("rangeLabel").textContent = errMsg || "No data";
  FULL_HISTORY = [];
  renderCharts([]);
}

/**
 * Fetch from /api/latest, with:
 * - cache-buster
 * - explicit no-store
 * - optional force=1 to trigger self-heal immediately
 */
async function fetchLatest(limit, { force = false } = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (force) params.set("force", "1");
  params.set("_t", String(Date.now()));
  const url = `/api/latest?${params.toString()}`;

  const res = await fetch(url, {
    cache: "no-store",
    headers: {
      "Cache-Control": "no-cache",
      "Pragma": "no-cache"
    }
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function load(forRange = CURRENT_RANGE, { force = false } = {}) {
  $("refreshBtn").disabled = true;
  $("refreshBtn").textContent = force ? "Refreshing (live)…" : "Refreshing…";

  try {
    const want = desiredLimitForRange(forRange);
    const data = await fetchLatest(want, { force });

    const latest = data.latest;
    $("gsr").textContent = fmtNum(latest.gsr, 4);
    $("gold").textContent = fmtUSD(latest.gold_usd, 2);
    $("silver").textContent = fmtUSD(latest.silver_usd, 2);
    $("fetchedAt").textContent = latest.fetched_at_utc || "—";
    $("source").textContent = latest.source || "—";
    $("utcDate").textContent = latest.date || "—";
    $("lastUpdatedHuman").textContent = latest.fetched_at_utc ? timeAgo(latest.fetched_at_utc) : "—";

    FULL_HISTORY = sortHistoryAsc(Array.isArray(data.history) ? data.history : []);

    // Delta vs previous
    if (FULL_HISTORY.length >= 2) {
      const prev = FULL_HISTORY[FULL_HISTORY.length - 2];
      const curr = FULL_HISTORY[FULL_HISTORY.length - 1];
      const dAbs = Number(curr.gsr) - Number(prev.gsr);
      const dPct = (Number(prev.gsr) !== 0) ? (dAbs / Number(prev.gsr)) * 100 : NaN;
      const isUp = Number.isFinite(dAbs) && dAbs > 0;
      const isDown = Number.isFinite(dAbs) && dAbs < 0;
      const sign = isUp ? "+" : (isDown ? "-" : "");
      $("deltaAbs").textContent = Number.isFinite(dAbs) ? `${sign}${fmtNum(Math.abs(dAbs), 4)}` : "—";
      $("deltaPct").textContent = Number.isFinite(dPct) ? `${sign}${fmtNum(Math.abs(dPct), 2)}%` : "—";
      $("deltaAbs").className = isUp ? "pos" : (isDown ? "neg" : "");
      $("deltaPct").className = isUp ? "pos" : (isDown ? "neg" : "");
    } else {
      $("deltaAbs").textContent = "—";
      $("deltaPct").textContent = "—";
      $("deltaAbs").className = "";
      $("deltaPct").className = "";
    }

    renderCharts(filterByRange(FULL_HISTORY, CURRENT_RANGE));

    // Keep the teaser/lock UI consistent after load
    applyEntitlementToUI();

  } catch (e) {
    setNoData(`Error: ${e?.message || e}`);
  } finally {
    $("refreshBtn").disabled = false;
    $("refreshBtn").textContent = "Refresh";
  }
}

/* -----------------------------
   Home page wiring (safe guards)
   ----------------------------- */

function initPremiumChartControls() {
  const expandBtn = $("chartsExpandBtn");
  const closeBtn = $("chartsCloseBtn");
  const resetBtn = $("chartsResetZoomBtn");
  const lockDismissBtn = $("lockDismissBtn");

  if (lockDismissBtn) {
    lockDismissBtn.addEventListener("click", () => {
      localStorage.setItem("mm_lock_dismissed", "1");
      applyEntitlementToUI();
    });
  }

  const resetAllZoom = () => {
    [CHART_GSR, CHART_GOLD, CHART_SILVER].forEach(c => {
      try { if (typeof c?.resetZoom === "function") c.resetZoom(); } catch {}
    });
  };

  if (resetBtn) resetBtn.addEventListener("click", resetAllZoom);

  const openExpanded = async () => {
    document.body.classList.add("mmChartsExpanded");
    if (closeBtn) closeBtn.classList.remove("hidden");

    // Mobile: true fullscreen if available
    const card = $("chartsCard");
    if (card && window.matchMedia("(max-width: 820px)").matches) {
      try { await card.requestFullscreen?.(); } catch {}
    }

    // Re-apply theme in expanded mode
    applyAllChartThemes();
  };

  const closeExpanded = async () => {
    document.body.classList.remove("mmChartsExpanded");
    if (closeBtn) closeBtn.classList.add("hidden");

    if (document.fullscreenElement) {
      try { await document.exitFullscreen?.(); } catch {}
    }

    applyAllChartThemes();
  };

  if (expandBtn) expandBtn.addEventListener("click", openExpanded);
  if (closeBtn) closeBtn.addEventListener("click", closeExpanded);

  // ESC closes expanded (desktop)
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("mmChartsExpanded")) {
      closeExpanded();
    }
  });

  // If fullscreen is exited by gesture, keep classes consistent
  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && document.body.classList.contains("mmChartsExpanded")) {
      document.body.classList.remove("mmChartsExpanded");
      if (closeBtn) closeBtn.classList.add("hidden");
    }
  });
}

async function initHome() {
  // If this page doesn’t have your dashboard elements, do nothing.
  if (!$("refreshBtn") || !$("chartsWrap") || !$("chartGsrCanvas")) return;

  // Entitlement: if route exists, apply gating; otherwise stay unlocked.
  await fetchEntitlementSafe();
  applyEntitlementToUI();

  // Hook theme changes so charts recolor immediately (NO refresh needed)
  const mo = new MutationObserver(() => {
    applyAllChartThemes();
  });
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });

  initPremiumChartControls();

  $("refreshBtn").addEventListener("click", () => load(CURRENT_RANGE, { force: true }));

  document.querySelectorAll(".segBtn").forEach((b) => {
    b.addEventListener("click", async () => {
      CURRENT_RANGE = b.dataset.range;
      setActiveRange(CURRENT_RANGE);

      // Reset zoom on range switch for predictable UX
      try { CHART_GSR?.resetZoom?.(); } catch {}
      try { CHART_GOLD?.resetZoom?.(); } catch {}
      try { CHART_SILVER?.resetZoom?.(); } catch {}

      if (CURRENT_RANGE === "MAX") {
        await load("MAX", { force: false });
      } else {
        renderCharts(filterByRange(FULL_HISTORY, CURRENT_RANGE));
      }
    });
  });

  ["showGold", "showSilver", "showGsr"].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.addEventListener("change", () => {
      renderCharts(filterByRange(FULL_HISTORY, CURRENT_RANGE));
    });
  });

  setActiveRange(CURRENT_RANGE);

  // Initial load: no force (fast path)
  load(CURRENT_RANGE, { force: false });

  // Existing: update "time ago"
  setInterval(() => {
    const txt = $("fetchedAt").textContent;
    if (txt && txt !== "—") $("lastUpdatedHuman").textContent = timeAgo(txt);
  }, 10000);

  // Auto-refresh hourly while the page is open (non-forced)
  setInterval(() => {
    load(CURRENT_RANGE, { force: false });
  }, 60 * 60 * 1000);

  // When user returns to the tab, refresh once (forced)
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) load(CURRENT_RANGE, { force: true });
  });
}

/* Start Home init */
initHome();

/* -----------------------------
   Melt Calculator Logic (unchanged)
   ----------------------------- */
document.addEventListener('DOMContentLoaded', () => {
  if (!document.querySelector('.metal-tab')) return;  // Only run on melt page

  let spots = { gold: 0, silver: 0, platinum: 0 };
  const purities = {
    gold: { '24K': 0.999, '22K': 0.916, '21K': 0.875, '18K': 0.75, '14K': 0.583, '10K': 0.417, '9K': 0.375 },
    silver: { '.999': 0.999, '.925': 0.925, '.958': 0.958, '.950': 0.950, '.900': 0.900, '.400': 0.400, '.350': 0.350 },
    platinum: { '.999': 0.999, '.950': 0.950, '.900': 0.900, '.850': 0.85 }
  };
  const unitsToGrams = { g: 1, ozt: 31.1034768, dwt: 1.55517384, kg: 1000, oz: 28.3495231, lb: 453.59237 };
  const gramToTroyOz = 0.0321507466;

  // Fetch spots
  fetch('/api/spot')
    .then(res => res.json())
    .then(data => {
      spots = data;
      calculate();
    });

  const tabs = document.querySelectorAll('.metal-tab');
  const purityOptions = document.getElementById('purity-options');
  const weightInput = document.getElementById('weight');
  const unitSelect = document.getElementById('unit');
  const output = document.getElementById('output');
  let currentMetal = 'gold';
  let currentPurity = Object.keys(purities.gold)[0];

  // Render purity buttons
  function renderPurities(metal) {
    purityOptions.innerHTML = '';
    Object.keys(purities[metal]).forEach(key => {
      const btn = document.createElement('button');
      btn.className = `purity-btn ${key === currentPurity ? 'active' : ''}`;
      btn.textContent = key;
      btn.onclick = () => {
        document.querySelectorAll('.purity-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentPurity = key;
        calculate();
      };
      purityOptions.appendChild(btn);
    });
  }

  // Tab switch
  tabs.forEach(tab => {
    tab.onclick = () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      currentMetal = tab.dataset.metal;
      currentPurity = Object.keys(purities[currentMetal])[0];
      renderPurities(currentMetal);
      calculate();
    };
  });

  // Inputs change
  weightInput.oninput = unitSelect.onchange = calculate;

  function calculate() {
    const weight = parseFloat(weightInput.value) || 0;
    if (weight <= 0) {
      output.classList.add('output-hidden');
      return;
    }
    const unitFactor = unitsToGrams[unitSelect.value];
    const grams = weight * unitFactor;
    const purityDecimal = purities[currentMetal][currentPurity];
    const pureGrams = grams * purityDecimal;
    const troyOz = pureGrams * gramToTroyOz;
    const spot = spots[currentMetal];
    const value = (troyOz * spot).toFixed(2);

    document.getElementById('total-value').textContent = `$${value}`;
    document.getElementById('summary').textContent = `${weight} ${unitSelect.value} of ${currentPurity} ${currentMetal.charAt(0).toUpperCase() + currentMetal.slice(1)}`;
    document.getElementById('out-weight').textContent = `${grams.toFixed(3)} g`;
    document.getElementById('out-purity').textContent = `${(purityDecimal * 100).toFixed(1)}%`;
    document.getElementById('out-pure').textContent = `${pureGrams.toFixed(3)} g / ${troyOz.toFixed(3)} oz t`;
    document.getElementById('out-spot').textContent = `$${spot.toFixed(2)} / oz t`;

    output.classList.remove('output-hidden');
  }

  // Init
  renderPurities('gold');
  calculate();
});

// Accordion (if not already in app.js)
document.querySelectorAll('details').forEach(d => d.addEventListener('toggle', () => {/* optional exclusive */}));
