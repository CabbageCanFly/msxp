'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="admin-token"]').content;
let scope, previewId = null, busy = false, loading = false;

function status(message, error = false) {
  $('status').textContent = message;
  $('status').classList.toggle('error', error);
}
async function api(path, data) {
  const response = await fetch(path, {headers: {'X-Admin-Token': token, ...(data ? {'Content-Type': 'application/json'} : {})},
    ...(data ? {method: 'POST', body: JSON.stringify(data)} : {})});
  const value = await response.json();
  if (!response.ok) throw Error(value.error || `Request failed (${response.status})`);
  return value;
}
function invalidate() { previewId = null; $('preview').hidden = true; $('save').disabled = true; }
function block() {
  for (const id of ['channel', 'character', 'session', 'refresh']) $(id).disabled = busy || loading;
  for (const id of ['editor', 'history', 'readings']) $(id).inert = busy || loading;
}
function option(value, text) { return new Option(text, String(value)); }
function values(node, pairs) {
  node.replaceChildren();
  for (const [name, value] of pairs) {
    const term = document.createElement('dt'), description = document.createElement('dd');
    term.textContent = name; description.textContent = value ?? 'Unavailable'; node.append(term, description);
  }
}
function readingValues(node, reading, displayLevel) {
  const r = reading;
  values(node, [['Level', displayLevel?.value ?? r?.level?.value],
    ['Current EXP', r?.exp ?? (r?.estimated_exp ? `Estimated: ${r.estimated_exp.value.approximate}` : null)],
    ['Percentage', r?.percentage == null ? null : `${r.estimated_percentage ? '~' : ''}${r.percentage}%`],
    ['EXP source', r?.evidence], ['Level source', displayLevel?.evidence?.status ?? r?.level?.status ?? r?.evidence],
    ['Effective time', r?.timestamp],
    ['Arithmetic check', r?.exp_validity ? `${r.exp_validity.status}: ${r.exp_validity.reason}` : null]]);
}
function audit(node, value, label = 'Audit provenance and original values') {
  const details = document.createElement('details'), summary = document.createElement('summary'), pre = document.createElement('pre');
  summary.textContent = label; pre.textContent = JSON.stringify(value, null, 2);
  details.append(summary, pre); node.append(details);
}
function button(node, label, fn) {
  const b = document.createElement('button'); b.type = 'button'; b.textContent = label;
  b.addEventListener('click', fn); node.append(b);
}
function mode() {
  invalidate();
  const action = $('action').value, correction = ['set', 'correct', 'amend'].includes(action);
  const point = action === 'correct' || action === 'amend' && $('kind').value === 'point';
  for (const [id, visible] of [['revision-fields', ['amend', 'undo'].includes(action)],
    ['kind-fields', action === 'amend'], ['time-fields', correction || action === 'clear'],
    ['point-fields', point], ['value-fields', correction], ['rename-fields', action === 'rename']]) {
    $(id).hidden = !visible; $(id).disabled = !visible;
  }
  $('effective-at').disabled = $('use-now').checked;
  $('reason').required = ['amend', 'undo'].includes(action);
}
function edit(action) {
  $('action').value = action; mode();
  $('editor').scrollIntoView({behavior: 'smooth', block: 'start'});
}
function fromEvent(event, action) {
  $('correction-id').value = event.id;
  $('kind').value = event.kind;
  $('level').value = event.level ?? ''; $('exp').value = event.current_exp ?? '';
  // Use server-supplied presentation for formatting only; no EXP arithmetic in the form.
  $('percentage').value = '';
  if (event.percentage_bp != null) $('percentage').value = String(event.percentage_bp).padStart(3, '0').replace(/(..)$/, '.$1');
  $('effective-at').value = event.effective_at; $('use-now').checked = false;
  $('target-session').value = event.session_id == null ? 'none' : String(event.session_id);
  $('target-kind').value = event.target_kind ?? 'diagnostic'; $('target-id').value = event.target_event_id ?? '';
  $('reason').value = ''; edit(action);
}
function renderHistory(data) {
  $('history').replaceChildren();
  for (const e of [...data.corrections].reverse()) {
    const row = document.createElement('article'), title = document.createElement('h3'), p = document.createElement('p');
    title.textContent = `#${e.id} · ${e.operation === 'retract' ? 'Undo' : e.action === 'clear' ? 'Clear' : e.kind} · ${e.active ? 'Active revision' : 'Inactive'}`;
    p.textContent = `Effective ${e.effective_at} · recorded ${e.recorded_at} · session ${e.session_id ?? 'unbound'}${e.replaces_id ? ` · replaces #${e.replaces_id}` : ''}${e.superseded_by ? ` · superseded by #${e.superseded_by}` : ''}`;
    row.append(title, p);
    if (e.reason) {const reason = document.createElement('p'); reason.textContent = e.reason; row.append(reason);}
    if (e.active) {
      if (e.action === 'set') button(row, 'Amend', () => fromEvent(e, 'amend'));
      button(row, 'Undo', () => fromEvent(e, 'undo'));
    }
    audit(row, e); $('history').append(row);
  }
  for (const e of data.renames) {
    const row = document.createElement('article'); row.textContent = `Rename #${e.id}: ${e.previous_label} → ${e.label} · ${e.recorded_at}`;
    audit(row, e); $('history').append(row);
  }
  if (!$('history').children.length) $('history').textContent = 'No corrections or renames for this character.';
}
function renderReadings(data) {
  $('readings').replaceChildren();
  for (const r of [...data.readings].reverse()) {
    const row = document.createElement('article'), title = document.createElement('h3');
    title.textContent = `${r.kind} ${r.identity} · ${r.timestamp}`; row.append(title);
    const dl = document.createElement('dl');
    readingValues(dl, r.presentation, r.presentation?.level ?? (r.original_level ? {value: r.original_level} : r.original ? {value: r.original.level} : null));
    row.append(dl);
    button(row, 'Correct', () => {
      $('effective-at').value = r.timestamp; $('use-now').checked = false;
      $('target-session').value = String(r.session_id); $('target-kind').value = r.kind; $('target-id').value = r.identity;
      $('level').value = r.presentation?.level?.value ?? r.original_level ?? r.original?.level ?? '';
      $('exp').value = ''; $('percentage').value = ''; $('reason').value = ''; edit('correct');
    });
    audit(row, r); $('readings').append(row);
  }
  if (!data.readings.length) $('readings').textContent = 'No readings in this view. Select a historical session or enter an original identity and timestamp above.';
}
async function load(channelChanged = false, characterChanged = false) {
  if (loading) return;
  loading = true; block(); invalidate(); $('preview-button').disabled = true;
  status('Loading character records…');
  try {
    const query = new URLSearchParams({channel: $('channel').value});
    if (!channelChanged && $('character').value) query.set('character_id', $('character').value);
    if (!channelChanged && !characterChanged && $('session').value) query.set('session_id', $('session').value);
    const data = await api('/api/inspect?' + query); scope = data;
    if (channelChanged || characterChanged) {$('editor').reset(); mode();}
    const selected = data.character?.id;
    $('character').replaceChildren(...data.characters.map(c => option(c.id, `${c.label} (#${c.id})`)));
    if (selected) $('character').value = String(selected);
    else { $('character').prepend(option('', 'Choose an existing character')); $('character').value = ''; }
    $('session').replaceChildren(option('', 'Latest / choose automatically'), ...(data.sessions ?? []).map(s => option(s.id, `#${s.id} · ${s.started_at}${s.ended_at ? ' · closed' : ' · open'}`)));
    if (query.has('session_id')) $('session').value = query.get('session_id');
    $('target-session').replaceChildren(option('auto', 'Resolve from character and effective time'), option('none', 'Explicitly unbound / no session'),
      ...(data.sessions ?? []).map(s => option(s.id, `Session #${s.id} · ${s.started_at}`)));
    $('target-session').value = $('session').value || 'auto';
    readingValues($('latest'), data.reading, data.display_level);
    renderHistory({...data, corrections: data.corrections ?? [], renames: data.renames ?? []});
    renderReadings({...data, readings: data.readings ?? []});
    $('preview-button').disabled = !selected;
    status(selected ? `Inspecting ${data.character.label} (#${selected}). ${data.session ? `Session #${data.session.id}.` : 'Select a session to inspect older characters with multiple sessions.'}` : 'No selected character. Select an existing character to inspect it.');
  } catch (e) { scope = null; status(e.message, true); }
  finally {loading = false; block();}
}
function payload() {
  const action = $('action').value;
  const data = {action, channel: $('channel').value, character_id: $('character').value};
  if ($('reason').value) data.reason = $('reason').value;
  if (action === 'rename') data.new_name = $('new-name').value;
  else if (action === 'undo') data.correction_id = $('correction-id').value;
  else {
    data.session_id = $('target-session').value;
    if ($('use-now').checked) data.use_now = true;
    else data.effective_at = $('effective-at').value;
    if (action !== 'clear') {
      data.level = $('level').value;
      if ($('exp').value !== '') data.exp = $('exp').value;
      if ($('percentage').value !== '') data.percentage = $('percentage').value;
    }
    if (action === 'amend') { data.correction_id = $('correction-id').value; data.kind = $('kind').value; }
    if (!$('point-fields').hidden) {data.target_kind = $('target-kind').value; data.target_event_id = $('target-id').value;}
  }
  return data;
}
async function submit(save) {
  if (busy || loading || !scope) return;
  busy = true; block(); $('preview-button').disabled = true; $('save').disabled = true;
  try {
    if (save) {
      if (!previewId) throw Error('Preview changes before saving.');
      const value = await api('/api/save', {preview_id: previewId}); invalidate();
      $('saved-audit').textContent = JSON.stringify(value, null, 2); $('receipt').hidden = false; $('receipt').open = true;
      await load();
      const saved = `Saved ${value.action} · audit #${value.event.id}. ${value.notice}`;
      status(scope ? saved : `${saved} Refresh failed: ${$('status').textContent}`, !scope);
    } else {
      invalidate();
      const value = await api('/api/preview', payload()); previewId = value.preview_id;
      const e = value.event;
      $('preview-summary').textContent = `${value.action} for ${value.character.label} (#${value.character.id}) on ${value.channel}. ` +
        (value.action === 'rename' ? `${e.previous_label} → ${e.label}.` :
          `Effective ${e.effective_at} (${value.timestamp_choice}). Session ${e.session_id ?? 'unbound'}. ` +
          `${e.replaces_id ? `Replaces correction #${e.replaces_id}. ` : ''}${e.target_event_id ? `Original ${e.target_kind} ${e.target_event_id}.` : ''}`);
      readingValues($('preview-values'), value.reading);
      $('preview-values').hidden = !value.reading;
      $('preview-audit').textContent = JSON.stringify(value, null, 2); $('preview-notice').textContent = value.notice;
      $('preview').hidden = false; $('save').disabled = false; $('preview').focus();
      status('Preview only. Review the exact values and provenance, then confirm to save.');
    }
  } catch (e) { invalidate(); status(e.message, true); }
  finally {busy = false; block(); $('preview-button').disabled = !scope?.character;}
}
$('editor').addEventListener('submit', e => {e.preventDefault(); submit(false);});
$('editor').addEventListener('input', invalidate);
$('action').addEventListener('change', mode); $('kind').addEventListener('change', mode); $('use-now').addEventListener('change', mode);
$('save').addEventListener('click', () => submit(true)); $('cancel').addEventListener('click', () => {invalidate(); status('Preview cancelled. No write was made.');});
$('channel').addEventListener('change', () => load(true)); $('character').addEventListener('change', () => load(false, true));
$('session').addEventListener('change', () => load()); $('refresh').addEventListener('click', () => load());
mode();
(async () => {
  try {
    const data = await api('/api/channels'); $('database').textContent = `Database: ${data.database}`;
    $('channel').replaceChildren(...data.channels.map(c => option(c.login, c.login)));
    if (data.channels.length) await load(true); else status('No channels in this database. Initialize explicit selections with the existing tracking tools first.');
  } catch (e) {status(e.message, true);}
})();
