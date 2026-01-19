const $ = (id) => document.getElementById(id);

function fmtNum(x, digits=2) {
  const n = Number(x);
  if (!Number.isFinite(n)) return String(x);
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function isoToDateSafe(s){
  try{
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }catch{ return null; }
}

function timeAgo(date){
  if (!date) return '—';
  const sec = Math.round((Date.now() - date.getTime())/1000);
  const abs = Math.abs(sec);
  if (abs < 10) return 'a few seconds ago';
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric:'auto' });
  if (abs < 60) return rtf.format(-sec, 'second');
  const min = Math.round(sec/60);
  if (Math.abs(min) < 60) return rtf.format(-min, 'minute');
  const hr = Math.round(min/60);
  if (Math.abs(hr) < 24) return rtf.format(-hr, 'hour');
  const day = Math.round(hr/24);
  return rtf.format(-day, 'day');
}

function getCssVar(name){
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Draw a simple sparkline with grid + date labels.
 * points: [{date, value}]
 */
function drawLine(svg, points, { digits=2 } = {}) {
  svg.innerHTML = '';
  const W = 1000, H = 260, pad = 18;

  const gridStroke = getCssVar('--grid') || 'rgba(128,128,128,0.22)';
  const textFill = getCssVar('--chartText') || 'rgba(128,128,128,0.78)';
  const lineColor = getCssVar('--accent') || '#0a84ff';

  if (!points || points.length < 2) return;

  const ys = points.map(p => Number(p.value)).filter(Number.isFinite);
  if (ys.length < 2) return;

  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanY = (maxY - minY) || 1;

  const toX = (i) => pad + (i * (W - 2*pad)) / (points.length - 1);
  const toY = (v) => (H - pad) - ((v - minY) * (H - 2*pad)) / spanY;

  // grid
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

  // line
  const path = document.createElementNS('http://www.w3.org/2000/svg','path');
  let d = '';
  for (let i=0;i<points.length;i++) {
    const v = Number(points[i].value);
    d += (i===0 ? `M ${toX(i)} ${toY(v)}` : ` L ${toX(i)} ${toY(v)}`);
  }
  path.setAttribute('d', d);
  path.setAttribute('stroke', lineColor);
  path.setAttribute('stroke-width', '2.5');
  path.setAttribute('fill', 'none');
  path.setAttribute('opacity', '0.95');
  svg.appendChild(path);

  // min/max labels
  const mkText = (txt, x, y, anchor='start') => {
    const t = document.createElementNS('http://www.w3.org/2000/svg','text');
    t.textContent = txt;
    t.setAttribute('x', String(x));
    t.setAttribute('y', String(y));
    t.setAttribute('fill', textFill);
    t.setAttribute('font-size', '16');
    t.setAttribute('font-family', 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace');
    t.setAttribute('text-anchor', anchor);
    return t;
  };
  svg.appendChild(mkText(`max ${fmtNum(maxY,digits)}`, W-pad, pad, 'end'));
  svg.appendChild(mkText(`min ${fmtNum(minY,digits)}`, W-pad, H-pad, 'end'));

  // X-axis date labels (start/mid/end)
  const start = points[0]?.date;
  const mid = points[Math.floor(points.length/2)]?.date;
  const end = points[points.length-1]?.date;

  const mkDate = (txt, x) => {
    const t = document.createElementNS('http://www.w3.org/2000/svg','text');
    t.textContent = txt;
    t.setAttribute('x', String(x));
    t.setAttribute('y', String(H - 6));
    t.setAttribute('fill', textFill);
    t.setAttribute('font-size', '14');
    t.setAttribute('font-family', 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace');
    t.setAttribute('text-anchor', 'middle');
    return t;
  };

  svg.appendChild(mkDate(start, toX(0)));
  svg.appendChild(mkDate(mid, toX(Math.floor(points.length/2))));
  svg.appendChild(mkDate(end, toX(points.length-1)));
}

let RANGE = '30';

function sliceHistory(hist){
  if (RANGE === 'max') return hist;
  const n = Number(RANGE);
  if (!Number.isFinite(n) || n <= 0) return hist;
  return hist.slice(Math.max(0, hist.length - n));
}

function setRangeButtons(val){
  document.querySelectorAll('.segBtn').forEach(b => {
    b.classList.toggle('active', b.dataset.range === val);
  });
}

function setEmpty(id, show){
  const el = $(id);
  if (el) el.hidden = !show;
}

async function load() {
  $('refreshBtn').disabled = true;
  $('refreshBtn').textContent = 'Refreshing…';

  try {
    const res = await fetch('/api/latest', { cache: 'no-store' });
    const data = await res.json();

    if (!data.ok) throw new Error(data.error || 'No data');

    const latest = data.latest;
    $('gsr').textContent = fmtNum(latest.gsr, 4);
    $('gold').textContent = fmtNum(latest.gold_usd, 2);
    $('silver').textContent = fmtNum(latest.silver_usd, 2);
    $('date').textContent = latest.date;
    $('fetchedAt').textContent = latest.fetched_at_utc;

    const fd = isoToDateSafe(latest.fetched_at_utc);
    $('updatedHuman').textContent = timeAgo(fd);

    const histRaw = Array.isArray(data.history) ? data.history : [];
    const hist = sliceHistory(histRaw);

    // Table (full)
    $('historyTable').innerHTML = hist.slice().reverse().map(r => (
      `<tr>
        <td>${r.date}</td>
        <td>${fmtNum(r.gold_usd, 2)}</td>
        <td>${fmtNum(r.silver_usd, 2)}</td>
        <td>${fmtNum(r.gsr, 4)}</td>
      </tr>`
    )).join('');

    const first = hist[0]?.date;
    const last = hist[hist.length-1]?.date;

    // Build series
    const gsrPts = hist.map(r => ({ date: r.date, value: r.gsr })).filter(p => Number.isFinite(Number(p.value)));
    const goldPts = hist.map(r => ({ date: r.date, value: r.gold_usd })).filter(p => Number.isFinite(Number(p.value)));
    const silverPts = hist.map(r => ({ date: r.date, value: r.silver_usd })).filter(p => Number.isFinite(Number(p.value)));

    // empty-state if <2 points
    setEmpty('emptyGsr', gsrPts.length < 2);
    setEmpty('emptyGold', goldPts.length < 2);
    setEmpty('emptySilver', silverPts.length < 2);

    // show/hide chart cards based on toggles
    $('chartCardGsr').style.display = $('showGsr').checked ? '' : 'none';
    $('chartCardGold').style.display = $('showGold').checked ? '' : 'none';
    $('chartCardSilver').style.display = $('showSilver').checked ? '' : 'none';

    // draw charts
    drawLine($('sparkGsr'), gsrPts, { digits: 2 });
    drawLine($('sparkGold'), goldPts, { digits: 0 });
    drawLine($('sparkSilver'), silverPts, { digits: 2 });

    // chart range labels
    const label = (first && last) ? `${first} → ${last} (${hist.length} pts)` : `${hist.length} pts`;
    $('rangeGsr').textContent = label;
    $('rangeGold').textContent = label;
    $('rangeSilver').textContent = label;

  } catch (e) {
    console.error(e);
  } finally {
    $('refreshBtn').disabled = false;
    $('refreshBtn').textContent = 'Refresh';
  }
}

$('refreshBtn').addEventListener('click', load);

document.querySelectorAll('.segBtn').forEach(btn => {
  btn.addEventListener('click', () => {
    RANGE = btn.dataset.range;
    setRangeButtons(RANGE);
    load();
  });
});

['showGold','showSilver','showGsr'].forEach(id => {
  $(id).addEventListener('change', load);
});

setRangeButtons(RANGE);
load();

// update timeago
setInterval(() => {
  const raw = $('fetchedAt')?.textContent;
  const d = isoToDateSafe(raw);
  if (d) $('updatedHuman').textContent = timeAgo(d);
}, 15000);
