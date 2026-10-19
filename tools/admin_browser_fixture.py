"""Synthetic-only servers for tools/admin.browser.mjs; never opens an existing DB."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading

from exp_tracker.admin_server import AdminServer
from exp_tracker.diagnostics import Diagnostics
from exp_tracker.exp_requirements import requirement
from exp_tracker.server import create_server
from exp_tracker.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    path = args.output.resolve()/'synthetic.sqlite3'
    if path.exists():parser.error('synthetic database already exists; choose a new output directory')
    start = datetime.now(timezone.utc)-timedelta(minutes=10)
    with Store(path) as store:
        store.add_channel('alpha'); cid = store.add_character('alpha', 'Tricia')
        store.add_character('alpha', 'Other')
        store.add_channel('beta'); foreign = store.add_character('beta', 'Beta')
        store.select_character('beta', foreign, at=start)
        store.select_character('alpha', cid, at=start)
        d = Diagnostics(store)
        stamps = {}
        for run, offset in [('old', 0), ('live', 200)]:
            sid = store.start_session('alpha', at=start+timedelta(seconds=offset))
            d.begin(run, 'alpha', dict(type='configuration', trusted=False, interval=20, count=4, source_kind='file'))
            stamps[run] = []
            for i in range(1, 5):
                stamp = (start+timedelta(seconds=offset+i*20)).isoformat(); stamps[run].append(stamp)
                bp = 3300+i*10; exp = bp*requirement(50)['to_next']//10000; pct = f'{bp//100}.{bp%100:02}'
                d.append(run, dict(type='attempt', trusted=False, index=i, attempted_at=stamp, received_at=stamp, current=True,
                    source=dict(kind='file', channel=None), status='diagnostic_pair', candidate=[exp,float(pct)],
                    neural=dict(text=f'{exp}[{pct}%]'), visual_level=50, visual_status='available',
                    neural_level=dict(status='numeric_candidate', level=50, text='50', score=.99),
                    localization=dict(count=1), frame_sha256=f'{offset+i:064x}'))
            if run == 'old':
                old_session = sid
                store.end_session('alpha', at=start+timedelta(seconds=100))
    with AdminServer(path, 0) as admin, create_server(path, port=0, public_only=True, background=True) as public:
        public.quiet = True
        threading.Thread(target=public.serve_forever, daemon=True).start()
        print(json.dumps(dict(admin=admin.origin, public=f'http://127.0.0.1:{public.server_port}',
                              cid=cid, session=sid, old_session=old_session, stamps=stamps)), flush=True)
        try:
            admin.serve_forever()
        finally:
            public.shutdown()


if __name__ == '__main__':
    main()
