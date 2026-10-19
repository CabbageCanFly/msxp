// Local input conversion only. Correction validation stays in the Python backend.
const pad = n => String(n).padStart(2, '0');
export const timezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
export function localFields(stamp) {
  const d = new Date(stamp);
  return {date: `${String(d.getFullYear()).padStart(4, '0')}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`};
}
export function offset(stamp) {
  const minutes = -new Date(stamp).getTimezoneOffset();
  return `UTC${minutes < 0 ? '-' : '+'}${pad(Math.floor(Math.abs(minutes)/60))}:${pad(Math.abs(minutes)%60)}`;
}
export function when(stamp) {
  return new Intl.DateTimeFormat(undefined, {dateStyle: 'long', timeStyle: 'long'}).format(new Date(stamp));
}
export function localCandidates(date, time) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}(?::\d{2})?$/.test(time))
    throw Error('Choose a date and time, including seconds.');
  time = time.length === 5 ? time+':00' : time;
  const utc = Date.parse(date+'T'+time+'Z');
  if (!Number.isFinite(utc) || new Date(utc).toISOString().slice(0,19) !== date+'T'+time || date.startsWith('0000'))
    throw Error('Choose a valid date and time.');
  // Check offsets on both sides of a clock change, including half-hour changes and skipped days.
  const offsets = new Set();
  for (let minutes = -2160; minutes <= 2160; minutes += 30)
    offsets.add(new Date(utc+minutes*60000).getTimezoneOffset());
  return [...offsets].map(o => new Date(utc+o*60000).toISOString()).filter(stamp => {
    const parts = localFields(stamp); return parts.date === date && parts.time === time;
  }).sort();
}
export function localTimestamp(date, time, choice = '') {
  const candidates = localCandidates(date, time);
  if (!candidates.length) throw Error('This local time does not exist because the clocks change. Choose another time or paste an ISO timestamp in Advanced.');
  if (candidates.length > 1 && !candidates.includes(choice))
    throw Error('This local time occurs twice because the clocks change. Choose which time you mean.');
  return candidates.length === 1 ? candidates[0] : choice;
}
