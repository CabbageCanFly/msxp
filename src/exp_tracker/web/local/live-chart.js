// The Live rate chart: EXP or mesos per hour, one point per second, scrolling with the clock.

/**
 * Per-hour rate at each second from `from` to `to`: what was gained in the trailing `window` (ms) over
 * that window, or over the time since `since` while that is shorter, so an estimate shows early and
 * settles as the window fills. Quiet time counts as nothing gained, so the line slopes down until gains
 * resume. Nothing is drawn until `minEvents` have come in since `since`; the early span is at least a
 * minute, so the first few gains do not extrapolate to a spike. `events`: {at, amount}, any order.
 */
export function rateSeries(events, {from, to, window, since, minEvents = 3, step = 1000}) {
  const list = events.filter((e) => e.at >= since).sort((a, b) => a.at - b.at);
  if (list.length < minEvents) return [];
  const out = [];
  let lo = 0, hi = 0, sum = 0;
  for (let t = Math.ceil(Math.max(from, list[minEvents - 1].at) / step) * step; t <= to; t += step) {
    while (hi < list.length && list[hi].at <= t) sum += list[hi++].amount;
    while (lo < hi && list[lo].at <= t - window) sum -= list[lo++].amount;
    if (lo === hi) sum = 0;  // Nothing in the window: exactly 0, not a float remainder.
    out.push({at: t, perHour: sum / Math.max(60e3, Math.min(window, t - since)) * 3600e3});
  }
  return out;
}

// Eases each step of the rate into a curve (an exponential moving average over `seconds`).
export function smooth(series, seconds = 6) {
  const k = 1 - Math.exp(-1 / seconds);
  let value = series[0]?.perHour ?? 0;
  return series.map((p) => ({...p, perHour: (value += (p.perHour - value) * k)}));
}

const short = new Intl.NumberFormat('en-US', {notation: 'compact', maximumFractionDigits: 1});
const clock = (at) => new Date(at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});

/**
 * Draws `source()` ({series, window, unit}) on a canvas about 30 times a second while it is on screen
 * and the tab is visible; hovering shows the nearest second's value. `axes: false` draws the line alone
 * (the pop-out overlay).
 */
