"""Private browser-test server: immutable saved replay + explicitly synthetic window control.

No OCR, network capture, HTTP writes or source retiming. stdin accepts only 'advance'.
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from exp_tracker.store import Store
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.server import create_server


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--directory',type=Path,required=True)
    cli.add_argument('--port',type=int,required=True)
    args=cli.parse_args()
    directory=args.directory.resolve()
    if not any(directory.is_relative_to(Path(p).resolve()) for p in ('private','artifacts')):
        raise ValueError('Private test directory required')
    database=directory/'updates.sqlite3'
    if database.exists():raise ValueError('Never overwrite an existing database')
    logs={channel:Path('private/local-alpha/runs')/run/'capture.jsonl' for channel,run in (
        ('telfer1','telfer1-20261017T214539Z-620539d6'),('shiphtur','shiphtur-20261017T214659Z-eba94e1c'))}
    saved={c:[json.loads(s) for s in p.read_text().splitlines()] for c,p in logs.items()}
    now=datetime.now(timezone.utc)
    with Store(database) as store:
        d=Diagnostics(store)
        for channel in (*logs,'synthetic_window'):
            store.add_channel(channel);cid=store.add_character(channel,'Synthetic window test' if channel=='synthetic_window' else 'Saved review')
            store.select_character(channel,cid);store.start_session(channel)
        for channel,records in saved.items():
            d.begin(records[0]['run_id'],channel,records[0])
            for record in records[1:]:
                if record['type']=='attempt' and record['index']<=(3 if channel=='telfer1' else 40):d.append(records[0]['run_id'],record)
        d.begin('synthetic-window','synthetic_window',dict(type='configuration',trusted=False,interval=15,source_kind='file'))
        def synthetic(index):
            # Test-generated historical timestamps, not a capture throughput/accuracy claim.
            stamp=(now-timedelta(seconds=5+15*(21-index))).isoformat()
            pct=f'{(6750+index)//100}.{(6750+index)%100:02}'
            return dict(type='attempt',trusted=False,index=index,current=True,attempted_at=stamp,received_at=stamp,
                source=dict(kind='file',channel=None),status='diagnostic_percentage_only',localization=dict(count=1),
                neural=dict(text=f'[{pct}%]'),visual_level=65,visual_status='available',
                neural_level=dict(status='numeric_candidate',text='65',level=65,score=.99,preprocessing='neutral4'))
        for i in range(1,20):d.append('synthetic-window',synthetic(i))
        with create_server(database,port=args.port,diagnostic_dashboard=True) as http:
            http.quiet=True
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            print(json.dumps(dict(ready=True,port=http.server_port)),flush=True)
            advanced=False
            try:
                for command in sys.stdin:
                    if command.strip()!='advance' or advanced:raise ValueError('One bounded advance only')
                    for channel,records in saved.items():
                        for record in records[1:]:
                            if record['type']=='attempt' and record['index']>(3 if channel=='telfer1' else 40):d.append(records[0]['run_id'],record)
                        d.append(records[0]['run_id'],records[-1])
                    for i in (20,21):d.append('synthetic-window',synthetic(i))
                    assert not store.db.execute('SELECT 1 FROM observations').fetchone()
                    advanced=True;print(json.dumps(dict(advanced=True)),flush=True)
            finally:
                http.shutdown();thread.join(timeout=2)


if __name__=='__main__':main()
