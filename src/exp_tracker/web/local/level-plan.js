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
// Playing `daily` hours a day from now: the moment `hours` of play are done (the last day's share is played
// from the same time of day), and the hours of play before a moment `ms` away.
export const finish = (hours, daily, now) => {
  if (daily >= 24) return now + hours * 36e5;
  const days = Math.floor(hours / daily - 1e-9);
  return now + days * 864e5 + (hours - days * daily) * 36e5;
};
export const playable = (ms, daily) => { const days = Math.floor(ms / 864e5); return days * daily + Math.min((ms - days * 864e5) / 36e5, daily); };
// When a level is reached: the clock time when playing all day, else "Today", "Tomorrow", a weekday within the
// week or the date (with the year when it is not this year's).
const date = (at, now) => at.toLocaleDateString(undefined, {month: 'short', day: 'numeric', ...(at.getFullYear() !== new Date(now).getFullYear() && {year: 'numeric'})});
export const when = (hours, daily, now) => {
  if (daily >= 24) {
    const at = new Date(now + hours * 36e5), time = at.toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'});
    if (at.toDateString() === new Date(now).toDateString()) return time;
    return (at - now) / 864e5 < 6 ? `${at.toLocaleDateString(undefined, {weekday: 'short'})} ${time}` : date(at, now);
  }
  // The calendar day of the moment `finish` gives, so the list and the "By" date agree.
  const at = new Date(finish(hours, daily, now)), days = Math.round((new Date(at).setHours(0, 0, 0, 0) - new Date(now).setHours(0, 0, 0, 0)) / 864e5);
  return days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : days < 6 ? at.toLocaleDateString(undefined, {weekday: 'short'}) : date(at, now);
};
// Whole EXP: commas group thousands, a "." starts decimals (rounded).
export const whole = (text) => Math.round(Number(text.replace(/[,\s]/g, ''))) || 0;
// A moment as a datetime-local value (local time, to the minute).
const local = (at) => new Date(at - new Date(at).getTimezoneOffset() * 6e4).toISOString().slice(0, 16);
const node = (tag, props = {}, ...children) => { const n = Object.assign(document.createElement(tag), props); n.append(...children); return n; };

let goal = null, daily = null;  // Kept while the page is open.
const opened = new Set();  // Levels whose EXP is shown (a tap on the row).

/**
 * Fills `root` (the planner popover's body) for `state` {level, exp, bp, rate, pph, tracked}: EXP may be given
 * as bp (hundredths of a percent) and the rate as % per hour, as the live page has them; `tracked` (seconds
 * tracked in the last 24 hours) suggests the hours played a day, else 4. EXP / hour, hours a day and the goal
 * set the "By" date; changing the date sets the EXP / hour that date needs.
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
  const deadline = node('input', {type: 'datetime-local', min: local(now)});
  const steps = node('ol', {className: 'planner-steps'});
  const box = node('div', {className: 'planner-table'});
  // Phones show no scrollbar: a shadow under the column names once scrolled, and above the goal's row while
  // rows hide behind it, says there is more.
  const edges = () => {
    const goalRow = steps.querySelector('li.goal'), before = goalRow?.previousElementSibling;
    box.dataset.up = String(box.scrollTop > 2);
    box.dataset.down = String(Boolean(before && before.getBoundingClientRect().bottom > goalRow.getBoundingClientRect().top + 1));
  };
  box.addEventListener('scroll', edges, {passive: true});
  const head = node('div', {className: 'planner-head'}, node('span', {textContent: 'Lvl'}), node('span', {textContent: 'Play time'}), node('span', {textContent: 'Reached'}));
  head.setAttribute('aria-hidden', 'true');
  box.append(head, steps);
  root.append(
    node('p', {className: 'planner-now', textContent: `Lv. ${level} · ${((exp / need(table, level)) * 100).toFixed(2)}%`}),
    node('div', {className: 'planner-inputs'},
      node('label', {}, node('span', {textContent: 'EXP / hour'}), rate),
      node('label', {}, node('span', {}, 'Hours / day', capped), hours),
      node('label', {}, node('span', {}, 'Goal Lvl', topped), target)),
    // The column names stay at the top and the goal's row at the bottom while the list scrolls.
    box,
    node('label', {className: 'planner-by'}, node('span', {textContent: 'By'}), deadline),
  );

  let hideCap = null;
  // A value past the cap is set back to it, with a short note beside the label.
  const cap = (input, note, max) => {
    if (Number(input.value) <= max) return;
    input.value = max; note.hidden = false;
    clearTimeout(hideCap); hideCap = setTimeout(() => { note.hidden = true; }, 2000);
  };
  // At least six rows: levels past the goal fill the list, faded, so the popup keeps its size.
  const path = () => climb(table, level, exp, Math.min(top, Math.max(goal, level + 6)));
  const toGoal = () => path().find((s) => s.level === goal)?.exp ?? 0;
  const draw = () => {
    const perHour = whole(rate.value);
    steps.replaceChildren(...path().map((s) => {
      const row = node('li', {className: `${s.level > goal ? 'beyond' : s.level === goal ? 'goal' : ''}${opened.has(s.level) ? ' open' : ''}`, tabIndex: 0},
        node('b', {textContent: `Lv. ${s.level}`}),
        node('span', {textContent: perHour ? span(s.exp / perHour) : '—'}),
        node('time', {textContent: perHour && daily ? when(s.exp / perHour, daily, now) : ''}),
        // The level's own EXP (Lv. N-1 to N) and the total from now.
        node('small', {className: 'planner-exp', textContent: `${numbers.format(need(table, s.level - 1))} EXP for this level · ${numbers.format(Math.ceil(s.exp))} from now`}));
      row.setAttribute('role', 'button');
      row.setAttribute('aria-expanded', String(opened.has(s.level)));
      // Redrawn on each toggle; a keyboard toggle keeps the focus on its row.
      const toggle = (keyboard) => { if (!opened.delete(s.level)) opened.add(s.level); draw(); if (keyboard) steps.querySelector(`[data-level="${s.level}"]`)?.focus(); };
      row.dataset.level = s.level;
      row.addEventListener('click', () => toggle(false));
      row.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(true); } });
      return row;
    }));
    requestAnimationFrame(edges);
  };
  // From the three fields: the date the goal is reached.
  const update = () => {
    const perHour = whole(rate.value);
    deadline.value = perHour && daily ? local(finish(toGoal() / perHour, daily, now)) : '';
    draw();
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
  // From the date: the EXP / hour that reaches the goal by then, at the hours a day above.
  deadline.addEventListener('input', () => {
    const played = playable(Date.parse(deadline.value) - now, daily || 24);
    if (!(played > 0)) return;
    rate.value = numbers.format(Math.ceil(toGoal() / played));
    draw();
  });
  update();
}
