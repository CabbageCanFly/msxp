// While a popup (an auto popover: About, the planner, the EXP table…) is open, a click outside it only closes it;
// the browser's light dismiss closes it, and this keeps the same click from also reaching the page behind.
// Loaded by every page with popups (tracker, player and local pages).
const stack = [];  // Open popovers, newest last: nested ones (the planner's EXP table) open over their parent.
document.addEventListener('toggle', (event) => {
  if (!event.target.matches?.('[popover]')) return;
  const at = stack.indexOf(event.target);
  if (at >= 0) stack.splice(at, 1);
  if (event.newState === 'open') stack.push(event.target);
}, true);

let swallow = false;
// Decided on pointerdown, before light dismiss closes the popup. A popup's own buttons (popovertarget) still work.
document.addEventListener('pointerdown', (event) => {
  const top = stack.at(-1);
  swallow = !!top && !top.contains(event.target) && !event.target.closest?.('[popovertarget]');
}, true);
// No focus for a field behind the popup either.
document.addEventListener('mousedown', (event) => { if (swallow) event.preventDefault(); }, true);
document.addEventListener('click', (event) => {
  if (!swallow) return;
  swallow = false;
  event.preventDefault(); event.stopImmediatePropagation();
}, true);
