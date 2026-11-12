// Level planner behind the "Next level" card (local and live pages): the time to each level at an EXP / hour,
// and the EXP / hour a goal by a set time needs. Arithmetic on the community EXP table (to_next per level).

const need = (table, level) => { const value = Number(table?.to_next?.[String(level)]); return value > 0 ? value : null; };

// EXP from `exp` into `level` to the start of each later level up to `goal`, added up: [{level, exp}].
// Stops where the table has no requirement.
export function climb(table, level, exp, goal) {
  const steps = [];
  let total = 0;
  for (let l = level; l < goal; l++) {
    const n = need(table, l);
    if (n == null) break;
    total += l === level ? Math.max(0, n - exp) : n;
    steps.push({level: l + 1, exp: total});
  }
  return steps;
}

const numbers = new Intl.NumberFormat('en-US');
const span = (hours) => {
  const minutes = Math.max(1, Math.round(hours * 60));
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  return `${Math.floor(minutes / 1440)}d ${Math.floor(minutes % 1440 / 60)}h`;
};
const when = (at, now) => {
  const date = new Date(at), days = (at - now) / 864e5;
  const time = date.toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'});
  if (date.toDateString() === new Date(now).toDateString()) return time;
  return days < 6 ? `${date.toLocaleDateString(undefined, {weekday: 'short'})} ${time}` : date.toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
};
const node = (tag, props = {}, ...children) => { const n = Object.assign(document.createElement(tag), props); n.append(...children); return n; };

let goal = null, by = '';  // Kept while the page is open.

/**
 * Fills `root` (the planner popover's body) for `state` {level, exp, bp, rate, pph}: EXP may be given as
 * bp (hundredths of a percent) and the rate as % per hour, as the live page has them.
 */
export function openPlanner(root, table, state) {
  const level = state.level, now = Date.now();
  root.replaceChildren();
  if (!level || !need(table, level)) { root.append(node('p', {className: 'planner-empty', textContent: level ? 'No EXP table for this level.' : 'Waiting for a reading.'})); return; }
  const exp = state.exp ?? (state.bp != null ? state.bp / 10000 * need(table, level) : 0);
  const current = state.rate ?? (state.pph != null ? state.pph / 100 * need(table, level) : null);
  let top = level + 1;
  while (need(table, top) && top < level + 30) top++;
  if (!goal || goal <= level || goal > top) goal = Math.min(top, Math.ceil((level + 1) / 10) * 10);

  const rate = node('input', {type: 'text', inputMode: 'numeric', autocomplete: 'off', value: current ? numbers.format(Math.round(current)) : '', placeholder: '50,000'});
  const target = node('select');
  for (let l = level + 1; l <= top; l++) target.append(node('option', {value: l, textContent: `Lv. ${l}`, selected: l === goal}));
  const deadline = node('input', {type: 'datetime-local', value: by});
  const steps = node('ol', {className: 'planner-steps'}), answer = node('p', {className: 'planner-answer'});
  root.append(
    node('p', {className: 'planner-now', textContent: `Lv. ${level} · ${((exp / need(table, level)) * 100).toFixed(2)}%`}),
    node('div', {className: 'planner-inputs'}, node('label', {}, node('span', {textContent: 'EXP / hour'}), rate), node('label', {}, node('span', {textContent: 'Goal'}), target)),
    steps,
    node('label', {className: 'planner-by'}, node('span', {textContent: 'By'}), deadline),
    answer,
  );

  const update = () => {
    goal = Number(target.value); by = deadline.value;
    const perHour = Number(rate.value.replace(/\D/g, '')) || 0, path = climb(table, level, exp, goal);
    steps.replaceChildren(...path.map((s) => node('li', {},
      node('b', {textContent: `Lv. ${s.level}`}),
      node('span', {textContent: perHour ? span(s.exp / perHour) : '—'}),
      node('time', {textContent: perHour ? when(now + s.exp / perHour * 36e5, now) : ''}),
    )));
    const hours = (Date.parse(deadline.value) - Date.now()) / 36e5, total = path.at(-1)?.exp ?? 0;
    answer.hidden = !deadline.value;
    if (!deadline.value) return;
    if (!(hours > 0)) { answer.textContent = 'Pick a time ahead.'; return; }
    answer.replaceChildren(node('strong', {textContent: numbers.format(Math.ceil(total / hours))}), ' EXP / hour needed');
    // Hours a day at the rate above, when the goal is more than a day away.
    if (perHour && hours > 24) answer.append(node('small', {textContent: ` · or ${span(total / perHour / Math.ceil(hours / 24))} a day at ${numbers.format(perHour)}`}));
  };
  rate.addEventListener('input', update);
  target.addEventListener('change', update);
  deadline.addEventListener('input', update);
  update();
}
