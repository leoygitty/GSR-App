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

/* =========================
   STRIPE CHECKOUT (Pro/Elite + monthly/yearly)
   - Calls /api/create_checkout_session (POST JSON)
   - Exposes window.startCheckout(plan, interval)
   - Optional: auto-binds any element with:
       data-checkout-plan="pro|elite"
       data-checkout-interval="monthly|yearly"
   ========================= */

async function mmReadJsonSafe(res) {
  try {
    return await res.json();
  } catch {
    const txt = await res.text().catch(() => "");
    return { ok: false, error: txt || `HTTP ${res.status}` };
  }
}

function mmNormalizePlan(v) {
  const p = String(v || "").trim().toLowerCase();
  return (p === "pro" || p === "elite") ? p : "";
}

function mmNormalizeInterval(v) {
  const i = String(v || "").trim().toLowerCase();
  return (i === "monthly" || i === "yearly") ? i : "monthly";
}

async function mmCreateCheckoutSession(plan, interval) {
  const p = mmNormalizePlan(plan);
  const i = mmNormalizeInterval(interval);
  if (!p) throw new Error("Invalid plan. Use 'pro' or 'elite'.");

  const res = await fetch("/api/create_checkout_session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan: p, interval: i })
  });

  const data = await mmReadJsonSafe(res);
  if (!res.ok || !data.ok || !data.url) {
    throw new Error(data?.error || `Checkout failed (HTTP ${res.status})`);
  }
  return data.url;
}

async function startCheckout(plan, interval) {
  const url = await mmCreateCheckoutSession(plan, interval);
  window.location.href = url;
}

// expose for inline onclick or console testing
window.startCheckout = startCheckout;

