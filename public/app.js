/* global Chart */
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
let FULL_HISTORY = [];
let CURRENT_RANGE = "1M";
let CHART_GSR = null;
let CHART_GOLD = null;
let CHART_SILVER = null;
function destroyCharts() {
  try { CHART_GSR?.destroy(); } catch {}
  try { CHART_GOLD?.destroy(); } catch {}
  try { CHART_SILVER?.destroy(); } catch {}
  CHART_GSR = CHART_GOLD = CHART_SILVER = null;
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
  // Makes x-axis readable at different ranges
  if (range === "1M") return "day";
  if (range === "3M") return "week";
  if (range === "6M") return "month";
  if (range === "1Y") return "month";
  return "year"; // MAX
}
function makeLineChart(canvasId, label, series, yFmtFn, unit) {
  const el = $(canvasId);
  if (!el) return null;
  const ctx = el.getContext("2d");
  return new Chart(ctx, {
    type: "line",
    data: {
      datasets: [{
        label,
        data: series,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.18
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const d = items?.[0]?.raw?.x;
              return d instanceof Date ? isoFromDate(d) : "";
            },
            label: (item) => `${label}: ${yFmtFn(item?.raw?.y)}`
          }
        }
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
            autoSkip: true
          },
          grid: { color: "rgba(0,0,0,0.06)" }
        },
        y: {
          ticks: {
            callback: (v) => yFmtFn(v)
          },
          grid: { color: "rgba(0,0,0,0.06)" }
        }
      }
    }
  });
}
function renderCharts(history) {
  const empty = $("emptyState");
  const chartsWrap = $("chartsWrap");
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
  destroyCharts();
  const unit = pickTimeUnit(CURRENT_RANGE);
  const pts = (CURRENT_RANGE === "MAX") ? downsample(history, 3000) : history;
  if (showGsr) {
    CHART_GSR = makeLineChart(
      "chartGsrCanvas",
      "GSR",
      buildSeries(pts, "gsr"),
      (v) => fmtNum(v, 2),
      unit
    );
  }
  if (showGold) {
    CHART_GOLD = makeLineChart(
      "chartGoldCanvas",
      "Gold Spot (USD)",
      buildSeries(pts, "gold_usd"),
      (v) => fmtUSD(v, 2),
      unit
    );
  }
  if (showSilver) {
    CHART_SILVER = makeLineChart(
      "chartSilverCanvas",
      "Silver Spot (USD)",
      buildSeries(pts, "silver_usd"),
      (v) => fmtUSD(v, 2),
      unit
    );
  }
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
    // Delta vs previous (small polish: consistent sign, avoid "+0.00", use ASCII "-")
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
  } catch (e) {
    setNoData(`Error: ${e?.message || e}`);
  } finally {
    $("refreshBtn").disabled = false;
    $("refreshBtn").textContent = "Refresh";
  }
}
/**
 * UX policy:
 * - Manual Refresh: force=1 (try to get live intraday now)
 * - Hourly auto-refresh: force=false (only updates if stale)
 * - When tab becomes visible: force=1 (user returning expects fresh)
 */
$("refreshBtn").addEventListener("click", () => load(CURRENT_RANGE, { force: true }));
document.querySelectorAll(".segBtn").forEach((b) => {
  b.addEventListener("click", async () => {
    CURRENT_RANGE = b.dataset.range;
    setActiveRange(CURRENT_RANGE);
    // For MAX we fetch bigger history; for others, reuse the already-fetched history
    if (CURRENT_RANGE === "MAX") {
      await load("MAX", { force: false });
    } else {
      renderCharts(filterByRange(FULL_HISTORY, CURRENT_RANGE));
    }
  });
});
["showGold", "showSilver", "showGsr"].forEach((id) => {
  $(id).addEventListener("change", () => {
    renderCharts(filterByRange(FULL_HISTORY, CURRENT_RANGE));
  });
});

setActiveRange(CURRENT_RANGE);

/* =========================================================
   FIX: Chart tick/axis text color updates immediately on
   light/dark toggle WITHOUT requiring manual Refresh.
   - No refetch
   - No history changes
   - Simply rebuild charts from in-memory FULL_HISTORY
   ========================================================= */
(function setupImmediateChartThemeRefresh(){
  // Only activate on the dashboard page that has charts
  const hasCharts =
    !!$("chartGsrCanvas") || !!$("chartGoldCanvas") || !!$("chartSilverCanvas");
  if (!hasCharts) return;

  const root = document.documentElement;

  const getTheme = () => {
    const t = (root.getAttribute("data-theme") || "light").toLowerCase();
    return (t === "dark" || t === "light") ? t : "light";
  };

  let lastTheme = getTheme();
  let timer = null;

  const softRebuild = () => {
    // Rebuild charts from existing FULL_HISTORY so Chart.js resolves new theme colors
    if (Array.isArray(FULL_HISTORY) && FULL_HISTORY.length >= 2) {
      renderCharts(filterByRange(FULL_HISTORY, CURRENT_RANGE));
    } else {
      // If charts exist but history isn't loaded yet, at least try to re-style existing charts
      try { CHART_GSR?.update("none"); } catch {}
      try { CHART_GOLD?.update("none"); } catch {}
      try { CHART_SILVER?.update("none"); } catch {}
    }

    // If your index.html exposes a helper, run it after rebuild (safe no-op if missing)
    try { window.mmApplyChartTheme && window.mmApplyChartTheme(); } catch (e) {}
  };

  const schedule = () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      softRebuild();
    }, 0);
  };

  // Watch for <html data-theme="..."> changes
  const mo = new MutationObserver(() => {
    const now = getTheme();
    if (now === lastTheme) return;
    lastTheme = now;
    schedule();
  });
  mo.observe(root, { attributes: true, attributeFilter: ["data-theme"] });

  // Extra safety: if the toggle button is clicked, schedule a rebuild as well
  const btn = $("themeToggle");
  if (btn) btn.addEventListener("click", schedule);
})();

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

// Melt Calculator Logic
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
