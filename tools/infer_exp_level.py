"""Conditional EXP-derived levels from an explicit table; never numerical verification."""
import argparse
import hashlib
import json
from pathlib import Path

from exp_tracker.exp_consistency import MODES, infer_levels


def strategies(tesseract,inference):
    """C retains OCR contradictions; D strictly requires two unique agreeing sources."""
    if tesseract is not None and (type(tesseract) is not int or tesseract<1):
        raise ValueError('Expected an existing integer OCR level or None')
    derived=inference['unique_level'] if inference['status']=='unique' else None
    return dict(A=tesseract,B=derived,C=tesseract if tesseract is not None else derived,
                D=tesseract if tesseract is not None and tesseract==derived else None)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requirements',type=Path,required=True)
    parser.add_argument('--exp',type=int,required=True)
    parser.add_argument('--percentage',required=True,help='Exact display value, e.g. 25.17; no percent sign')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.output and args.output.exists():parser.error('Never overwrite saved diagnostic evidence')
    table=json.loads(args.requirements.read_text(encoding='utf-8'))
    requirements={int(k):v for k,v in table['to_next'].items()}
    result=dict(exp=args.exp,percentage=args.percentage,
        requirements_sha256=hashlib.sha256(args.requirements.read_bytes()).hexdigest(),
        table_provenance={k:v for k,v in table.items() if k!='to_next'},
        hypotheses={mode:infer_levels(args.exp,args.percentage,requirements,mode) for mode in MODES})
    serialized=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(serialized,encoding='utf-8')
    else:print(serialized,end='')


if __name__=='__main__':main()
