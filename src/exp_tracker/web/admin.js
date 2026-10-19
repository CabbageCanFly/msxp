import {timezone, localFields, localCandidates, localTimestamp, when, offset} from './admin-time.js';

const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="admin-token"]').content;
let scope = null, view = null, previewId = null, busy = false, loading = false;
let edit = {action: 'set', session: 'auto'}, exactTimestamp = null;
const inputZone = timezone();
const option = (value, text) => new Option(text, String(value));
const bpText = bp => bp == null ? '' : String(bp).padStart(3, '0').replace(/(..)$/, '.$1');

function status(message, error = false) {
  $('status').textContent = message; $('status').classList.toggle('error', error);
}
async function api(path, data) {
  const response = await fetch(path, {headers: {'X-Admin-Token': token, ...(data ? {'Content-Type': 'application/json'} : {})},
    ...(data ? {method: 'POST', body: JSON.stringify(data)} : {})});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || `Request failed (${response.status}). Try refreshing.`);
  return result;
}
function block() {
  $('app').setAttribute('aria-busy', String(busy || loading));
  for (const id of ['pickers', 'editor', 'rename-form', 'readings', 'history']) $(id).inert = busy || loading;
  for (const id of ['session', 'refresh', 'new-correction']) $(id).disabled = busy || loading;
  $('save').disabled = busy || loading || !previewId;
  $('preview-button').disabled = !scope?.character;
  $('rename').disabled = !scope?.character;
}
function invalidate() {
  previewId = null; $('preview').hidden = true; $('save').disabled = true;
  $('editor').hidden = !$('rename-form').hidden;
}
function text(node, value, tag = 'p', className = '') {
  const element = document.createElement(tag); element.textContent = value;
  element.className = className; node.append(element); return element;
}
function audit(node, value) {
  const details = document.createElement('details'); text(details, 'Advanced details', 'summary');
  text(details, JSON.stringify(value, null, 2), 'pre'); node.append(details);
}
function button(node, label, fn) {
  const b = text(node, label, 'button'); b.type = 'button'; b.addEventListener('click', fn);
}
function numbers(node, r, level) {
  const parts = [[level ?? r?.level?.value, 'Level'],
    [r?.exp ?? (r?.estimated_exp ? `~${r.estimated_exp.value.approximate}` : null), 'EXP'],
    [r?.percentage == null ? null : `${r.estimated_percentage ? '~' : ''}${r.percentage}%`, 'EXP percentage']];
  const row = document.createElement('div'); row.className = 'numbers';
  for (const [value, label] of parts) if (value != null) {
    const item = document.createElement('div'); text(item, value, 'strong'); text(item, label, 'span'); row.append(item);
  }
  node.append(row); return row.children.length > 0;
}
function latest(data) {
  const node = $('latest'); node.replaceChildren();
  const hasValues = numbers(node, data.reading, data.display_level?.value);
  if (!hasValues) {node.replaceChildren(); text(node, 'No recorded level or EXP to show yet. You can enter the correct values below.'); return;}
  const stamp = data.reading?.timestamp ?? data.display_level?.timestamp;
  const manual = data.reading?.evidence === 'manual_admin' || data.display_level?.evidence?.status === 'manual_admin';
  text(node, `${manual ? 'Manually corrected' : 'From game readings'}${stamp ? ' · '+when(stamp) : ''}`, 'p', 'muted');
  audit(node, {reading: data.reading, level: data.display_level});
}
function timeControls() {
  const now = $('use-now').checked, iso = $('use-iso').checked;
  for (const id of ['date', 'time']) {$(id).disabled = now || iso; $(id).required = !now && !iso;}
  $('effective-at').disabled = now || !iso; $('effective-at').required = !now && iso;
  $('iso-field').hidden = !iso;
  $('timezone').textContent = `Your local timezone: ${inputZone}.`;
  $('exact-time').textContent = exactTimestamp ? `Exact timestamp kept: ${exactTimestamp}` : '';
  $('clock-choice').hidden = true; $('clock-time').required = false;
  if (!now && !iso && !exactTimestamp && $('date').value && $('time').value) {
    try {
      const candidates = localCandidates($('date').value, $('time').value);
      if (candidates.length > 1) {
        const previous = $('clock-time').value;
        $('clock-time').replaceChildren(option('', 'Choose a time…'), ...candidates.map(s => option(s, `${when(s)} (${offset(s)})`)));
        if (candidates.includes(previous)) $('clock-time').value = previous;
        $('clock-choice').hidden = false; $('clock-time').required = true;
      }
    } catch { /* Incomplete native input is checked when Review is pressed. */ }
  }
}
function setTimestamp(stamp) {
  const parts = localFields(stamp); $('date').value = parts.date; $('time').value = parts.time;
  $('effective-at').value = stamp; $('use-now').checked = false; $('use-iso').checked = false;
  // Native controls show whole seconds; preserve the source's full precision until edited.
  exactTimestamp = stamp;
}
function mode() {
  invalidate();
  const {action} = edit;
  $('edit-title').textContent = {set: 'Set level and EXP', correct: 'Fix a past reading', amend: 'Edit correction', undo: 'Undo correction', clear: 'Stop using a manual starting point'}[action];
  $('new-correction').hidden = false; $('new-correction').textContent = action === 'set' ? 'Clear form' : 'New correction';
  $('edit-context').hidden = !edit.context; $('edit-context').textContent = edit.context || '';
  $('time-fields').hidden = action === 'undo'; $('time-fields').disabled = action === 'undo';
  $('value-fields').hidden = !['set', 'correct', 'amend'].includes(action);
  $('value-fields').disabled = $('value-fields').hidden;
  $('reason').required = ['amend', 'undo'].includes(action);
  $('reason-note').textContent = $('reason').required ? '(required)' : '(optional)';
  $('target-fields').hidden = !(action === 'correct' || action === 'amend' && edit.kind === 'point');
  $('target-id').required = !$('target-fields').hidden;
  $('target-id').disabled = $('target-fields').hidden;
  $('target-session').value = edit.session;
  $('session-choice').hidden = true; $('recording-choice').required = false;
  $('form-advanced').open = false;
  $('exp').setCustomValidity(''); timeControls();
}
function reset() {
  $('editor').reset(); $('rename-form').hidden = true; $('editor').hidden = false;
  edit = {action: 'set', session: 'auto'}; exactTimestamp = null; mode();
}
function startEdit(next, stamp, values) {
  reset(); edit = next;
  if (stamp) setTimestamp(stamp);
  $('level').value = values?.level ?? ''; $('exp').value = values?.exp ?? ''; $('percentage').value = values?.percentage ?? '';
  mode(); $('editor').scrollIntoView({block: 'center'});
  (next.action === 'undo' ? $('reason') : $('level')).focus({preventScroll: true});
}
function editEvent(e, action = 'amend') {
  startEdit({action, correction: e.id, kind: e.kind, session: e.session_id == null ? 'none' : String(e.session_id),
    context: `${action === 'undo' ? 'Undo the correction for' : 'Editing the correction for'} ${scope.character.label} on ${when(e.effective_at)}.${action === 'undo' ? ' Earlier versions of this correction will stay undone.' : ''}`},
  e.effective_at, {level: e.level, exp: e.current_exp, percentage: bpText(e.percentage_bp)});
  $('target-kind').value = e.target_kind ?? 'diagnostic'; $('target-id').value = e.target_event_id ?? '';
}
function renderHistory(data) {
  $('history').replaceChildren();
  for (const e of [...(data.corrections ?? [])].reverse()) {
    const row = document.createElement('article'); row.dataset.correctionId = e.id;
    const label = e.operation === 'retract' ? 'Correction undone' : e.action === 'clear' ? 'Manual starting point stopped' :
      e.kind === 'point' ? 'Past reading corrected' : 'Level and EXP set';
    text(row, label, 'h3');
    text(row, when(e.effective_at)+(e.active ? '' : ' · No longer applied'), 'p', 'muted');
    if (e.action === 'set') numbers(row, {exp: e.current_exp, percentage: e.percentage_bp == null ? null : bpText(e.percentage_bp)}, e.level);
    if (e.reason) text(row, e.reason);
    if (e.active) {
      if (e.action === 'set') button(row, 'Edit', () => editEvent(e));
      button(row, 'Undo', () => editEvent(e, 'undo'));
    }
    audit(row, e); $('history').append(row);
  }
  for (const e of data.renames ?? []) {
    const row = document.createElement('article'); text(row, `${e.previous_label} → ${e.label}`, 'h3');
    text(row, when(e.recorded_at), 'p', 'muted'); audit(row, e); $('history').append(row);
  }
  if (!$('history').children.length) text($('history'), 'No corrections yet.');
}
function renderReadings(data) {
  $('readings').replaceChildren();
  for (const r of [...(data.readings ?? [])].sort((a,b) => new Date(b.timestamp)-new Date(a.timestamp))) {
    const row = document.createElement('article'); row.dataset.readingId = r.identity; row.dataset.readingKind = r.kind;
    text(row, when(r.timestamp), 'h3');
    if (!numbers(row, r.presentation, r.presentation?.level?.value ?? r.original_level ?? r.original?.level))
      text(row, 'No readable level or EXP in this reading.', 'p', 'muted');
    const existing = scope.corrections?.find(e => e.active && e.kind === 'point' && e.target_kind === r.kind && String(e.target_event_id) === String(r.identity));
    button(row, existing ? 'Edit correction' : 'Fix', () => {
      if (existing) {editEvent(existing); return;}
      const p = r.presentation;
      startEdit({action: 'correct', session: String(r.session_id), context: `Fixing ${scope.character.label}'s reading from ${when(r.timestamp)}. The original time is kept exactly.`},
        r.timestamp, {level: p?.level?.value ?? r.original_level ?? r.original?.level,
          exp: p?.exp ?? '', percentage: p?.estimated_percentage ? '' : p?.percentage ?? ''});
      $('target-kind').value = r.kind; $('target-id').value = r.identity;
    });
    audit(row, r); $('readings').append(row);
  }
  if (!$('readings').children.length) text($('readings'), 'No past readings in this period.');
}
const period = s => `${when(s.started_at)}${s.ended_at ? ' – '+when(s.ended_at) : ' – still recording'}`;
function inspectPath(session = '') {
  const query = new URLSearchParams({channel: $('channel').value});
  if ($('character').value) query.set('character_id', $('character').value);
  if (session) query.set('session_id', session);
  return '/api/inspect?'+query;
}
async function load(channelChanged = false, characterChanged = false, pastOnly = false) {
  if (loading) return;
  loading = true; invalidate(); block();
  try {
    if (pastOnly) {view = await api(inspectPath($('session').value)); renderReadings(view); return;}
    const query = new URLSearchParams({channel: $('channel').value});
    if (!channelChanged && $('character').value) query.set('character_id', $('character').value);
    scope = await api('/api/inspect?'+query);
    if (!scope.session && !scope.reading && scope.sessions?.length) scope = await api('/api/inspect?'+query+'&session_id='+scope.sessions[0].id);
    $('character').replaceChildren(...scope.characters.map(c => option(c.id, c.label)));
    if (scope.character) $('character').value = String(scope.character.id);
    else {$('character').prepend(option('', 'Choose a character')); $('character').value = '';}
    const oldPeriod = channelChanged || characterChanged ? '' : $('session').value;
    $('session').replaceChildren(option('', 'Latest recorded period'), ...(scope.sessions ?? []).map(s => option(s.id, period(s))));
    if ([...$('session').options].some(o => o.value === oldPeriod)) $('session').value = oldPeriod;
    $('target-session').replaceChildren(option('auto', 'Choose automatically'), option('none', 'Outside recorded play times'),
      ...(scope.sessions ?? []).map(s => option(s.id, period(s))));
    if (channelChanged || characterChanged) reset();
    else $('target-session').value = edit.session;
    view = $('session').value ? await api(inspectPath($('session').value)) : scope;
    latest(scope); renderHistory(scope); renderReadings(view);
    status(scope.character ? '' : 'Select a character to enter its level and EXP.');
  } catch (e) {
    if (!pastOnly) {
      scope = null; $('latest').replaceChildren(); $('history').replaceChildren();
      text($('latest'), 'Could not load the latest information. Choose Refresh to try again.');
      text($('history'), 'Correction history could not be loaded.');
    }
    $('readings').replaceChildren(); text($('readings'), 'Past readings could not be loaded. Try Refresh.');
    status(friendlyError(e.message), true);
  }
  finally {loading = false; block();}
}
function effectiveTime() {
  if ($('use-now').checked) return {use_now: true};
  if ($('use-iso').checked) return {effective_at: $('effective-at').value};
  if (timezone() !== inputZone) throw Error('Your timezone changed. Reload this page before entering a local time.');
  return {effective_at: exactTimestamp ?? localTimestamp($('date').value, $('time').value, $('clock-time').value)};
}
function payload() {
  const data = {action: edit.action, channel: $('channel').value, character_id: $('character').value};
  if ($('reason').value) data.reason = $('reason').value;
  if (edit.action === 'undo') return {...data, correction_id: String(edit.correction)};
  Object.assign(data, effectiveTime());
  data.session_id = $('session-choice').hidden ? $('target-session').value : $('recording-choice').value;
  if (edit.action !== 'clear') {
    data.level = $('level').value;
    if ($('exp').value !== '') data.exp = $('exp').value;
    if ($('percentage').value !== '') data.percentage = $('percentage').value;
  }
  if (edit.action === 'amend') {data.correction_id = String(edit.correction); data.kind = edit.kind;}
  if (edit.action === 'correct' || edit.action === 'amend' && edit.kind === 'point') {
    data.target_kind = $('target-kind').value; data.target_event_id = $('target-id').value;
  }
  return data;
}
function friendlyError(message) {
  if (message.includes('ambiguous session')) return 'This time belongs to two recordings. Choose the recording below and review again.';
  if (message.includes('outside the character/session scope')) return 'This character was not being tracked at that time. Check the date and time, or choose Outside recorded play times in Advanced.';
  if (message.includes('no reading matches')) return 'The original reading does not have this exact time. Choose it again from Past readings to keep its original time.';
  if (message.includes('level and at least one')) return 'Enter a level and numerical EXP or EXP percentage.';
  if (message.includes('inactive')) return 'This correction has already changed. Refresh the history and choose the current correction.';
  if (message.includes('preview expired')) return 'This review has expired. Review the changes again before saving.';
  if (message.includes('manual_admin')) return 'The change could not be saved. Refresh the page and try again.';
  return message;
}
function showReview(value) {
  const e = value.event, r = value.reading, name = value.character.label;
  const at = e.effective_at ? when(e.effective_at) : '';
  const pct = r?.percentage == null ? '' : ` at ${r.estimated_percentage ? '~' : ''}${r.percentage}%`;
  $('preview-summary').textContent = value.action === 'rename' ? `You're renaming ${e.previous_label} to ${e.label}.` :
    value.action === 'undo' ? `You're undoing the correction for ${name} on ${at}.` :
    value.action === 'clear' ? `You're stopping the manual starting point for ${name} from ${at}.` :
    `You're ${value.action === 'amend' ? 'changing the correction for' : 'setting'} ${name} to level ${e.level}${pct} on ${at}.`;
  $('preview-values').replaceChildren();
  if (r?.exp != null) text($('preview-values'), `Numerical EXP: ${r.exp}`);
  else if (r?.estimated_exp) text($('preview-values'), `Approximate EXP: ~${r.estimated_exp.value.approximate}`);
  if (r?.estimated_percentage) text($('preview-values'), 'The percentage is approximate, calculated from the EXP you entered.', 'p', 'muted');
  if (e.reason) text($('preview-values'), `Reason: ${e.reason}`);
  $('preview-warning').hidden = r?.exp_validity?.status !== 'invalid';
  $('preview-warning').textContent = "EXP values don't match. Check the level and any EXP values you've entered. Your entered values will be kept.";
  $('preview-notice').textContent = value.action === 'rename' ? 'History stays with the same character. Update its name in the capture roster before the next restart.' :
    value.action === 'undo' ? 'Original game readings are kept. Earlier versions of this correction will not be restored.' :
    'This corrects the recorded information. It does not add earned EXP or erase game readings.';
  $('preview-audit').textContent = JSON.stringify(value, null, 2);
  $('editor').hidden = true; $('rename-form').hidden = true; $('preview').hidden = false;
  previewId = value.preview_id; $('preview').focus();
  status('Review the changes, then save when you are ready.');
}
async function submit(save = false, rename = false) {
  if (busy || loading || !scope?.character) return;
  if (!save && !rename && ['set', 'correct', 'amend'].includes(edit.action) && !$('exp').value && !$('percentage').value) {
    $('exp').setCustomValidity('Enter numerical EXP or EXP percentage.'); $('exp').reportValidity();
    status('Enter numerical EXP or EXP percentage.', true); return;
  }
  const editingName = rename || save && $('preview').dataset.rename === 'true';
  busy = true; block();
  try {
    if (save) {
      const value = await api('/api/save', {preview_id: previewId});
      $('saved-audit').textContent = JSON.stringify(value, null, 2); $('receipt').hidden = false; $('receipt').open = false;
      reset(); await load();
      const message = value.action === 'rename' ? `Saved. Character renamed to ${value.event.label}. Update its name in your capture roster before the next restart.` :
        value.action === 'undo' ? 'Saved. Correction undone.' : 'Saved. Your changes have been applied.';
      status(scope ? message : `${message} Refresh failed: ${$('status').textContent}`, !scope);
      $('status').scrollIntoView({block: 'nearest'});
    } else {
      const data = rename ? {action: 'rename', channel: $('channel').value, character_id: $('character').value, new_name: $('new-name').value,
        ...($('rename-reason').value ? {reason: $('rename-reason').value} : {})} : payload();
      invalidate(); showReview(await api('/api/preview', data));
      $('preview').dataset.rename = String(rename);
    }
  } catch (e) {
    invalidate(); status(friendlyError(e.message), true);
    if (editingName) {$('rename-form').hidden = false; $('editor').hidden = true;}
    if (e.message.includes('ambiguous session')) {
      $('session-choice').hidden = false; $('recording-choice').required = true;
      $('recording-choice').replaceChildren(option('', 'Choose a recording…'), ...scope.sessions.map(s => option(s.id, period(s))));
      $('recording-choice').focus();
    }
  } finally {busy = false; block();}
}
$('editor').addEventListener('submit', e => {e.preventDefault(); submit();});
$('rename-form').addEventListener('submit', e => {e.preventDefault(); submit(false, true);});
for (const id of ['editor', 'rename-form']) $(id).addEventListener('input', () => {invalidate(); $('exp').setCustomValidity('');});
function clearRecordingChoice() {$('session-choice').hidden = true; $('recording-choice').required = false;}
for (const id of ['date', 'time']) $(id).addEventListener('input', () => {exactTimestamp = null; $('clock-time').value = ''; clearRecordingChoice(); timeControls();});
$('use-now').addEventListener('change', () => {clearRecordingChoice(); timeControls();});
$('use-iso').addEventListener('change', () => {
  if (!$('use-iso').checked) {
    const stamp = $('effective-at').value;
    if (/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(stamp) && Number.isFinite(Date.parse(stamp))) setTimestamp(stamp);
    else {exactTimestamp = null; $('date').value = ''; $('time').value = '';}
  }
  clearRecordingChoice();
  timeControls();
});
$('effective-at').addEventListener('input', () => {exactTimestamp = null; clearRecordingChoice();});
$('save').addEventListener('click', () => submit(true));
$('cancel').addEventListener('click', () => {
  const rename = $('preview').dataset.rename === 'true'; invalidate();
  $('rename-form').hidden = !rename; $('editor').hidden = rename;
  (rename ? $('new-name') : $('level')).focus(); status('Nothing saved. You can keep editing.');
});
$('rename').addEventListener('click', () => {
  invalidate(); $('rename-form').reset(); $('rename-form').hidden = false; $('editor').hidden = true;
  $('new-name').value = scope.character.label; $('new-name').focus(); $('new-name').select();
});
$('cancel-rename').addEventListener('click', () => {reset(); $('character').focus();});
$('new-correction').addEventListener('click', reset);
$('clear').addEventListener('click', () => {edit = {action: 'clear', session: 'auto'}; mode(); $('date').focus();});
$('find-reading').addEventListener('click', () => {edit = {action: 'correct', session: 'auto'}; mode(); $('form-advanced').open = true; $('target-id').focus();});
$('target-session').addEventListener('change', () => {edit.session = $('target-session').value;});
$('channel').addEventListener('change', () => load(true)); $('character').addEventListener('change', () => load(false, true));
$('session').addEventListener('change', () => load(false, false, true)); $('refresh').addEventListener('click', () => load());
for (const link of document.querySelectorAll('nav a')) link.addEventListener('click', () => {document.querySelector(link.hash).open = true;});
reset(); block();
(async () => {
  try {
    const data = await api('/api/channels'); $('database').textContent = `Database: ${data.database}`;
    $('channel').replaceChildren(...data.channels.map(c => option(c.login, c.login)));
    if (data.channels.length) await load(true);
    else status('No characters to choose yet. Add a channel and character with the tracking tools first.');
  } catch (e) {status(friendlyError(e.message), true);}
  finally {block();}
})();
