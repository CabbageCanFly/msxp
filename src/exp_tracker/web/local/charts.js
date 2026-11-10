// Charts for /local and its pop-out, ported from product.js (drawExpHistory, drawPercentageHistory,
// drawDailyHistory, drawHourChart, bucketHistory) so they look and behave like the live site, but fed
// from local readings instead of the API. product.js itself is unchanged.

const numbers = new Intl.NumberFormat('en-US'), shortNumber = new Intl.NumberFormat('en-US', {maximumSignificantDigits: 3});
const wholeNumbers = new Intl.NumberFormat('en-US', {maximumFractionDigits: 0});
const localDates = new Intl.DateTimeFormat(undefined, {dateStyle: 'medium', timeStyle: 'long'});
const clockMinutes = new Intl.DateTimeFormat('en-GB', {hour: '2-digit', minute: '2-digit'});
const clockSeconds = new Intl.DateTimeFormat('en-GB', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
const monthDay = new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric'});
const zoneLabel = () => new Intl.DateTimeFormat('en-US', {timeZoneName: 'short'}).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value ?? 'local time';

// Same formatting as the live site: 12.3K / 4.56M, or the whole number.
export function expText(value, full = false) {
  if (value == null) return '—';
  if (full) return wholeNumbers.format(value);
  const n = Number(value), scale = n >= 1e9 ? 1e9 : n >= 1e6 ? 1e6 : n >= 1e3 ? 1e3 : 1;
  return (scale === 1 ? numbers : shortNumber).format(n / scale) + ({1: '', 1000: 'K', 1000000: 'M', 1000000000: 'B'}[scale]);
}
export const localTime = (stamp) => localDates.format(new Date(stamp));

// ---------- tooltips (product.js showTip/inspect) ----------
let tip = null, tipKey = null;
export function hideTip() { if (tip) tip.hidden = true; tipKey = null; }
function showTip(target, position = null) {
  if (!tip) { tip = document.createElement('div'); tip.className = 'chart-tooltip'; tip.id = 'chart-tooltip'; tip.setAttribute('role', 'tooltip'); document.body.append(tip); }
  tipKey = target.dataset.tipKey; tip.textContent = target.dataset.tipText; tip.hidden = false;
  target.setAttribute('aria-describedby', 'chart-tooltip');
  const box = target.getBoundingClientRect(), size = tip.getBoundingClientRect();
  const x = position?.x ?? box.left + box.width / 2, y = position?.y ?? box.top;
  tip.style.left = Math.max(8, Math.min(innerWidth - size.width - 8, x - size.width / 2)) + 'px';
  tip.style.top = Math.max(8, Math.min(innerHeight - size.height - 8, y - size.height - 12 >= 8 ? y - size.height - 12 : box.bottom + 10)) + 'px';
}
function inspect(target, key, text) {
  Object.assign(target.dataset, {tipKey: key, tipText: text});
  target.setAttribute('tabindex', '0'); target.setAttribute('role', 'img'); target.setAttribute('aria-label', text);
  target.addEventListener('pointerenter', (e) => { if (e.pointerType !== 'touch') showTip(target, {x: e.clientX, y: e.clientY}); });
  target.addEventListener('pointerleave', () => { if (document.activeElement !== target) hideTip(); });
  target.addEventListener('focus', () => showTip(target)); target.addEventListener('blur', hideTip);
  target.addEventListener('pointerdown', (e) => { if (e.pointerType === 'touch') { if (tipKey === key) hideTip(); else showTip(target); } });
  return target;
}

function drawer(svg) {
  return (tag, attrs, title) => {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (title) { const t = document.createElementNS('http://www.w3.org/2000/svg', 'title'); t.textContent = title; n.append(t); }
    svg.append(n); return n;
  };
}

/**
 * EXP per bucket from accepted intervals ({start, end, gain, level} in ms). Visualization only, as on the
 * live site: a gain is spread evenly over its own interval; buckets without observed intervals are
 * 'missing' (drawn as a dash), never zero.
 */
export function bucketHistory(intervals, anchor, seconds, range) {
  if (!range || !Number.isFinite(anchor)) return null;
  const step = seconds * 1000, end = Math.ceil(anchor / step) * step, start = end - range * 1000;
  const bins = Array.from({length: Math.round(range / seconds)}, (_, i) => ({start: start + i * step, end: start + (i + 1) * step, value: null, covered: 0}));
  for (const g of intervals) {
    const a = g.start, b = g.end;
    if (!(b > a) || b - a > 3600e3 || b <= start || a >= end) continue;
    for (const bin of bins) {
      const overlap = Math.max(0, Math.min(b, bin.end) - Math.max(a, bin.start));
      if (!overlap) continue;
      bin.value = (bin.value ?? 0) + g.gain * overlap / (b - a);
      bin.covered += overlap / 1000;
    }
  }
  for (const bin of bins) bin.state = bin.value == null ? 'missing' : bin.covered < seconds - .01 ? 'partial' : 'covered';
  return {start, end, bins, range, seconds};
}

// Bar chart: EXP gained per 1/5/30-minute bucket (drawExpHistory).
export function drawExpChart(svg, intervals, {anchor, seconds, range}) {
  svg.replaceChildren();
  const chart = bucketHistory(intervals, anchor, seconds, range);
  if (!chart) return '';
  const width = Math.max(300, Math.min(960, svg.clientWidth || 960)), plotWidth = width - 76;
  svg.setAttribute('viewBox', `0 20 ${width} 230`); svg.setAttribute('aria-label', 'EXP gained over time; dashes mean no data');
  const max = Math.max(1, ...chart.bins.map((b) => b.value ?? 0)), scale = 10 ** Math.floor(Math.log10(max)), top = Math.ceil(max / scale) * scale;
  const yValue = (v) => 200 - v / top * 160, x = (t) => 54 + (t - chart.start) / (chart.end - chart.start) * plotWidth;
  const shape = drawer(svg);
  for (let i = 0; i <= 4; i++) {
    const y = 200 - i * 40;
    shape('line', {x1: 54, x2: width - 22, y1: y, y2: y, class: 'chart-grid'});
    shape('text', {x: 44, y: y + 4, 'text-anchor': 'end'}).textContent = expText(top * i / 4);
  }
  for (const bin of chart.bins) {
    const left = x(bin.start) + 2, w = Math.max(2, x(bin.end) - x(bin.start) - 4), height = bin.value == null ? 0 : Math.max(2, Math.abs(yValue(bin.value) - yValue(0)));
    shape('rect', {x: left, y: bin.state === 'missing' ? 205 : yValue(bin.value), width: w, height: bin.state === 'missing' ? 2 : height, rx: 2,
      class: bin.state === 'missing' ? 'exp-column missing' : 'exp-column'});
    inspect(shape('rect', {x: left, y: 25, width: w, height: 183, fill: 'transparent', class: 'bar-hit'}), `bar:${bin.start}`,
      `${localTime(bin.start)}\n${bin.value == null ? 'No data (not zero EXP)' : `${expText(bin.value, true)} EXP`}`);
  }
  const ticks = width < 600 ? 3 : 5;
  for (let i = 0; i < ticks; i++) {
    const tick = new Date(chart.start + (chart.end - chart.start) * i / (ticks - 1));
    const attrs = {x: 54 + plotWidth * i / (ticks - 1), 'text-anchor': i === 0 ? 'start' : i === ticks - 1 ? 'end' : 'middle'};
    shape('text', {...attrs, y: 232}).textContent = clockMinutes.format(tick);
    if (chart.range >= 43200) shape('text', {...attrs, y: 248}).textContent = monthDay.format(tick);
  }
  const count = chart.bins.filter((b) => b.value != null).length;
  return `${chart.seconds / 60} min per bar · last ${chart.range < 3600 ? chart.range / 60 + ' min' : chart.range / 3600 + ' hours'} · times in ${zoneLabel()}${count ? '' : ' · no data in this period'}`;
}

// Line chart: Level % of accepted readings, level-ups marked (drawPercentageHistory).
export function drawPercentChart(svg, readings, {anchor, minutes}) {
  svg.replaceChildren();
  svg.setAttribute('aria-label', 'Level % over time; level-ups are marked');
  const width = Math.max(300, Math.min(960, svg.clientWidth || 960)), plotWidth = width - 100;
  svg.setAttribute('viewBox', `0 0 ${width} 230`);
  const first = anchor - minutes * 60000, last = anchor;
  const points = readings.filter((r) => r.at >= first && r.at <= last);
  const values = points.map((p) => p.bp / 100), min = values.length ? Math.min(...values) : 0, max = values.length ? Math.max(...values) : 100;
  const padding = Math.max(.01, (max - min) * .1), low = Math.max(0, min - padding), high = Math.min(100, max + padding);
  const shape = drawer(svg);
  const x = (t) => 60 + (t - first) / Math.max(1, last - first) * plotWidth, y = (v) => 190 - (v - low) / Math.max(.01, high - low) * 165;
  const ticks = width < 600 ? 3 : 5;
  for (let i = 1; i < (ticks - 1) * 2; i++) shape('line', {x1: 60 + plotWidth * i / ((ticks - 1) * 2), x2: 60 + plotWidth * i / ((ticks - 1) * 2), y1: 20, y2: 190, class: 'line-grid'});
  for (let i = 0; i <= 4; i++) {
    const value = low + (high - low) * i / 4;
    shape('line', {x1: 60, x2: width - 40, y1: y(value), y2: y(value), class: i ? 'line-grid' : 'chart-axis'});
    shape('line', {x1: 56, x2: 60, y1: y(value), y2: y(value), class: 'chart-tick'});
    shape('text', {x: 52, y: y(value) + 4, 'text-anchor': 'end'}).textContent = value.toFixed(2) + '%';
  }
  shape('line', {x1: 60, x2: 60, y1: 20, y2: 190, class: 'chart-axis'});
  // A new session or baseline starts a new line: unobserved time is never drawn as progress.
  points.forEach((p, i) => {
    const previous = points[i - 1];
    if (previous && p.gain != null && p.sessionId === previous.sessionId) shape('line', {x1: x(previous.at), y1: y(previous.bp / 100), x2: x(p.at), y2: y(p.bp / 100), class: 'trend'});
    shape('circle', {cx: x(p.at), cy: y(p.bp / 100), r: 4, class: 'sample'});
  });
  points.forEach((p, i) => {
    if (i && p.level !== points[i - 1].level) {
      shape('line', {x1: x(p.at), x2: x(p.at), y1: 20, y2: 190, class: 'level-transition'});
      shape('text', {x: Math.min(width - 75, x(p.at) + 4), y: 16, class: 'level-transition-label'}).textContent = p.level > points[i - 1].level ? `Level ${p.level}!` : `Lv. ${p.level}`;
    }
  });
  for (let i = 0; i < ticks; i++) {
    const time = first + (last - first) * i / (ticks - 1);
    shape('line', {x1: x(time), x2: x(time), y1: 190, y2: 195, class: 'chart-tick'});
    shape('text', {x: 60 + plotWidth * i / (ticks - 1), y: 218, 'text-anchor': i === 0 ? 'start' : i === ticks - 1 ? 'end' : 'middle'}).textContent = clockSeconds.format(new Date(time));
  }
  points.forEach((p, i) => {
    const left = i ? (x(points[i - 1].at) + x(p.at)) / 2 : 60, right = i + 1 < points.length ? (x(p.at) + x(points[i + 1].at)) / 2 : width - 40;
    inspect(shape('rect', {x: left, y: 20, width: right - left, height: 182, fill: 'transparent', class: 'point-hit'}), `point:${p.at}`,
      `${localTime(p.at)}\nLv. ${p.level} · ${(p.bp / 100).toFixed(2)}%\n${expText(p.exp, true)} EXP`);
    shape('line', {x1: x(p.at), x2: x(p.at), y1: 20, y2: 202, class: 'point-guide', 'aria-hidden': 'true'});
  });
  return `Last ${minutes} min · times in ${zoneLabel()}${points.length ? '' : ' · no data in this period'}`;
}

// Daily history: one point per day (level + %), kept indefinitely (drawDailyHistory).
export function drawDailyChart(svg, days, {now, range}) {
  svg.replaceChildren();
  svg.setAttribute('aria-label', 'Historical level and EXP progress');
  const start = now - range * 86400000;
  const points = days.filter((d) => d.at >= start).map((d) => ({...d, time: d.at, value: d.level * 10000 + d.bp}));
  const width = Math.max(300, Math.min(960, svg.clientWidth || 960)), left = 60, right = width - 40;
  svg.setAttribute('viewBox', `0 0 ${width} 230`);
  const shape = drawer(svg);
  if (!points.length) { shape('text', {x: width / 2, y: 110, 'text-anchor': 'middle'}).textContent = 'This character’s history is still building.'; return; }
  let first = points[0].time, last = points.at(-1).time;
  if (first === last) { first -= 43200000; last += 43200000; }
  const min = Math.min(...points.map((r) => r.value)), max = Math.max(...points.map((r) => r.value)), padding = Math.max(100, max - min) * .1;
  const low = Math.max(10000, Math.floor(min - padding)), high = Math.ceil(max + padding);
  const x = (t) => left + (t - first) / (last - first) * (right - left), y = (v) => 190 - (v - low) / (high - low) * 170;
  const ticks = Math.max(2, Math.min(7, Math.floor((right - left) / 110) + 1, Math.floor((last - first) / 86400000) + 1));
  for (let i = 1; i < (ticks - 1) * 2; i++) { const position = left + (right - left) * i / ((ticks - 1) * 2); shape('line', {x1: position, x2: position, y1: 20, y2: 190, class: 'line-grid'}); }
  for (let i = 0; i <= 4; i++) {
    const value = Math.round(low + (high - low) * i / 4), level = Math.floor(value / 10000), pct = numbers.format((value % 10000) / 100);
    shape('line', {x1: left, x2: right, y1: y(value), y2: y(value), class: i ? 'line-grid' : 'chart-axis'});
    if (i % 2 === 0) {
      shape('line', {x1: left - 4, x2: left, y1: y(value), y2: y(value), class: 'chart-tick'});
      const label = shape('text', {x: left - 8, y: y(value) - 3, 'text-anchor': 'end'}); label.textContent = level;
      const percent = document.createElementNS('http://www.w3.org/2000/svg', 'tspan'); percent.setAttribute('x', left - 8); percent.setAttribute('dy', 14); percent.textContent = `(${pct}%)`; label.append(percent);
    }
  }
  shape('line', {x1: left, x2: left, y1: 20, y2: 190, class: 'chart-axis'});
  points.forEach((r, i) => {
    const previous = points[i - 1];
    if (previous) shape('line', {x1: x(previous.time), y1: y(previous.value), x2: x(r.time), y2: y(r.value), class: 'trend'});
    shape('circle', {cx: x(r.time), cy: y(r.value), r: 4, class: 'sample'});
  });
  const dates = new Intl.DateTimeFormat(undefined, {month: '2-digit', day: '2-digit'}), shown = new Set();
  for (let i = 0; i < ticks; i++) {
    const stamp = first + (last - first) * i / (ticks - 1), label = dates.format(new Date(stamp));
    if (shown.has(label)) continue; shown.add(label);
    shape('line', {x1: x(stamp), x2: x(stamp), y1: 190, y2: 195, class: 'chart-tick'});
    shape('text', {x: x(stamp), y: 218, 'text-anchor': i === 0 ? 'start' : i === ticks - 1 ? 'end' : 'middle'}).textContent = label;
  }
  points.forEach((r, i) => {
    const a = i ? (x(points[i - 1].time) + x(r.time)) / 2 : left, b = i + 1 < points.length ? (x(r.time) + x(points[i + 1].time)) / 2 : right;
    inspect(shape('rect', {x: a, y: 20, width: b - a, height: 182, fill: 'transparent', class: 'point-hit'}), `daily:${r.day}`,
      `${localTime(r.at)}\nLv. ${r.level} · ${(r.bp / 100).toFixed(2)}%\n${expText(r.exp, true)} EXP${r.gain ? `\n${expText(r.gain, true)} EXP gained that day` : ''}`);
    shape('line', {x1: x(r.time), x2: x(r.time), y1: 20, y2: 202, class: 'point-guide', 'aria-hidden': 'true'});
  });
}

// Overlay bars (drawHourChart): the General card's bare mini chart, or the labelled "Last hour" chart.
export function drawHourChart(svg, intervals, {anchor, seconds, range, labelled}) {
  svg.replaceChildren();
  const chart = bucketHistory(intervals, anchor, seconds, range);
  if (!chart) return null;
  const shape = drawer(svg);
  const max = Math.max(1, ...chart.bins.map((b) => b.value ?? 0));
  const width = labelled ? svg.clientWidth || 462 : 462, height = labelled ? svg.clientHeight || 90 : 76;
  const left = labelled ? 28 : 0, top = labelled ? 11 : 2, bottom = height - 2, scale = 10 ** Math.floor(Math.log10(max));
  const ceiling = labelled ? Math.ceil(max / scale) * scale : max;
  if (labelled) svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  const step = (width - left) / chart.bins.length, gap = Math.min(6, step / 4), y = (v) => bottom - Math.max(0, v) / ceiling * (bottom - top);
  if (labelled) for (const v of [ceiling, ceiling / 2]) {
    shape('line', {x1: left, x2: width, y1: y(v), y2: y(v), class: 'grid'});
    shape('text', {x: left - 5, y: y(v) + 3, 'text-anchor': 'end', class: 'axis'}).textContent = expText(v);
  }
  chart.bins.forEach((b, i) => {
    const tall = b.value == null ? 2 : Math.max(2, bottom - y(b.value));
    shape('rect', {x: left + i * step + gap / 2, y: bottom - tall, width: step - gap, height: tall, rx: b.value == null ? 1 : 3, class: b.value == null ? 'none' : 'bar'});
  });
  if (labelled) {
    const peak = chart.bins.reduce((best, b, i) => b.value != null && b.value > (chart.bins[best]?.value ?? -Infinity) ? i : best, -1);
    if (peak >= 0 && chart.bins[peak].value > 0) shape('text', {x: left + (peak + .5) * step, y: y(chart.bins[peak].value) - 3, 'text-anchor': 'middle', class: 'peak'}).textContent = expText(chart.bins[peak].value);
  }
  const seen = chart.bins.filter((b) => b.value != null);
  return seen.length ? seen.reduce((sum, b) => sum + b.value, 0) : null;
}
