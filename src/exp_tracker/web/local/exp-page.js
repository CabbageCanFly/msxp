// The /exp-table page (exp-table.html): the town scenery and the level planner beside the table, from the same
// modules /local uses. Scenery "off" is remembered like the Twitch pages (localStorage 'scenery'), so it carries over.
import {setScenery} from './scenery.js';
import {openPlanner} from './level-plan.js';

const $ = (id) => document.getElementById(id);
let on = (() => { try { return localStorage.getItem('scenery') !== 'off'; } catch { return true; } })();
function show() {
  setScenery(on);
  $('scenery-toggle').setAttribute('aria-pressed', String(on));
  $('scenery-toggle').title = on ? 'Hide the town background and mobs' : 'Show the town background and mobs';
}
$('scenery-toggle').addEventListener('click', () => {
  on = !on;
  try { if (on) localStorage.removeItem('scenery'); else localStorage.setItem('scenery', 'off'); } catch {}  // Storage can be unavailable.
  show();
});
show();

const table = await fetch('/static/local/community-exp.json').then((r) => r.ok ? r.json() : null).catch(() => null);
if (table) openPlanner($('planner-body'), table, {});
else $('planner-body').textContent = 'The planner could not load the EXP table. The table on this page is complete.';
