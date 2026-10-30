"""Reconcile desired roster settings on the existing scheduler/writer thread."""
from datetime import datetime, timedelta, timezone
import sqlite3

from exp_tracker import streamer_roster as roster
from exp_tracker.store import utc


def policy(row):
    return {k:row[k] for k in ('authorized','tracking_enabled','automatic_characters',*roster.DEFAULTS)}


class Reconciler:
    def __init__(self,store,lanes,build,start,close,activity,active_runs):
        self.store,self.lanes,self.build,self.start,self.close=store,lanes,build,start,close
        self.activity,self.active_runs=activity,active_runs
        self.next_poll=0;self.failed={}

    def __call__(self,running,now):
        if now<self.next_poll:return
        self.next_poll=now+1
        desired={row['channel']:row for row in roster.entries(self.store)}
        waiting={login for login,row in desired.items() if roster.waiting_for_character(self.store,row)}
        for lane in list(self.lanes):
            row=desired.get(lane['channel'])
            binding=self.store.db.execute('''SELECT s.selected_character_id,c.label FROM streamers s
                LEFT JOIN characters c ON c.id=s.selected_character_id WHERE s.login=?''',(lane['channel'],)).fetchone()
            same_owner=bool(binding and lane.get('character_id',binding[0])==binding[0] and lane.get('character',binding[1])==binding[1])
            if row and policy(row)==lane['roster_policy'] and same_owner and lane['channel'] not in waiting:
                lane['paused']=False  # A pause/resume may coalesce while the old capture drains.
                continue  # Visibility does not rotate capture.
            lane['paused']=True
            if lane['channel'] in running:continue
            try:self.close(lane,'roster_change')
            except (OSError,ValueError,sqlite3.Error) as error:
                self.failed[lane['channel']]=dict(revision=row['revision'] if row else lane['roster_revision'],error=str(error))
            self.lanes.remove(lane)
        current={lane['channel']:lane for lane in self.lanes}
        for login,row in desired.items():
            if login in current or not row['tracking_enabled'] or login in waiting or self.failed.get(login,{}).get('revision')==row['revision']:continue
            lane=None
            try:
                roster.validate_policy(self.store,row)  # Recheck ownership risks after in-flight results commit.
                lane=self.build(row)
                lane.update(roster_policy=policy(row),roster_revision=row['revision'])
                self.start(lane)
                self.lanes.append(lane);current[login]=lane
                self.failed.pop(login,None)
            except (OSError,ValueError,sqlite3.Error) as error:
                if lane and lane.get('log'):
                    lane['log'].close();self.active_runs.discard(lane.get('run_id'))
                self.failed[login]=dict(revision=row['revision'],error=str(error))
        with self.store._transaction():
            for login,row in desired.items():
                lane=current.get(login);error=None
                if lane and lane.get('paused'):state='draining'
                elif row['tracking_enabled'] and login in waiting:state='waiting_for_character'
                elif self.failed.get(login,{}).get('revision')==row['revision']:state='error';error=self.failed[login]['error']
                elif not row['tracking_enabled']:state='paused'
                elif lane and lane.get('persistence_failed'):state='error';error='capture persistence failed; review logs and pause/resume'
                else:state=self.activity.get(login,{}).get('state','waiting')
                if state in ('paused','error','waiting_for_character'):
                    self.activity[login]=dict(state='stopped',run_id=lane and lane['run_id'],updated_at=utc(),
                                              reason='roster_paused' if state=='paused' else state)
                self.store.db.execute('''INSERT INTO streamer_runtime VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(streamer_id) DO UPDATE SET revision=excluded.revision,state=excluded.state,
                    run_id=excluded.run_id,error=excluded.error,last_attempt_at=COALESCE(excluded.last_attempt_at,streamer_runtime.last_attempt_at),
                    heartbeat_at=excluded.heartbeat_at WHERE streamer_runtime.revision!=excluded.revision
                    OR streamer_runtime.state!=excluded.state OR streamer_runtime.error IS NOT excluded.error
                    OR streamer_runtime.last_attempt_at IS NOT COALESCE(excluded.last_attempt_at,streamer_runtime.last_attempt_at)
                    OR streamer_runtime.heartbeat_at<?''',
                    (row['streamer_id'],row['revision'],state,lane and lane['run_id'],error,
                     lane and lane.get('last_attempt_at'),utc(),utc(datetime.now(timezone.utc)-timedelta(seconds=5))))
