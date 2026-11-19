// Shared stat choices for the public Browser Source and local Window Capture overlays.
(() => {
  const metrics = {rate: 'EXP / hour', percent: '% / hour', gain: 'EXP earned', eta: 'Next level ETA', mesoRate: 'Mesos / hour', mesos: 'Mesos earned'};
  const counts = {card: 4, bar: 4, rates: 4, live: 5};
  const windows = (metric, local) => ['5', '10', '15', '30', '60', ...(['gain', 'mesos'].includes(metric) ? ['1440', ...(local && metric === 'gain' ? ['session'] : [])] : [])];
  const keys = (local) => Object.entries(counts).filter(([layout]) => local || layout !== 'live').flatMap(([layout, count]) => Array.from({length: count}, (_, i) => `${layout}${i + 1}`));
  function read(search, local = false) {
    const q = new URLSearchParams(search), result = {};
    for (const key of keys(local)) {
      const value = q.get(key), [metric, window] = (value ?? '').split(':');
      if (Object.hasOwn(metrics, metric) && (local || !metric.startsWith('meso')) && windows(metric, local).includes(window) && value === `${metric}:${window}`) result[key] = value;
    }
    return result;
  }
  function query(q, options, local = false) {
    for (const key of keys(local)) if (options[key]) q.set(key, options[key]);
  }
  const timeLabel = (window) => window === 'session' ? 'session' : window === '1440' ? '24 h' : `${window} min`;
  const label = (metric, window) => metric === 'eta' ? 'NEXT LEVEL' : metric === 'gain' ? (window === 'session' ? 'This session' : `Last ${timeLabel(window)}`) : `${{rate:'EXP/h', percent:'%/h', gain:'EXP', mesoRate:'Mesos/h', mesos:'Mesos'}[metric]} · ${timeLabel(window)}`;
  function statCells(doc, layout) {
    return layout === 'live' ? ['live-rate', 'live-eta', 'live-other', 'live-percent', 'live-exp'].map(id => doc.getElementById(id))
      : Array.from(doc.querySelectorAll(layout === 'rates' ? '.rate-stats strong' : '.general-stats strong'));
  }
  function previewHighlight(layout, index) {
    const doc = document.getElementById('overlay-preview')?.contentDocument;
    if (!doc) return;
    for (const area of doc.querySelectorAll('[data-stat-highlight]')) delete area.dataset.statHighlight;
    const area = index == null ? null : statCells(doc, layout)[index - 1]?.parentElement;
    if (area) area.dataset.statHighlight = 'true';
  }
  function editor(root, options, local, changed) {
    if (!root) return;
    const layout = options.layout;
    root.hidden = !counts[layout];
    if (root.hidden) { previewHighlight(null, null); return; }
    const selections = Array.from({length: counts[layout]}, (_, i) => options[`${layout}${i + 1}`]);
    const customized = selections.some(Boolean);
    const overlap = selections.includes('rate:60') && selections.includes('gain:60')
      ? '60m EXP/h and Last 60 min can show the same number when a full hour is tracked.' : '';
    if (root.dataset.layout === layout) {
      const reset = root.querySelector('.stat-reset'), note = root.querySelector('.stat-overlap');
      if (reset) reset.disabled = !customized;
      if (note && note.textContent !== overlap) note.textContent = overlap;
      return;
    }
    previewHighlight(null, null);
    root.dataset.layout = layout;
    const rows = document.createElement('div'); rows.className = 'stat-edit-rows';
    for (let i = 1; i <= counts[layout]; i++) {
      const key = `${layout}${i}`, row = document.createElement('div'); row.className = 'stat-edit-row';
      const name = document.createElement('label'), metric = document.createElement('select'), window = document.createElement('select');
      metric.id = `stat-${key}`; name.htmlFor = metric.id;
      name.textContent = layout === 'live' ? ['Main', 'Top right', 'Bottom left', 'Bottom middle', 'Bottom right'][i - 1] : `Stat ${i}`;
      metric.setAttribute('aria-label', `${name.textContent}: statistic`); window.setAttribute('aria-label', `${name.textContent}: time window`);
      for (const [value, text] of [['default', 'Default'], ...Object.entries(metrics).filter(([m]) => local || !m.startsWith('meso'))]) {
        const option = document.createElement('option'); option.value = value; option.textContent = text; metric.append(option);
      }
      const [chosen, period = '15'] = (options[key] ?? 'default').split(':'); metric.value = chosen;
      function periods(preferred) {
        row.dataset.metric = metric.value;
        const hourly = ['rate', 'percent', 'mesoRate'].includes(metric.value);
        const rateHint = 'Lookback window used to calculate the hourly rate.';
        window.setAttribute('aria-description', hourly ? rateHint : metric.value === 'eta' ? 'EXP/hour lookback used to calculate the next-level ETA.' : '');
        window.replaceChildren(); window.disabled = metric.value === 'default';
        window.title = window.disabled ? 'Uses the layout default time window.' : hourly ? rateHint : '';
        if (window.disabled) {
          const option = document.createElement('option'); option.value = 'auto'; option.textContent = 'Auto'; window.append(option); return;
        }
        for (const value of windows(metric.value, local)) {
          const option = document.createElement('option'); option.value = value; option.textContent = value === 'session' ? 'Session' : value === '1440' ? '24h' : metric.value === 'eta' ? `${value}m pace` : `${value}m`; window.append(option);
        }
        window.value = windows(metric.value, local).includes(preferred) ? preferred : metric.value === 'eta' ? '5' : '15';
      }
      periods(period);
      function save() { if (metric.value === 'default') delete options[key]; else options[key] = `${metric.value}:${window.value}`; changed(); }
      metric.addEventListener('change', () => { periods(metric.value === 'eta' ? '5' : window.value); save(); }); window.addEventListener('change', save);
      let hovered = false, focused = false;
      const highlight = () => previewHighlight(layout, hovered || focused ? i : null);
      row.addEventListener('mouseenter', () => { hovered = true; highlight(); });
      row.addEventListener('mouseleave', () => { hovered = false; highlight(); });
      row.addEventListener('focusin', () => { focused = true; highlight(); });
      row.addEventListener('focusout', event => { focused = row.contains(event.relatedTarget); highlight(); });
      row.append(name, metric, window); rows.append(row);
    }
    const note = document.createElement('p'); note.className = 'stat-overlap';
    note.setAttribute('role', 'status'); note.textContent = overlap; rows.append(note);
    const title = document.createElement('span'); title.textContent = 'Stats';
    const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'stat-reset'; reset.textContent = 'Reset';
    reset.setAttribute('aria-label', 'Reset stats to default for this layout'); reset.disabled = !customized;
    reset.addEventListener('click', () => {
      for (let i = 1; i <= counts[layout]; i++) delete options[`${layout}${i}`];
      delete root.dataset.layout; changed();
    });
    title.append(reset); root.replaceChildren(title, rows);
  }
  const originals = new WeakMap();
  function render(options, resolve) {
    const layout = options.layout;
    const cells = statCells(document, layout);
    cells.forEach((cell, i) => {
      if (!cell) return;
      const caption = cell.parentElement.querySelector('span'), choice = options[`${layout}${i + 1}`];
      if (!caption) return;
      if (!originals.has(caption)) originals.set(caption, caption.textContent);
      if (!choice) { if (caption.dataset.customStat) { caption.textContent = originals.get(caption); delete caption.dataset.customStat; } return; }
      const [metric, window] = choice.split(':');
      caption.textContent = label(metric, window); caption.dataset.customStat = 'true'; caption.title = caption.textContent;
      const result = resolve(metric, window);
      cell.textContent = result ?? '—'; cell.title = `${caption.textContent}: ${cell.textContent}`;
      cell.dataset.size = cell.textContent.length > 8 ? 'long' : 'normal'; cell.dataset.paused = 'false';
    });
  }
  globalThis.OverlayStats = {read, query, editor, render, label};
})();
