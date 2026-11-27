// EXP table popup, opened from About and the level planner on every page: the bundled requirements as a list.

const numbers = new Intl.NumberFormat('en-US');
const node = (tag, props = {}, ...children) => { const n = Object.assign(document.createElement(tag), props); n.append(...children); return n; };

// [{level, next, total}]: EXP to the next level (null after the last requirement) and the EXP from Lv. 1 to this level.
export function expRows(table) {
  const rows = [];
  let total = 0;
  for (let level = 1; ; level++) {
    const next = Number(table?.to_next?.[String(level)]) || null;
    rows.push({level, next, total});
    if (!next) return level > 1 ? rows : [];
    total += next;
  }
}

export function openExpTable(root, table) {
  const rows = expRows(table);
  if (!rows.length) { root.replaceChildren(node('p', {className: 'planner-empty', textContent: 'The EXP table could not be loaded.'})); return; }
  root.replaceChildren(
    node('p', {className: 'exp-table-source', textContent: 'From the game client\'s own formula, checked Nov 27, 2026.'}),
    node('div', {className: 'exp-table-list'},
      node('div', {className: 'exp-table-row exp-table-head'}, node('span', {textContent: 'Level'}), node('span', {textContent: 'EXP to next level'}), node('span', {textContent: 'Total from Lv. 1'})),
      ...rows.map(({level, next, total}) => node('div', {className: 'exp-table-row'},
        node('b', {textContent: level}), node('span', {textContent: next ? numbers.format(next) : '—'}), node('span', {textContent: numbers.format(total)})))));
}