// Optional auto-bind (no effect unless you add these attributes in HTML)
(function mmBindCheckoutButtons() {
  function bind() {
    document.querySelectorAll("[data-checkout-plan]").forEach((el) => {
      if (el.__mmCheckoutBound) return;
      el.__mmCheckoutBound = true;

      el.addEventListener("click", async (e) => {
        e.preventDefault();
        const plan = el.getAttribute("data-checkout-plan");
        const interval = el.getAttribute("data-checkout-interval") || "monthly";

        const prevText = el.textContent;
        try {
          el.disabled = true;
          el.textContent = "Redirecting…";
          await startCheckout(plan, interval);
        } catch (err) {
          el.disabled = false;
          el.textContent = prevText;
          console.error(err);
          alert(err?.message || String(err));
        }
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();

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

/* =========================
   THEME-SAFE CHART STYLING
   - Fixes “ticks not changing until refresh”
   - Prevents “blank line” when defaults get overridden
   ========================= */

function mmIsDark() {
  return (document.documentElement.getAttribute("data-theme") || "light").toLowerCase() === "dark";
}

function mmThemeTokens() {
  const dark = mmIsDark();
  return {
    dark,
    tick:  dark ? "rgba(255,255,255,.78)" : "rgba(17,17,20,.72)",
    grid:  dark ? "rgba(255,255,255,.08)" : "rgba(17,17,20,.10)",
    title: dark ? "rgba(255,255,255,.88)" : "rgba(17,17,20,.86)",
    tipTitle: dark ? "rgba(255,255,255,.92)" : "rgba(17,17,20,.92)",
    tipBody:  dark ? "rgba(255,255,255,.86)" : "rgba(17,17,20,.86)",
    tipBg:    dark ? "rgba(0,0,0,.78)" : "rgba(255,255,255,.92)",
    tipBorder:dark ? "rgba(255,255,255,.12)" : "rgba(17,17,20,.10)"
  };
}

function mmLineColorForLabel(label) {
  const t = String(label || "").toLowerCase();
  if (t.includes("gsr")) return "rgba(139,92,246,0.95)";      // violet
  if (t.includes("gold")) return "rgba(245,158,11,0.95)";     // gold
  if (t.includes("silver")) return mmIsDark()
    ? "rgba(226,232,240,0.92)"                                // silver (dark)
    : "rgba(71,85,105,0.92)";                                 // slate (light)
  return mmIsDark() ? "rgba(226,232,240,0.90)" : "rgba(71,85,105,0.90)";
}

function mmApplyThemeToChart(chart) {
  if (!chart || !chart.options) return;
  const tok = mmThemeTokens();

  // Root options
  chart.options.color = tok.tick;
  chart.options.borderColor = tok.grid;

  // Scales
  if (chart.options.scales) {
    Object.values(chart.options.scales).forEach(sc => {
      sc.ticks = sc.ticks || {};
      sc.grid = sc.grid || {};
      sc.border = sc.border || {};
      sc.title = sc.title || {};
      sc.ticks.color = tok.tick;
      sc.grid.color = tok.grid;
      sc.border.color = tok.grid;
      sc.title.color = tok.title;
    });
  }

  // Legend / Tooltip
  chart.options.plugins = chart.options.plugins || {};
  chart.options.plugins.legend = chart.options.plugins.legend || {};
  chart.options.plugins.legend.labels = chart.options.plugins.legend.labels || {};
  chart.options.plugins.legend.labels.color = tok.tick;

  chart.options.plugins.tooltip = chart.options.plugins.tooltip || {};
  chart.options.plugins.tooltip.titleColor = tok.tipTitle;
  chart.options.plugins.tooltip.bodyColor = tok.tipBody;
  chart.options.plugins.tooltip.backgroundColor = tok.tipBg;
  chart.options.plugins.tooltip.borderColor = tok.tipBorder;
  chart.options.plugins.tooltip.borderWidth = 1;

  // Dataset line color (prevents invisible lines)
  if (chart.data?.datasets?.[0]) {
    const ds = chart.data.datasets[0];
    ds.borderColor = mmLineColorForLabel(ds.label);
    ds.pointHoverBorderColor = ds.borderColor;
  }

  chart.update("none");
}

function mmApplyThemeToAllCharts() {
  try { mmApplyThemeToChart(CHART_GSR); } catch {}
  try { mmApplyThemeToChart(CHART_GOLD); } catch {}
  try { mmApplyThemeToChart(CHART_SILVER); } catch {}
}

function makeLineChart(canvasId, label, series, yFmtFn, unit) {
  const el = $(canvasId);
  if (!el) return null;
  const ctx = el.getContext("2d");
  const tok = mmThemeTokens();

  return new Chart(ctx, {
    type: "line",
    data: {
      datasets: [{
        label,
        data: series,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.18,
        // Explicit line color so it never disappears under theme/default changes
        borderColor: mmLineColorForLabel(label)
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },

      // Theme-aware root colors (so ticks react properly)
      color: tok.tick,
      borderColor: tok.grid,

      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const d = items?.[0]?.raw?.x;
              return d instanceof Date ? isoFromDate(d) : "";
            },
            label: (item) => `${label}: ${yFmtFn(item?.raw?.y)}`
          },
          titleColor: tok.tipTitle,
          bodyColor: tok.tipBody,
          backgroundColor: tok.tipBg,
          borderColor: tok.tipBorder,
          borderWidth: 1
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
            autoSkip: true,
            color: tok.tick
          },
          grid: { color: tok.grid },
          border: { color: tok.grid }
        },
        y: {
          ticks: {
            callback: (v) => yFmtFn(v),
            color: tok.tick
          },
          grid: { color: tok.grid },
          border: { color: tok.grid }
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

  // Apply theme immediately after chart creation (fixes “needs refresh”)
  mmApplyThemeToAllCharts();

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
  const refreshBtn = $("refreshBtn");
  if (refreshBtn) {
    refreshBtn.disabled = true;
    refreshBtn.textContent = force ? "Refreshing (live)…" : "Refreshing…";
  }

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
    const refreshBtn2 = $("refreshBtn");
    if (refreshBtn2) {
      refreshBtn2.disabled = false;
      refreshBtn2.textContent = "Refresh";
    }
  }
}

/**
 * UX policy:
 * - Manual Refresh: force=1 (try to get live intraday now)
 * - Hourly auto-refresh: force=false (only updates if stale)
 * - When tab becomes visible: force=1 (user returning expects fresh)
 */
const refreshBtn = $("refreshBtn");
if (refreshBtn) refreshBtn.addEventListener("click", () => load(CURRENT_RANGE, { force: true }));

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
  const txt = $("fetchedAt")?.textContent;
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

/* Theme observer: updates chart text colors immediately on toggle */
(function () {
  const root = document.documentElement;
  const mo = new MutationObserver(() => {
    // Run on next paint, and once again shortly after (mobile/Safari safety)
    requestAnimationFrame(() => {
      try { mmApplyThemeToAllCharts(); } catch {}
    });
    setTimeout(() => {
      try { mmApplyThemeToAllCharts(); } catch {}
    }, 120);
  });
  mo.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
})();

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
