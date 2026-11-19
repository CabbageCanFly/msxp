// Served only by the loopback demo. Seed a separate fictional character through the real local store.
import * as store from './store.js';

let demo = (await store.characters()).find((character) => character.expChartDemo);
if (!demo?.last || Date.now() - demo.last.at >= 3600e3) {
  const id = demo?.id ?? await store.saveCharacter({name: 'Chart demo', nameSource: 'user', job: 'Rogue', expChartDemo: true});
  const end = Math.floor(Date.now() / 60000) * 60000, start = end - 59 * 60000;
  const level = 61, {to_next: levels} = await (await fetch('/static/local/community-exp.json')).json();
  const session = await store.startSession(id, start);
  let exp = 500000;
  const readings = Array.from({length: 60}, (_, i) => {
    const gain = i === 0 ? null : ({20: 8300, 45: 10600, 47: 9600, 59: 7200}[i] ?? 200 + i % 7 * 145);
    exp += gain ?? 0;
    return {at: start + i * 60000, level, exp, bp: Math.floor(exp * 10000 / levels[level]),
      gain, kind: i === 0 ? 'baseline' : 'gain'};
  });
  await store.record(id, session, readings, {last: readings.at(-1), pending: null}, 'accepted');
  await store.endSession(session, end, 'stopped');
  demo = {id};
}
await store.setSetting('activeCharacterId', demo.id);
await import('./app.js');
