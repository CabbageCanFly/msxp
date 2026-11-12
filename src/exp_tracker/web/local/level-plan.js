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
// The day a goal is reached when `daily` hours are played each day from today: "Today", "Tomorrow", a weekday
// within the week, else the date. Playing all day (24) gives the clock time.
const date = (at, now) => at.toLocaleDateString(undefined, {month: 'short', day: 'numeric', ...(at.getFullYear() !== new Date(now).getFullYear() && {year: 'numeric'})});
export const when = (hours, daily, now) => {
  if (daily >= 24) {
    const at = new Date(now + hours * 36e5), time = at.toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'});
    if (at.toDateString() === new Date(now).toDateString()) return time;
    return (at - now) / 864e5 < 6 ? `${at.toLocaleDateString(undefined, {weekday: 'short'})} ${time}` : date(at, now);
  }
  const days = Math.floor(hours / daily - 1e-9), at = new Date(now + days * 864e5);
  return days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : days < 6 ? at.toLocaleDateString(undefined, {weekday: 'short'}) : date(at, now);
};
// Whole EXP: commas group thousands, a "." starts decimals (rounded).
export const whole = (text) => Math.round(Number(text.replace(/[,\s]/g, ''))) || 0;
const node = (tag, props = {}, ...children) => { const n = Object.assign(document.createElement(tag), props); n.append(...children); return n; };

let goal = null, by = '', daily = null;  // Kept while the page is open.

/**
 * Fills `root` (the planner popover's body) for `state` {level, exp, bp, rate, pph, tracked}: EXP may be given
 * as bp (hundredths of a percent) and the rate as % per hour, as the live page has them; `tracked` (seconds
 * tracked in the last 24 hours) suggests the hours played a day, else 4.
 */
export function openPlanner(root, table, state) {
  const level = state.level, now = Date.now();
  root.replaceChildren();
  if (!level || !need(table, level)) { root.append(node('p', {className: 'planner-empty', textContent: level ? 'No EXP table for this level.' : 'Waiting for a reading.'})); return; }
  const exp = state.exp ?? (state.bp != null ? state.bp / 10000 * need(table, level) : 0);
  const current = state.rate ?? (state.pph != null ? state.pph / 100 * need(table, level) : null);
  let top = level + 1;
  while (need(table, top)) top++;  // The level after the table's last requirement (Lv. 100).
  if (!goal || goal <= level || goal > top) goal = Math.min(top, Math.ceil((level + 1) / 10) * 10);
  daily ??= state.tracked >= 1800 ? Math.min(24, Math.round(state.tracked / 1800) / 2) : 4;

  const rate = node('input', {type: 'text', inputMode: 'numeric', autocomplete: 'off', value: current ? numbers.format(Math.round(current)) : '', placeholder: '50,000'});
  const hours = node('input', {type: 'number', inputMode: 'decimal', min: .5, max: 24, step: .5, value: daily});
  const target = node('input', {type: 'number', inputMode: 'numeric', min: level + 1, max: top, step: 1, value: goal});
  const capped = node('span', {className: 'planner-cap', textContent: '24 max', hidden: true});
  const topped = node('span', {className: 'planner-cap', textContent: `${top} max`, hidden: true});
  const deadline = node('input', {type: 'datetime-local', value: by});
  const steps = node('ol', {className: 'planner-steps'}), answer = node('p', {className: 'planner-answer'});
  root.append(
    node('p', {className: 'planner-now', textContent: `Lv. ${level} · ${((exp / need(table, level)) * 100).toFixed(2)}%`}),
    node('div', {className: 'planner-inputs'},
      node('label', {}, node('span', {textContent: 'EXP / hour'}), rate),
      node('label', {}, node('span', {}, 'Hours / day', capped), hours),
      node('label', {}, node('span', {}, 'Goal Lvl', topped), target)),
    steps,
    node('label', {className: 'planner-by'}, node('span', {textContent: 'By'}), deadline),
    answer,
  );

  let hideCap = null;
  // A value past the cap is set back to it, with a short note beside the label.
  const cap = (input, note, max) => {
    if (Number(input.value) <= max) return;
    input.value = max; note.hidden = false;
    clearTimeout(hideCap); hideCap = setTimeout(() => { note.hidden = true; }, 2000);
  };
  const update = () => {
    by = deadline.value;
    // At least six rows: levels past the goal fill the list, faded, so the popup keeps its size.
    const perHour = whole(rate.value), path = climb(table, level, exp, Math.min(top, Math.max(goal, level + 6)));
    const total = path.find((s) => s.level === goal)?.exp ?? path.at(-1)?.exp ?? 0;
    steps.replaceChildren(...path.map((s) => node('li', {className: s.level > goal ? 'beyond' : s.level === goal ? 'goal' : ''},
      node('b', {textContent: `Lv. ${s.level}`}),
      node('span', {textContent: perHour ? span(s.exp / perHour) : '—'}),
      node('time', {textContent: perHour && daily ? when(s.exp / perHour, daily, now) : ''}),
    )));
    // Hours left before the deadline, of which `daily` a day are played.
    const left = (Date.parse(deadline.value) - Date.now()) / 36e5, played = left / 24 * (daily || 24);
    // The answer keeps its space while empty, so the popup never changes size.
    answer.replaceChildren();
    if (!deadline.value) return;
    if (!(left > 0)) { answer.textContent = 'Pick a time ahead.'; return; }
    answer.replaceChildren(node('strong', {textContent: numbers.format(Math.ceil(total / played))}), ` EXP / hour at ${daily || 24}h a day`);
    if (perHour) {
      const needed = total / perHour / (left / 24);
      if (needed <= 24) answer.append(node('small', {textContent: ` · or ${span(needed)} a day at ${numbers.format(perHour)}`}));
    }
  };
  rate.addEventListener('input', update);
  hours.addEventListener('input', () => {
    cap(hours, capped, 24);
    daily = Number(hours.value) > 0 ? Number(hours.value) : null;
    update();
  });
  // Typed or picked; a decimal rounds and the level stays within the table.
  target.addEventListener('input', () => { cap(target, topped, top); const value = Math.round(Number(target.value)); if (value > level) { goal = value; update(); } });
  target.addEventListener('change', () => { goal = Math.min(top, Math.max(level + 1, Math.round(Number(target.value)) || goal)); target.value = goal; update(); });
  deadline.addEventListener('input', update);
  update();
}
