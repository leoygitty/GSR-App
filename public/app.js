const $ = (id) => document.getElementById(id);

function fmtNum(x, digits = 2) {
  const n = Number(x);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function parseISODate(d) {
  // d = "YYYY-MM-DD"
  const [y, m, day] = d.split("-").map((v) => parseInt(v, 10));
  return new Date(Date.UTC(y, (m || 1) - 1, day || 1, 0, 0, 0));
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

function drawSpark(svg, points, key, colorCss = "currentColor") {
  svg.innerHTML = "";
  if (!points || points.length < 2) return;

  const W = 1000, H = 260, pad = 18;
  const ys = points.map(p => Number(p[key])).filter(Number.isFinite);
  if (ys.length < 2) return;

  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanY = (maxY - minY) || 1;

  const toX = (i) => pad + (i * (W - 2 * pad)) / (points.length - 1);
  const toY = (v) => (H - pad) - ((v - minY) * (H - 2 * pad)) / spanY;

  // Grid
  const grid = document.createElementNS("http://www.w3.org/2000/svg", "path");
  let gridD = "";
  for (let i = 0; i < 5; i++) {
    const y = pad + (i * (H - 2 * pad)) / 4;
    gridD += `M ${pad} ${y} L ${W - pad} ${y} `;
  }
  grid.setAttribute("d", gridD);
  grid.setAttribute("stroke", "rgba(128,128,128,0.20)");
  grid.setAttribute("stroke-width", "1");
  grid.setAttribute("fill", "none");
  svg.appendChild(grid);

  // Line
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  let d = "";
  for (let i = 0; i < points.length; i++) {
    const v = Number(points[i][key]);
    const x = toX(i);
    const y = toY(v);
    d += (i === 0 ? `M ${x} ${y}` : ` L ${x} ${y}`);
  }
  path.setAttribute("d", d);
  path.setAttribute("stroke", colorCss);
  path.setAttribute("stroke-width", "2.5");
  path.setAttribute("fill", "none");
  path.setAttribute("opacity", "0.95");
  svg.appendChild(path);

  // Min/Max
  const mkText = (txt, x, y, anchor = "start") => {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.textContent = txt;
    t.setAttribute("x", String(x));
    t.setAttribute("y", String(y));
    t.setAttribute("fill", "rgba(128,128,128,0.85)");
    t.setAttribute("font-size", "14");
    t.setAttribute("font-family", "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace");
    t.setAttribute("text-anchor", anchor);
    return t;
  };
  svg.appendChild(mkText(`max ${fmtNum(maxY, 2)}`, W - pad, pad, "end"));
  svg.appendChild(mkText(`min ${fmtNum(minY, 2)}`, W - pad, H - pad, "end"));
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

let FULL_HISTORY = [];
let CURRENT_RANGE = "1M";

function render(history) {
  // Empty state logic
  const empty = $("emptyState");
  const chartsWrap = $("chartsWrap");

  if (!history || history.length < 2) {
    empty.classList.remove("hidden");
    chartsWrap.classList.add("hidden");
    $("rangeLabel").textContent = history?.length ? `${history[0].date} → ${history[0].date} (1 pt)` : "—";
    $("historyTable").innerHTML = "";
    $("sparkGsr").innerHTML = "";
    $("sparkGold").innerHTML = "";
    $("sparkSilver").innerHTML = "";
    return;
  }

  empty.classList.add("hidden");
  chartsWrap.classList.remove("hidden");

  const first = history[0].date;
  const last = history[history.length - 1].date;
  $("rangeLabel").textContent = `${first} → ${last} (${history.length} pts)`;

  // Series toggles
  const showGsr = $("showGsr").checked;
  const showGold = $("showGold").checked;
  const showSilver = $("showSilver").checked;

  $("chartGsr").classList.toggle("hidden", !showGsr);
  $("chartGold").classList.toggle("hidden", !showGold);
  $("chartSilver").classList.toggle("hidden", !showSilver);

  if (showGsr) drawSpark($("sparkGsr"), history, "gsr");
  if (showGold) drawSpark($("sparkGold"), history, "gold_usd");
  if (showSilver) drawSpark($("sparkSilver"), history, "silver_usd");

  // Table (cap to last 200 rows for sanity)
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
  render([]);
}

async function load() {
  $("refreshBtn").disabled = true;
  $("refreshBtn").textContent = "Refreshing…";

  try {
    // Limit protects the UI + payload sizes
    const res = await fetch("/api/latest?limit=5000", { cache: "no-store" });
    const data = await res.json();

    if (!data.ok) {
      setNoData(data.error ? `Error: ${data.error}` : "No data");
      return;
    }

    const latest = data.latest;
    $("gsr").textContent = fmtNum(latest.gsr, 4);
    $("gold").textContent = fmtNum(latest.gold_usd, 2);
    $("silver").textContent = fmtNum(latest.silver_usd, 2);
    $("fetchedAt").textContent = latest.fetched_at_utc || "—";
    $("source").textContent = latest.source || "—";
    $("utcDate").textContent = latest.date || "—";
    $("lastUpdatedHuman").textContent = latest.fetched_at_utc ? timeAgo(latest.fetched_at_utc) : "—";

    FULL_HISTORY = Array.isArray(data.history) ? data.history : [];

    // Delta vs previous point
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

    const sliced = filterByRange(FULL_HISTORY, CURRENT_RANGE);
    render(sliced);

  } catch (e) {
    setNoData(`Error: ${e?.message || e}`);
  } finally {
    $("refreshBtn").disabled = false;
    $("refreshBtn").textContent = "Refresh";
  }
}

$("refreshBtn").addEventListener("click", load);

document.querySelectorAll(".segBtn").forEach((b) => {
  b.addEventListener("click", () => {
    CURRENT_RANGE = b.dataset.range;
    setActiveRange(CURRENT_RANGE);
    render(filterByRange(FULL_HISTORY, CURRENT_RANGE));
  });
});

["showGold", "showSilver", "showGsr"].forEach((id) => {
  $(id).addEventListener("change", () => {
    render(filterByRange(FULL_HISTORY, CURRENT_RANGE));
  });
});

setActiveRange(CURRENT_RANGE);
load();

// Update the "Last updated" label every 10s
setInterval(() => {
  const txt = $("fetchedAt").textContent;
  if (txt && txt !== "—") $("lastUpdatedHuman").textContent = timeAgo(txt);
}, 10000);
