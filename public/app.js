const $ = (id) => document.getElementById(id);

function fmtNum(x, digits = 2) {
  const n = Number(x);
  if (!Number.isFinite(n)) return String(x);
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function drawSpark(svg, points, valueKey = "gsr") {
  svg.innerHTML = "";

  if (!points || points.length < 2) return;

  const W = 1000, H = 260, pad = 18;

  const ys = points
    .map((p) => Number(p[valueKey]))
    .filter(Number.isFinite);

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
  grid.setAttribute("stroke", "rgba(128,128,128,0.25)");
  grid.setAttribute("stroke-width", "1");
  grid.setAttribute("fill", "none");
  svg.appendChild(grid);

  // Line path
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  let d = "";
  for (let i = 0; i < points.length; i++) {
    const v = Number(points[i][valueKey]);
    if (!Number.isFinite(v)) continue;
    const x = toX(i);
    const y = toY(v);
    d += (i === 0 ? `M ${x} ${y}` : ` L ${x} ${y}`);
  }
  path.setAttribute("d", d);
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "2.5");
  path.setAttribute("fill", "none");
  path.setAttribute("opacity", "0.95");
  svg.appendChild(path);

  // Labels
  const mkText = (txt, x, y, anchor = "start") => {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.textContent = txt;
    t.setAttribute("x", String(x));
    t.setAttribute("y", String(y));
    t.setAttribute("fill", "rgba(128,128,128,0.85)");
    t.setAttribute("font-size", "16");
    t.setAttribute("font-family", "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace");
    t.setAttribute("text-anchor", anchor);
    return t;
  };
  svg.appendChild(mkText(`max ${fmtNum(maxY, 2)}`, W - pad, pad, "end"));
  svg.appendChild(mkText(`min ${fmtNum(minY, 2)}`, W - pad, H - pad, "end"));
}

function setNoDataUI(msg) {
  $("gsr").textContent = "—";
  $("gold").textContent = "—";
  $("silver").textContent = "—";
  $("date").textContent = "—";
  $("fetchedAt").textContent = "—";
  $("historyTable").innerHTML = "";
  $("range").textContent = msg || "No data";
  drawSpark($("spark"), []);
}

async function load() {
  $("refreshBtn").disabled = true;
  $("refreshBtn").textContent = "Refreshing…";

  try {
    // IMPORTANT: cap the payload
    const res = await fetch("/api/latest?limit=2000", { cache: "no-store" });
    const data = await res.json();

    if (!data.ok) {
      setNoDataUI(data.error ? `Error: ${data.error}` : "No data");
      return;
    }

    const latest = data.latest;
    $("gsr").textContent = fmtNum(latest.gsr, 4);
    $("gold").textContent = fmtNum(latest.gold_usd, 2);
    $("silver").textContent = fmtNum(latest.silver_usd, 2);
    $("date").textContent = latest.date;
    $("fetchedAt").textContent = latest.fetched_at_utc;

    const hist = Array.isArray(data.history) ? data.history : [];
    if (hist.length < 2) {
      $("historyTable").innerHTML = "";
      $("range").textContent = `${hist.length} day${hist.length === 1 ? "" : "s"}`;
      drawSpark($("spark"), []);
      return;
    }

    // Table
    const tbody = hist.slice().reverse().map(r =>
      `<tr><td>${r.date}</td><td>${fmtNum(r.gsr, 4)}</td></tr>`
    ).join("");
    $("historyTable").innerHTML = tbody;

    // Range label
    const first = hist[0]?.date;
    const last = hist[hist.length - 1]?.date;
    $("range").textContent = (first && last) ? `${first} → ${last} (${hist.length} days)` : `${hist.length} days`;

    // Chart: draw GSR (you can add additional charts later for gold/silver)
    drawSpark($("spark"), hist, "gsr");

  } catch (e) {
    setNoDataUI(`Error: ${e?.message || e}`);
  } finally {
    $("refreshBtn").disabled = false;
    $("refreshBtn").textContent = "Refresh";
  }
}

$("refreshBtn").addEventListener("click", load);
load();
