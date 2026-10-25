"""Offline layout-first comparison on saved images; never opens streams or a database.

Includes original-pixel EXP and neural/visual level reads, actual fallback and the
recursive resident child CPU. In-process native APIs are for this research tool only.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime,timezone
from io import BytesIO
import json
from multiprocessing.util import Finalize
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def initialize(python):
    global engines,crop_engine,resident,requirements,ocr_python,native_identity
    from PIL import Image
    import pytesseract
    from exp_tracker.recognition import configure_tesseract,ocr_engine
    from layout_first_hud import LayoutEngine
    from resident_tesseract import NativeTesseract,installation,as_data
    from shadow_capture import ResidentNeural,neural_line
    configure_tesseract();info=installation(pytesseract.pytesseract.tesseract_cmd)
    native_identity=dict(version=info['cli_version'],model_sha256=info['model_sha256'])
    engines=[LayoutEngine(info),LayoutEngine(info)];crop_engine=NativeTesseract(info)
    for engine in (*engines,crop_engine):Finalize(engine,engine.close,exitpriority=0)
    ocr_engine.set(lambda image,psm,whitelist:as_data(crop_engine.tsv('L',image.size,image.tobytes(),psm,whitelist)))
    resident=ResidentNeural();Finalize(resident,resident.close,exitpriority=1);ocr_python=python
    requirements={int(k):v for k,v in json.loads((ROOT/'src/exp_tracker/data/community-exp-v2.json').read_text())['to_next'].items()}
    neural_line(Image.new('RGB',(128,32),'black'),python,30,experimental_neural_level=True,resident=resident)


def cpu_time():
    import psutil
    return time.process_time()+sum(sum(p.cpu_times()[:2]) for p in psutil.Process().children(recursive=True))


def measure(task):
    from PIL import Image
    from exp_tracker.video import Frame
    from layout_first_hud import LayoutLocator
    from shadow_capture import analyze,neural_line
    index,path=task
    with Image.open(path) as source:
        if source.width*source.height>4096*2160:raise ValueError('Frame exceeds pixel limit')
        image=source.convert('RGB')
    buffer=BytesIO();image.save(buffer,'PNG',compress_level=1)
    reader=lambda crop,level:neural_line(crop,ocr_python,30,level,experimental_neural_level=True,resident=resident)
    row=dict(frame=str(path),size=image.size,tesseract=native_identity,variants={})
    for variant in (('baseline','candidate') if index%2 else ('candidate','baseline')):
        locator=LayoutLocator(engines,crop_engine,reader,experimental=True)
        frame=Frame(buffer.getvalue(),0,time.monotonic(),datetime.now(timezone.utc).isoformat())
        start=cpu_time();wall=time.monotonic()
        result=analyze(frame,requirements,locator.read if variant=='candidate' else reader,max_age=600,
            experimental_neural_level=True,**({'locator':locator} if variant=='candidate' else {}))
        row['variants'][variant]=dict(cpu_seconds=cpu_time()-start,wall_seconds=time.monotonic()-wall,
            localization_count=(result.get('localization') or {}).get('count'),
            reading={k:result.get(k) for k in ('candidate','percentage_only_candidate','visual_level','status','neural','neural_level')})
        if variant=='candidate':row['decision']=locator.info
    print(f"{path.name}: {row['decision']['path']} / {row['decision']['reason']}",flush=True)
    return row


def main(argv=None):
    from exp_tracker.msxp import OCR
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('frames',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,required=True,help='new JSON under private/ or artifacts/')
    parser.add_argument('--ocr-python',type=Path,default=OCR)
    parser.add_argument('--workers',type=int,choices=(1,2,3),default=1)
    args=parser.parse_args(argv);output=args.output.resolve()
    if not any(output.is_relative_to(ROOT/name) for name in ('private','artifacts')):
        parser.error('Results must stay under private/ or artifacts/')
    if output.exists():parser.error('Output already exists; choose a new file')
    if not args.ocr_python.is_file() or any(not p.is_file() for p in args.frames):
        parser.error('Existing OCR Python and saved image files required')
    os.environ['OMP_THREAD_LIMIT']='1'
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(args.ocr_python.absolute(),)) as pool:
        rows=list(pool.map(measure,enumerate(args.frames)))
    totals={key:sum(r['variants'][key]['cpu_seconds'] for r in rows) for key in ('baseline','candidate')}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as handle:json.dump(dict(frames=len(rows),cpu_seconds=totals,rows=rows),handle,indent=1)
    print(json.dumps(totals));return 0


if __name__=='__main__':raise SystemExit(main())
