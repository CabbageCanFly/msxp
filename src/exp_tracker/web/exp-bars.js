// Shared EXP scales for the live profiles, personal tracker, and overlays.
(() => {
  function axis(min, max, divisions) {
    const span = max - min || 1;
    // Keep the plot tight while choosing round grid values independently.
    const top = min + span * 1.06;
    const target = span / divisions * .8, magnitude = 10 ** Math.floor(Math.log10(target));
    const step = magnitude * [1, 2, 2.5, 5, 10].find((n) => n * magnitude >= target);
    const ticks = [];
    for (let i = Math.ceil(min / step); i <= Math.floor(top / step); i++) ticks.push(i * step);
    return {top, ticks};
  }

  function overlay(svg, bins, labelled, format) {
    const peak = bins.reduce((best, b, i) => (b.value ?? 0) > (bins[best]?.value ?? 0) ? i : best, -1);
    const max = bins[peak]?.value ?? 0;
    const width = labelled ? svg.clientWidth || 462 : 462, height = labelled ? svg.clientHeight || 90 : 76;
    const left = labelled ? 28 : 0, top = labelled ? 15 : 2, bottom = height - 2;
    const scale = labelled ? axis(0, max, 2) : {top: Math.max(1, max)};
    const step = (width - left) / bins.length, gap = Math.min(6, step / 4);
    const y = (value) => bottom - Math.max(0, value) / scale.top * (bottom - top);
    const shape = (tag, attrs) => {
      const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      svg.append(node);
      return node;
    };
    if (labelled) {
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      for (const value of scale.ticks.slice(1).reverse()) {
        shape('line', {x1: left, x2: width, y1: y(value), y2: y(value), class: 'grid'});
        shape('text', {x: left - 5, y: y(value) + 3, 'text-anchor': 'end', class: 'axis'}).textContent = format(value);
      }
    }
    bins.forEach((b, i) => {
      const tall = b.value == null ? 2 : Math.max(2, bottom - y(b.value));
      shape('rect', {x: left + i * step + gap / 2, y: bottom - tall, width: step - gap, height: tall,
        rx: b.value == null ? 1 : 3, class: b.value == null ? 'none' : 'bar'});
    });
    if (labelled && peak >= 0) {
      const value = format(max), halfWidth = value.length * 3 + 2;
      // Keep end-bucket labels inside the source frame.
      const x = Math.max(halfWidth, Math.min(width - halfWidth, left + (peak + .5) * step));
      shape('text', {x, y: y(max) - 3, 'text-anchor': 'middle', class: 'peak'}).textContent = value;
    }
  }

  globalThis.ExpBars = {axis, overlay};
})();
