const $ = (id) => document.getElementById(id);

function fmtNum(x, digits = 2) {
  const n = Number(x);
  if (!Number.isFinite(n)) return String(x ?? "—");
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function drawSpark(svg, points) {
  svg.innerHTML = "";
  if (!points || points.length < 2) return;

  const W = 1000, H = 260, pad = 18;
  const ys = points.map((p) => Number(p.gsr)).filter(Number.isFinite);
  if (ys.length < 2) return;

  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanY = (maxY - minY) || 1;

  const toX = (i) => pad + (i * (W - 2 * pad)) / (points.length - 1);
  const toY = (v) => (H - pad) - ((v - minY) * (H - 2 * pad)) / spanY;

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

  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  let d = "";
  for (let i = 0; i < points.length; i++) {
    const v = Number(points[i].gsr);
    const x = toX(i);
    const y = toY(v);
    d += i === 0 ? `M ${x} ${y}` : ` L ${x} ${y}`;
  }
  path.setAttribute("d", d);
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "2.5");
  path.setAttribute("fill", "none");
  path.setAttribute("opacity", "0.95");
  svg.appendChild(path);

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

// Accept BOTH possible API shapes:
// (A) { ok:true, latest:{...}, history:[...] }
// (B) { ok:true, latest:{..., history:[...]} }  <-- what you currently have
// (C) older: { ok:true, gold_usd:..., silver_usd:..., gsr:..., date_utc:... }
function normalizeApi(data) {
  const latest = data.latest ?? data;
  const history = data.history ?? latest.history ?? [];
  return { ok: !!data.ok, latest, history, error: data.error };
}

function setEmpty(msg = "No data") {
  $("gsr").textContent = "—";
  $("gold").textContent = "—";
  $("silver").textContent = "—";
  $("date").textContent = "—";
  $("fetchedAt").textContent = "—";
  $("historyTable").innerHTML = "";
  $("range").textContent = msg;
  drawSpark($("spark"), []);
}

async function load() {
  const btn = $("refreshBtn");
  if (!btn) return;

  btn.disabled = true;
  btn.textContent = "Refreshing…";

  try {
    const res = await fetch("/api/latest", {
      cache: "no-store",
      headers: { "Accept": "application/json" },
    });

    // If a proxy/route ever returns HTML again, this prevents "Unexpected token <"
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      setEmpty(`Error: /api/latest returned non-JSON (status ${res.status})`);
      return;
    }

    const norm = normalizeApi(data);
    if (!norm.ok) {
      setEmpty(norm.error ? `Error: ${norm.error}` : "No data yet");
      return;
    }

    const latest = norm.latest;

    // Support date/date_utc
    const date = latest.date ?? latest.date_utc ?? "—";
    const fetchedAt = latest.fetched_at_utc ?? latest.fetched_at ?? "—";

    $("gsr").textContent = fmtNum(latest.gsr, 4);
    $("gold").textContent = fmtNum(latest.gold_usd, 2);
    $("silver").textContent = fmtNum(latest.silver_usd, 2);
    $("date").textContent = date;
    $("fetchedAt").textContent = fetchedAt;

    const hist = Array.isArray(norm.history) ? norm.history : [];
    const tbody = hist.slice().reverse()
      .map((r) => `<tr><td>${r.date ?? r.date_utc ?? "—"}</td><td>${fmtNum(r.gsr, 4)}</td></tr>`)
      .join("");
    $("historyTable").innerHTML = tbody;

    const first = hist[0]?.date ?? hist[0]?.date_utc;
    const last = hist[hist.length - 1]?.date ?? hist[hist.length - 1]?.date_utc;
    $("range").textContent =
      first && last ? `${first} → ${last} (${hist.length} days)` : `${hist.length} days`;

    drawSpark($("spark"), hist);
  } catch (e) {
    setEmpty(`Error: ${e?.message || e}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh";
  }
}

window.addEventListener("DOMContentLoaded", () => {
  const btn = $("refreshBtn");
  if (btn) btn.addEventListener("click", load);
  load();
});
