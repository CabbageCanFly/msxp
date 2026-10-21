"""Server-owned publication of public player state; HTTP requests only present it.

One refresher builds each due channel's card and tracked-EXP packet together, in one
read transaction, and publishes them as an immutable entry. Requests never build cards,
replay history or call Twitch. They time-present the latest entries and reuse the
serialized body for at most PRESENT_SECONDS of as-of clock. A character poll that names the
content revisions it already holds is sent the chart history and tracked packet only when changed.

A visitor may also view one of the channel's unselected characters. Those views are
built by the same refresher, on demand, at most MAX_VIEWS at once. Least recently
polled views are replaced when full; idle views expire after VIEW_IDLE_SECONDS.
Viewing never changes the selection.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
import time

from .character_automation import PLACEHOLDER_CHARACTER
from .diagnostics import Diagnostics, due, operation, present_card
from .product import refresh, tracked_statistics
from .store import Store, utc

PRESENT_SECONDS = 1  # A presented body is reused for at most this long.
TRACKED_SECONDS = 30  # Tracked windows age even without a new capture, as before.
RETRY_SECONDS = (5, 60)  # Failed channel refresh: exponential backoff bounds.
# Never in public responses, at any depth: internal identities, capture scheduling, and
# diagnostics no public page reads. Calculations, publisher state and /dev keep them.
PRIVATE_FIELDS = frozenset({
    'source_identity', 'coordinator_instance', 'run_id', 'run_ids', 'session_id',
    'updated_at', 'next_due_at', 'expected_completion_seconds', 'requested_interval_seconds',
    'actual_interval_seconds', 'skipped_deadlines',
    'excluded', 'holes', 'latest_endpoint', 'last_observed_eta', 'eligibility_checks',
    'evidence_counts', 'published_alternatives'})
CHARACTER_ONLY = ('current_level_windows', 'tracked_current_level_windows')  # Only the character page's level toggle reads them.
MAX_VIEWS = 8  # Unselected-character views across all channels.
VIEW_IDLE_SECONDS = 60


def broadcast(players, statuses, now):
    """Twitch status is separate from capture health; unknown never means offline."""
    for value in players:
        value['twitch'] = dict(statuses.get(value['channel'], dict(status='not_applicable' if value['source_kind'] == 'file' else 'unknown', reason='source_unavailable')))
        status = value['twitch']
        status['capture_disagreement'] = bool(status['status'] == 'offline' and value.get('latest_attempt_at') and status.get('checked_at')
            and datetime.fromisoformat(value['latest_attempt_at']) >= datetime.fromisoformat(status['checked_at']) - timedelta(seconds=60)
            and value['latest_attempt_status'] != 'capture_failed')
    return [refresh(p, now=now, activity=p.get('activity')) for p in players]


def encode(body):
    return json.dumps(body, allow_nan=False).encode()


def public(value):
    """The same values without PRIVATE_FIELDS."""
    if isinstance(value, dict):return {k: public(v) for k, v in value.items() if k not in PRIVATE_FIELDS}
    if isinstance(value, list):return [public(v) for v in value]
    return value


def public_character(character):
    """Visitors never see the internal pre-recognition placeholder as a name."""
    return dict(character, label='—') if character and character['label'] == PLACEHOLDER_CHARACTER else character


def public_roster(rows, level):
    """Selectable characters: the current one first, then most recently seen; no placeholder."""
    rows = [dict(r, level=level if r['current'] and level is not None else r['level'])
            for r in rows if r['label'] != PLACEHOLDER_CHARACTER]
    rows.sort(key=lambda r: (not r['current'], r['last_seen_at'] is None,
        -datetime.fromisoformat(r['last_seen_at']).timestamp() if r['last_seen_at'] else 0, r['id']))
    return [{k: r[k] for k in ('id', 'label', 'level', 'last_seen_at', 'current')} for r in rows]


def revision(value):
    """Content revision of a published section: equal content, equal revision."""
    return hashlib.sha256(encode(value)).hexdigest()[:16]


class Publisher:
    def __init__(self, server, *, clock, background):
        self.server, self.clock, self.background = server, clock, background
        self.lock = threading.Lock()  # Guards the published fields below.
        self.work = threading.Lock()  # One refresher; inline requests take turns.
        self.entries = {}; self.heads = []; self.truncated = False; self.statuses = {}
        self.generation = 0; self.failures = {}; self.wanted = set()
        self.cards = {}  # Card cache owned by the refresher (see Diagnostics.card).
        self.presented = {}; self.present_locks = {}
        self.views = {}; self.viewed = {}  # ('view', login, character) -> entry / last poll (monotonic).
        self.stats = dict(steps=0, builds=0, build_seconds=0.0, max_build_seconds=0.0, failures=0,
            last_error=None, presentations=0, present_seconds=0.0, ready_at=None, started_at=None)
        self.stop = threading.Event(); self.wake = threading.Event(); self.thread = None

    # Refresher ---------------------------------------------------------------

    def start(self):
        self.stats['started_at'] = time.monotonic()
        try:  # Channel list only, so the first homepage already names warming channels.
            with Store(self.server.database, read_only=True) as store, store._transaction():
                self.publish_heads(Diagnostics(store).heads(), self.statuses)
        except Exception as error:
            self.stats['last_error'] = type(error).__name__
        if self.background:
            self.thread = threading.Thread(target=self.run, name='publisher', daemon=True)
            self.thread.start()

    def close(self, timeout=30):
        self.stop.set(); self.wake.set()
        if self.thread:self.thread.join(timeout)

    def run(self):
        while not self.stop.is_set():
            try:busy = self.step()
            except Exception as error:  # Database unavailable: keep the last entries, retry.
                busy = False; self.stats['failures'] += 1; self.stats['last_error'] = type(error).__name__
            if not busy:
                self.wake.wait(1); self.wake.clear()

    def settle(self):
        """Inline mode: build everything due now, as the former synchronous requests did."""
        for _ in range(64):
            if not self.step():return

    def want(self, channel):
        """A viewer is waiting for this channel: build it before other cold channels."""
        with self.lock:self.wanted.add(channel)
        self.wake.set()

    def step(self):
        """Refresh heads and Twitch status, then build at most one due channel."""
        with self.work:
            self.stats['steps'] += 1
            now = self.clock()
            with Store(self.server.database, read_only=True) as store:
                diagnostics = Diagnostics(store)
                with store._transaction():
                    heads = diagnostics.heads()
                    sources = store.db.execute('''SELECT s.login,r.configuration_json AS config,
                        (SELECT payload_json FROM diagnostic_attempts WHERE run_id=r.run_id ORDER BY attempt_index DESC LIMIT 1) AS payload
                        FROM streamers s LEFT JOIN diagnostic_runs r ON r.rowid=(
                            SELECT rowid FROM diagnostic_runs WHERE streamer_id=s.id ORDER BY rowid DESC LIMIT 1)
                        ORDER BY s.login LIMIT 25''').fetchall()
                twitch = [r['login'] for r in sources if (json.loads(r['config'] or '{}').get('source_kind') or
                    json.loads(r['payload'] or '{}').get('source', {}).get('kind')) == 'twitch']
                self.publish_heads(heads, self.statuses)
                statuses = self.server.twitch_availability.snapshot(twitch, now=now)
                with self.lock:self.statuses = statuses
                now = self.clock()  # Network time is not part of the subsequent database snapshot.
                pending = self.due(heads[:25], now)
                views = self.due_views(diagnostics, heads[:25], now)
                # Browsing must not delay fresh tracked-channel publications.
                if pending:self.build(diagnostics, store, pending[0], now)
                elif views:self.build(diagnostics, store, views[0][1][1], now, view=views[0][1:])
                if not pending[1:] and self.stats['ready_at'] is None and all(h['login'] in self.entries for h in heads[:25]):
                    self.stats['ready_at'] = time.monotonic()
                return len(pending) + len(views) > 1

    def publish_heads(self, heads, statuses):
        """Channel list and Twitch status; removed channels lose every cached state."""
        logins = {h['login'] for h in heads[:25]}
        with self.lock:
            if [h['login'] for h in heads[:25]] != [h['login'] for h in self.heads]:self.generation += 1
            self.heads = list(heads[:25]); self.truncated = len(heads) > 25; self.statuses = statuses
            for login in [c for c in self.entries if c not in logins]:
                del self.entries[login]; self.generation += 1
            for head in self.heads:
                entry = self.entries.get(head['login'])
                if entry and entry['key'][1:3] != tuple(head)[1:3]:
                    # A failed refresh may retain old readings, never a different ownership scope.
                    del self.entries[head['login']]; self.generation += 1
                    self.failures.pop(head['login'], None)
            for cache in (self.cards, self.failures, self.presented, self.present_locks, self.views, self.viewed):
                for key in [k for k in cache if (k[1] if isinstance(k, tuple) else k) not in logins | {'home', 'home-characters'}]:del cache[key]
            self.wanted &= logins

    def due(self, heads, now):
        """Cold (wanted first), then all due publications oldest first."""
        ranked = []
        for head in heads:
            login = head['login']; entry = self.entries.get(login); failure = self.failures.get(login)
            if failure and now < failure[1]:continue
            if entry is None:rank = (0 if login in self.wanted else 1, '')
            elif entry['key'] != tuple(head):rank = (2, entry['built_at'])
            elif (due(entry['card']['player'], entry['card']['recent_as_of'], now)
                    or not timedelta(0) <= now - datetime.fromisoformat(entry['built_at']) < timedelta(seconds=TRACKED_SECONDS)):
                rank = (2, entry['built_at'])
            else:continue
            ranked.append((rank, login))
        return [login for _, login in sorted(ranked)]

    def due_views(self, diagnostics, heads, now):
        """Polled views of unselected characters: cold first, then due, oldest first.

        A view whose character became selected, or whose saved data changed, is dropped
        at once: it is never served in place of the channel entry or a fresh build.
        """
        heads = {h['login']: h for h in heads}; idle = time.monotonic() - VIEW_IDLE_SECONDS
        with self.lock:
            for key in [k for k, seen in self.viewed.items() if seen < idle or k[1] not in heads
                        or heads[k[1]]['selected_character_id'] == k[2]]:
                self.drop_view(key)
            wanted = list(self.viewed)
        rosters = {}; ranked = []
        for key in wanted:
            failure = self.failures.get(key)
            if failure and now < failure[1]:continue
            if key[1] not in rosters:rosters[key[1]] = {r['id']: r for r in diagnostics.roster(key[1])}
            head = heads[key[1]]; row = rosters[key[1]].get(key[2])
            current = (head['manual_revision'], head['rename_revision'], head['invalidation_revision'],
                       head['retention_revision'], row and row['revision'])
            entry = self.views.get(key)
            if entry is not None and entry['key'] != current:
                with self.lock:
                    if self.views.pop(key, None):self.generation += 1
                entry = None
            if entry is None:rank = (0, '')
            elif (due(entry['card']['player'], entry['card']['recent_as_of'], now)
                    or not timedelta(0) <= now - datetime.fromisoformat(entry['built_at']) < timedelta(seconds=TRACKED_SECONDS)):
                rank = (1, entry['built_at'])
            else:continue
            ranked.append((rank, key, current))
        return [(rank[0], key, current) for rank, key, current in sorted(ranked)]

    def build(self, diagnostics, store, login, now, *, view=None):
        """view: (('view', login, character), revision) builds that unselected character instead."""
        tick = time.perf_counter(); name = view[0] if view else login
        try:
            with store._transaction():
                # Card and tracked packet share one database snapshot and clock.
                head = diagnostics.heads(login)[0]
                character = view[0][2] if view else None
                # A view keeps no card cache; due_views decides when it is rebuilt.
                _, card, extras = diagnostics.card({} if view else self.cards, head, now=now,
                    checkpoints=self.server.checkpoints, eta_cache=self.server.eta_cache, character=character)
                tracked = diagnostics.rolling_history(login, now=now, checkpoints=self.server.checkpoints, character=character)
                roster = None if view else diagnostics.roster(login)
        except Exception as error:
            attempts = self.failures.get(name, (0, None))[0] + 1
            self.failures[name] = (attempts, now + timedelta(seconds=min(RETRY_SECONDS[1], RETRY_SECONDS[0] * 2 ** (attempts - 1))))
            self.stats['failures'] += 1; self.stats['last_error'] = type(error).__name__
            return
        seconds = time.perf_counter() - tick
        # Projected once per publication; requests present only these public copies.
        shown = dict(player=public(card['player']), history=public(extras['history']), tracked=public(tracked))
        shown['player']['character'] = public_character(shown['player']['character'])
        entry = dict(key=view[1] if view else tuple(head), built_at=now.isoformat(), card=card, extras=extras, tracked=tracked, build_seconds=seconds,
            public=shown, revisions=(revision(shown['history']), revision(shown['tracked'])))
        if roster is not None:
            entry['roster'] = public_roster(roster, (card['player'].get('display_level') or {}).get('value'))
        with self.lock:
            if not view:
                self.entries[login] = entry; self.wanted.discard(login)
            elif name in self.viewed:  # Never resurrected after its viewers left.
                self.views[name] = entry
            self.generation += 1
        self.failures.pop(name, None)
        self.stats['builds'] += 1; self.stats['build_seconds'] += seconds
        self.stats['max_build_seconds'] = max(self.stats['max_build_seconds'], seconds)

    # Presentation ------------------------------------------------------------

    def drop_view(self, key):
        """Called under lock: evict a view and all its presentation variants."""
        self.viewed.pop(key, None);self.views.pop(key, None);self.failures.pop(key, None)
        for cache in (self.presented, self.present_locks):
            for variant in [k for k in cache if isinstance(k, tuple) and k[:3] == key]:del cache[variant]
        self.generation += 1

    def runtime(self, channel=None):
        """Coordinator activity is presentation input: it changes without a database revision."""
        status = self.server.coordinator_status.copy()
        return json.dumps([status if channel is None else status.get(channel),
            sorted(self.server.active_run_ids.copy()) if channel is None else None], sort_keys=True, default=str)

    def present(self, key, build, runtime=''):
        """Serialized body for this publication and runtime, reused for PRESENT_SECONDS; one builder per key."""
        with self.lock:
            if isinstance(key, tuple) and key[0] == 'view' and key[:3] not in self.viewed:raise LookupError('evicted_view')
            lock = self.present_locks.setdefault(key, threading.Lock())
        with lock:
            now = self.clock()
            with self.lock:
                generation = self.generation
                cached = self.presented.get(key)
            if (cached and cached[0] == generation and cached[3] == runtime
                    and timedelta(0) <= now - cached[1] < timedelta(seconds=PRESENT_SECONDS)):
                return cached[2]
            tick = time.perf_counter()
            body = build(now)
            with self.lock:
                if generation == self.generation:
                    self.presented[key] = (generation, now, body, runtime)
            self.stats['presentations'] += 1; self.stats['present_seconds'] += time.perf_counter() - tick
            return body

    def player(self, entry, now):
        card = entry['card']
        value = refresh(entry['public']['player'], now=now, activity=operation(entry['extras']['lifecycle'], self.server.coordinator_status.get(card['channel']), now))
        value = tracked_statistics(value, entry['public']['tracked'], now=now, pace_as_of=datetime.fromisoformat(card['recent_as_of']))
        value['activity'] = public(value['activity'])  # The coordinator's runtime state joins at presentation.
        return value

    def homepage(self):
        def build(now):
            with self.lock:entries = dict(self.entries); heads = list(self.heads); statuses = self.statuses; truncated = self.truncated
            players = []; warming = []
            for head in heads:
                entry = entries.get(head['login'])
                if entry is None:warming.append(head['login']);continue
                card = present_card(dict(entry['card'], player=entry['public']['player']), now=now, active_runs=self.server.active_run_ids.copy(),
                    coordinator_status=self.server.coordinator_status.copy())
                value = tracked_statistics(card['player'], entry['public']['tracked'], now=now,
                    pace_as_of=datetime.fromisoformat(entry['card']['recent_as_of']))
                value['activity'] = public(value['activity'])
                for field in CHARACTER_ONLY:del value[field]
                players.append(value)
            body = dict(players=broadcast(players, statuses, now), served_at=utc(now), truncated=truncated, experimental=True, poll_seconds=2)
            if warming:body['warming'] = warming
            return encode(body)
        return self.present('home', build, self.runtime())

    def characters(self):
        """Compact published rosters only: no inactive card, chart or window builds."""
        def build(now):
            with self.lock:
                rows = [dict(row, channel=head['login']) for head in self.heads
                    if (entry := self.entries.get(head['login'])) for row in entry['roster']]
                warming = [h['login'] for h in self.heads if h['login'] not in self.entries]
                truncated = self.truncated
            return encode(dict(characters=rows, warming=warming, served_at=utc(now), truncated=truncated, poll_seconds=2, experimental=True))
        return self.present('home-characters', build)

    def entry(self, channel):
        with self.lock:return self.entries.get(channel)

    def character(self, channel, known=(None, None), view=None):
        """Serialized character body, or None while the channel has no published entry.

        known: the viewer's (history, tracked) revisions. A section is omitted only when the
        presented entry still has that revision, so the viewer's copy is the published one.
        view: a character ID from this channel's roster; the selected one, or None, is the
        channel entry. Raises LookupError('unknown_character').
        """
        entry = self.entry(channel)
        if entry is None:return None
        if view is not None and view not in {r['id'] for r in entry['roster']}:raise LookupError('unknown_character')
        if view is not None and view != entry['key'][1]:return self.view(channel, view, known, entry)
        held = tuple(k if k == r else None for k, r in zip(known, entry['revisions']))
        def build(now):
            entry = self.entry(channel)
            if entry is None:raise LookupError(channel)
            body = dict(player=broadcast([self.player(entry, now)], self.statuses, now)[0],
                roster=entry['roster'], view=dict(character_id=entry['key'][1], current=True))
            return self.sections(body, entry, held, now)
        # Bounded keys; the held revisions are runtime, so a cached body is only reused for the same ones.
        key = ('character', channel, held[0] is not None, held[1] is not None)
        try:return self.present(key, build, self.runtime(channel) + json.dumps(held))
        except LookupError:return None

    def sections(self, body, entry, held, now):
        if held[1] != entry['revisions'][1]:body['tracked_history'] = entry['public']['tracked']
        if held[0] != entry['revisions'][0]:body['history'] = entry['public']['history']
        return encode(dict(body, history_revision=entry['revisions'][0], tracked_revision=entry['revisions'][1],
            truncated=entry['extras']['truncated'], served_at=utc(now), experimental=True, poll_seconds=2))

    def view(self, channel, character, known, entry):
        """An unselected character's own saved state: no coordinator activity or Twitch status."""
        if character not in {r['id'] for r in entry['roster']}:raise LookupError('unknown_character')
        key = ('view', channel, character)
        with self.lock:
            if key not in self.viewed and len(self.viewed) >= MAX_VIEWS:
                self.drop_view(min(self.viewed, key=self.viewed.get))
            self.viewed[key] = time.monotonic(); found = self.views.get(key)
        if found is None:
            self.wake.set();return None
        held = tuple(k if k == r else None for k, r in zip(known, found['revisions']))
        def build(now):
            with self.lock:found = self.views.get(key); entry = self.entries.get(channel)
            if found is None or entry is None:raise LookupError(channel)
            value = refresh(found['public']['player'], now=now, activity=dict(state='historical_session'))
            value = tracked_statistics(value, found['public']['tracked'], now=now, pace_as_of=datetime.fromisoformat(found['card']['recent_as_of']))
            value.update(activity=public(value['activity']), twitch=dict(status='not_applicable', reason='inactive_character'))
            return self.sections(dict(player=value, roster=entry['roster'], view=dict(character_id=character, current=False)), found, held, now)
        try:return self.present((*key, held[0] is not None, held[1] is not None), build, json.dumps(held))
        except LookupError:return None

    def history(self, channel):
        if self.entry(channel) is None:return None
        def build(now):
            entry = self.entry(channel)
            if entry is None:raise LookupError(channel)
            return encode(dict(entry['public']['tracked'], served_at=utc(now)))
        try:return self.present(('history', channel), build)
        except LookupError:return None
