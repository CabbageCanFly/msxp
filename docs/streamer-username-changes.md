# Twitch username changes

Use an explicit operator-reviewed merge, never level/EXP similarity, to associate
an old Twitch username with its current profile. Start tracking the current username
first and wait until its character is recognized. No additional service is needed.

```powershell
.\msxp server streamer merge Streamer_A --into Streamer_B --preview
# If the same verified character exists twice, review the printed IDs and map it explicitly:
.\msxp server streamer merge Streamer_A --into Streamer_B --map-character 12:34 --preview
.\msxp server streamer merge Streamer_A --into Streamer_B --map-character 12:34 --apply --backup private/before-username-merge.sqlite3
```

The default is read-only. Preview reports the affected character IDs; a duplicate
label requires an explicit `--map-character OLD_ID:NEW_ID`. Names, levels and EXP
never authorize a mapping. `--apply` makes a consistent SQLite backup in a new file,
pauses only these two capture lanes, and waits for their current roster revisions
to be acknowledged as paused by the running tracker. It then changes ownership in
one foreign-key-checked transaction and restores the destination's prior tracking
setting. The old username stays paused and disappears from the directory. Failure
before commit rolls back data changes and restores the prior tracking settings.
Keep the backup private; the command never overwrites it. If the tracker is not
running or cannot drain within three minutes, the merge is refused.

Distinct saved characters retain their IDs, sessions, readings, jobs and retained
state under the current profile. Operator audit bound to an old ownership is not
rewritten: such characters require separate review and are refused by this command.

For an explicitly mapped duplicate, this version supports **archived source data**:
no remaining raw diagnostic attempts or trusted observations, a retained checkpoint,
and dated daily points strictly before the destination's first session. The validated
level must not regress. Daily points are copied to the surviving character, keeping
the newest point on a shared UTC date. The original source character, sessions,
checkpoint and audit stay intact as retired evidence. Existing destination raw
readings, tracking state and rate calculations are not combined with an older state
machine; no EXP is invented across the gap. Unexpired or overlapping duplicate
histories are refused for separate review, rather than silently discarded.

The merge records an append-only receipt and explicit character-link mappings.
Old profile, API, daily-history and overlay URLs redirect to the current username;
old mapped character IDs resolve to their surviving IDs. Later username changes
flatten these aliases. Retired usernames cannot be re-enabled accidentally, even
by an older running admin process. Recycled Twitch usernames require an explicit
review of the alias; the tracker does not automatically attach a new account.

The API publisher loads the small alias map during its existing refresh, not on
each OCR read or public poll. A merged profile includes `previous_usernames`; normal
profiles omit it. Both leaderboard modes search these names. A former-name-only
search opens a compact, selectable popup with the matched substring highlighted,
without expanding rows. One popup is shared between results; Escape or clicking
elsewhere dismisses it. A profile history button reveals previous-name information.

Initial deployment needs an API restart to load the new routing/presentation code
and a frontend build. The tracker service does not need restarting: its existing
roster reconciliation drains and resumes the affected lanes. Subsequent supported
merges need neither service restarted. The protected admin portal has no new merge
form; use the command. No schema-version bump or implicit API migration is performed;
the explicit merge installs its own additive metadata/audit tables.

Synthetic tests cover explicit mapping, raw/overlapping evidence rejection,
ownership audit refusal, drain acknowledgement, backup/rollback, unrelated-streamer
isolation, repeated changes, public routing, directory metadata and daily history.
Visual review uses private saved responses and the existing fictional demo fixtures;
it is separate from live tracking verification.
