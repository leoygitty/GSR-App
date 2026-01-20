const $ = (id) => document.getElementById(id);

function fmtNum(x, digits = 2) {
  const n = Number(x);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function parseISODate(d) {
  // "YYYY-MM-DD" -> Date
  const [y, m, day] = String(d || "").split("-").map((v) => parseInt(v, 10));
  return new Date(Date.UTC(y || 1970, (m || 1) - 1, day || 1, 0, 0, 0));
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

// Downsample for MAX so charts stay responsive.
function downsample(points, maxPts = 2500) {
  if (!Array.isArray(points) || points.length <= maxPts) return points || [];
  const out = [];
  const step = (points.length - 1) / (maxPts - 1);
  for (let i = 0; i < maxPts; i++) {
    out.push(points[Math.round(i * step)]);
  }
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
  if (range === "1M") return 2000;
  if (range === "3M") return 6000;
  if (range === "6M") return 12000;
  if (range === "1Y") return 20000;
  if (range === "MAX") return 50000;
  return 5000;
}

function sortHistoryAsc(hist) {
  return (hist || []).slice().sort((a, b) => (String(a?.date || "") < String(b?.date || "") ? -1 : 1));
}

let FULL_HISTORY = [];
let CURRENT_RANGE = "1M";

// Chart.js instances
let CHART_GSR = null;
let CHART_GOLD = null;
let CHART_SILVER = null;

function destroyCharts() {
  try { CHART_GSR?.destroy(); } catch {}
  try { CHART_GOLD?.destroy(); } catch {}
  try { CHART_SILVER?.destroy(); } catch {}
  CHART_GSR = CHART_GOLD = CHART_SILVER = null;
}

function buildSeries(points, valueKey) {
  // Chart.js time scale requires {x: Date, y: Number}
  return points
    .map(p => ({ x: parseISODate(p.date), y: Number(p[valueKey]) }))
    .filter(pt => Number.isFinite(pt.y) && pt.x instanceof Date && !isNaN(pt.x.getTime()));
}

function makeChart(canvasId, label, series, yDigits, isRatio = false) {
  const ctx = $(canvasId).getContext("2d");

  return new Chart(ctx, {
    type: "line",
    data: {
      datasets: [{
        label,
        data: series,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.15
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
              if (!(d instanceof Date)) return "";
              // YYYY-MM-DD
              return d.toISOString().slice(0, 10);
            },
            label: (item) => {
              const v = item?.raw?.y;
              return `${label}: ${fmtNum(v, yDigits)}`;
            }
          }
        }
      },
      scales: {
        x: {
          type: "time",
          time: {
            tooltipFormat: "yyyy-MM-dd"
          },
          ticks: {
            maxTicksLimit: 8
          },
          grid: {
            color: "rgba(0,0,0,0.06)"
          }
        },
        y: {
          ticks: {
            callback: (v) => fmtNum(v, isRatio ? 2 : yDigits)
          },
          grid: {
            color: "rgba(0,0,0,0.06)"
          }
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

  // Rebuild charts (simple + reliable)
  destroyCharts();

  const ptsForCharts = (CURRENT_RANGE === "MAX") ? downsample(history, 2500) : history;

  if (showGsr) {
    CHART_GSR = makeChart("chartGsrCanvas", "GSR", buildSeries(ptsForCharts, "gsr"), 4, true);
  }
  if (showGold) {
    CHART_GOLD = makeChart("chartGoldCanvas", "Gold Spot (USD)", buildSeries(ptsForCharts, "gold_usd"), 2, false);
  }
  if (showSilver) {
    CHART_SILVER = makeChart("chartSilverCanvas", "Silver Spot (USD)", buildSeries(ptsForCharts, "silver_usd"), 2, false);
  }

  // Table (cap last 200)
  const tail = history.slice(-200).slice().reverse();
  $("historyTable").innerHTML = tail.map(r => (
    `<tr>
      <td>${r.date}</td>
      <td>${fmtNum(r.gsr, 4)}</td>
      <td>${fmtNum(r.gold_usd, 2)}</td>
      <td>${fmtNum(r.silver_usd, 2)}</td>
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

async function fetchHistory(limit) {
  const res = await fetch(`/api/latest?limit=${encodeURIComponent(limit)}`, { cache: "no-store" });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "No data");
  return data;
}

async function load(forRange = CURRENT_RANGE) {
  $("refreshBtn").disabled = true;
  $("refreshBtn").textContent = "Refreshing…";

  try {
    const want = desiredLimitForRange(forRange);
    const data = await fetchHistory(want);

    const latest = data.latest;
    $("gsr").textContent = fmtNum(latest.gsr, 4);
    $("gold").textContent = fmtNum(latest.gold_usd, 2);
    $("silver").textContent = fmtNum(latest.silver_usd, 2);
    $("fetchedAt").textContent = latest.fetched_at_utc || "—";
    $("source").textContent = latest.source || "—";
    $("utcDate").textContent = latest.date || "—";
    $("lastUpdatedHuman").textContent = latest.fetched_at_utc ? timeAgo(latest.fetched_at_utc) : "—";

    FULL_HISTORY = sortHistoryAsc(Array.isArray(data.history) ? data.history : []);

    // Delta
    if (FULL_HISTORY.length >= 2) {
      const prev = FULL_HISTORY[FULL_HISTORY.length - 2];
      const curr = FULL_HISTORY[FULL_HISTORY.length - 1];
      const dAbs = Number(curr.gsr) - Number(prev.gsr);
      const dPct = (Number(prev.gsr) !== 0) ? (dAbs / Number(prev.gsr)) * 100 : NaN;

      const sign = dAbs > 0 ? "+" : (dAbs < 0 ? "−" : "");
      $("deltaAbs").textContent = Number.isFinite(dAbs) ? `${sign}${fmtNum(Math.abs(dAbs), 4)}` : "—";
      $("deltaPct").textContent = Number.isFinite(dPct) ? `${sign}${fmtNum(Math.abs(dPct), 2)}%` : "—";
      $("deltaAbs").className = dAbs > 0 ? "pos" : (dAbs < 0 ? "neg" : "");
      $("deltaPct").className = dAbs > 0 ? "pos" : (dAbs < 0 ? "neg" : "");
    } else {
      $("deltaAbs").textContent = "—";
      $("deltaPct").textContent = "—";
    }

    renderCharts(filterByRange(FULL_HISTORY, CURRENT_RANGE));

  } catch (e) {
    setNoData(`Error: ${e?.message || e}`);
  } finally {
    $("refreshBtn").disabled = false;
    $("refreshBtn").textContent = "Refresh";
  }
}

$("refreshBtn").addEventListener("click", () => load(CURRENT_RANGE));

document.querySelectorAll(".segBtn").forEach((b) => {
  b.addEventListener("click", async () => {
    CURRENT_RANGE = b.dataset.range;
    setActiveRange(CURRENT_RANGE);

    // Fetch more if MAX
    if (CURRENT_RANGE === "MAX") {
      await load("MAX");
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
load(CURRENT_RANGE);

setInterval(() => {
  const txt = $("fetchedAt").textContent;
  if (txt && txt !== "—") $("lastUpdatedHuman").textContent = timeAgo(txt);
}, 10000);