export function liveChart(canvas, source, {axes = true} = {}) {
  let hover = null, frame = 0, last = 0, visible = true, top = 0;
  const loop = (time) => {
    frame = 0;
    if (!visible || document.hidden) return;
    if (time - last >= 33) { last = time; draw(); }
    frame = requestAnimationFrame(loop);
  };
  const wake = () => { if (!frame && visible && !document.hidden) frame = requestAnimationFrame(loop); };
  new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; wake(); }).observe(canvas);
  document.addEventListener('visibilitychange', wake);
  canvas.addEventListener('pointermove', (event) => { hover = event.offsetX; });
  canvas.addEventListener('pointerleave', () => { hover = null; });

  function draw() {
    const {series, window, unit, empty} = source(), now = Date.now(), ratio = devicePixelRatio || 1;
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    // Height too: the overlay's canvas fills a flexible space, and a stale height leaves old frames below.
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
    const c = canvas.getContext('2d'), style = getComputedStyle(canvas), css = (name) => style.getPropertyValue(name).trim();
    c.setTransform(ratio, 0, 0, ratio, 0, 0); c.clearRect(0, 0, width, height);
    const left = axes ? 46 : 2, right = width - (axes ? 12 : 2), bottom = height - (axes ? 24 : 4), upper = axes ? 10 : 6;
    const x = (at) => left + (at - (now - window)) / window * (right - left);
    const shown = series.filter((p) => p.at >= now - window - 2000);
    // The scale eases toward the visible peak instead of jumping.
    const target = Math.max(1, ...shown.map((p) => p.perHour)) * 1.2;
    top = top ? top + (target - top) * .08 : target;
    const y = (value) => bottom - value / top * (bottom - upper);
    c.font = `600 11px ${style.fontFamily}`; c.fillStyle = css('--muted'); c.strokeStyle = css('--grid'); c.lineWidth = 1;
    if (axes) {
    // Gridlines on round steps (1, 2 or 5 times a power of ten), about three of them.
    const power = 10 ** Math.floor(Math.log10(top / 3)), step = [1, 2, 5, 10].map((m) => m * power).find((s) => top / s <= 3.5);
    for (let v = 0; v <= top; v += step) {
      const py = Math.round(y(v)) + .5;
      c.beginPath(); c.moveTo(left, py); c.lineTo(right, py); c.stroke();
      c.textAlign = 'right'; c.fillText(short.format(v), left - 8, py + 4);
    }
    c.textAlign = 'center';
    for (const f of [0, .5]) c.fillText(clock(now - window * (1 - f)), left + f * (right - left), height - 6);
    c.textAlign = 'right'; c.fillText('now', right, height - 6);
    }
    if (!shown.length) {
      c.textAlign = 'center'; c.fillText(empty ?? 'Waiting for data…', (left + right) / 2, (upper + bottom) / 2);
      return;
    }
    const color = css('--stroke');
    // Through each second's point, then flat to "now"; a soft fill below.
    c.save(); c.beginPath(); c.rect(left, 0, right - left, height); c.clip();
    const points = [...shown.map((p) => [x(p.at), y(p.perHour)]), [x(now), y(shown.at(-1).perHour)]];
    const line = new Path2D();
    line.moveTo(...points[0]);
    for (let i = 1; i < points.length; i++) {
      const [px, py] = points[i - 1], [qx, qy] = points[i];
      line.quadraticCurveTo(px, py, (px + qx) / 2, (py + qy) / 2);
    }
    line.lineTo(...points.at(-1));
    const area = new Path2D(line);
    area.lineTo(points.at(-1)[0], bottom); area.lineTo(points[0][0], bottom); area.closePath();
    c.globalAlpha = .12; c.fillStyle = color; c.fill(area); c.globalAlpha = 1;
    c.strokeStyle = color; c.lineWidth = 2.5; c.lineJoin = 'round'; c.stroke(line);
    // "Live": a faint light sweeps along the line every 3.2 s, toward the tip.
    const pulse = performance.now(), sweep = left - 80 + (pulse % 3200) / 3200 * (right - left + 160);
    const glow = c.createLinearGradient(sweep - 70, 0, sweep + 70, 0);
    glow.addColorStop(0, '#fff0'); glow.addColorStop(.5, '#ffffff59'); glow.addColorStop(1, '#fff0');
    c.strokeStyle = glow; c.lineWidth = 2.5; c.stroke(line);
    c.restore();
    // The leading edge: a dot at "now" with a slow, soft pulse around it.
    const [tx, ty] = points.at(-1), beat = (Math.sin(pulse / 260) + 1) / 2;
    c.fillStyle = color;
    c.globalAlpha = .18 + .12 * beat; c.beginPath(); c.arc(tx - 3, ty, 6 + 3 * beat, 0, Math.PI * 2); c.fill();
    c.globalAlpha = 1; c.beginPath(); c.arc(tx - 3, ty, 3.5, 0, Math.PI * 2); c.fill();
    c.fillStyle = '#fff'; c.beginPath(); c.arc(tx - 3, ty, 1.4, 0, Math.PI * 2); c.fill();
    if (hover != null && hover >= left && hover <= right) {
      const at = now - window + (hover - left) / (right - left) * window;
      const p = shown.reduce((best, q) => (Math.abs(q.at - at) < Math.abs(best.at - at) ? q : best));
      const px = x(p.at), py = y(p.perHour), label = `${new Date(p.at).toLocaleTimeString()} · ${short.format(p.perHour)} ${unit}`;
      c.strokeStyle = css('--grid'); c.beginPath(); c.moveTo(px, upper); c.lineTo(px, bottom); c.stroke();
      c.fillStyle = color; c.beginPath(); c.arc(px, py, 4, 0, Math.PI * 2); c.fill();
      c.font = `700 12px ${style.fontFamily}`;
      const w = c.measureText(label).width + 16, bx = Math.min(Math.max(px - w / 2, left), right - w);
      c.fillStyle = css('--tip'); c.fillRect(bx, upper, w, 22);
      c.fillStyle = css('--text'); c.textAlign = 'left'; c.fillText(label, bx + 8, upper + 15);
    }
  }
  wake();
  return {wake};
}
