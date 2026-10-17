"""Strict parsing of the fixed two-pass, four-sheet human transcription format."""
from decimal import Decimal
import re


NUMBER=r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)'


def parse_answers(text):
    pages={};stage=0;sheet=None
    for line_number,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line or line=='---':
            continue
        if match:=re.fullmatch(r'pass ([12])',line):
            number=int(match[1])
            if number!=stage+1 or stage and (sheet!=4 or len(pages[stage,4])!=6):
                raise ValueError(f'Unexpected pass header at line {line_number}')
            stage=number;sheet=None
            continue
        if match:=re.fullmatch(r'review-0([1-4])\.png',line):
            number=int(match[1])
            if not stage or number!=(sheet or 0)+1 or sheet and len(pages[stage,sheet])!=6:
                raise ValueError(f'Unexpected sheet header at line {line_number}')
            sheet=number;pages[stage,sheet]=[]
            continue
        pattern=rf'lvl ([1-9][0-9]{{0,2}});\s*({NUMBER})'+(r';\s*([0-9]{1,2}\.[0-9]{2})%' if stage==2 else '')
        match=re.fullmatch(pattern,line)
        if sheet is None or match is None or len(pages[stage,sheet])>=6:
            raise ValueError(f'Unclear answer or mapping at line {line_number}: {line!r}')
        level,exp=int(match[1]),int(match[2].replace(',',''))
        percent=match[3] if stage==2 else None
        if level>300 or exp>2**63-1 or percent is not None and not Decimal(0)<=Decimal(percent)<Decimal(100):
            raise ValueError(f'Out-of-range answer at line {line_number}')
        pages[stage,sheet].append(dict(level=level,current_exp=exp,percentage=percent,
            raw_line=line,line_number=line_number))
    if stage!=2 or set(pages)!={(s,p) for s in (1,2) for p in range(1,5)} or any(len(v)!=6 for v in pages.values()):
        raise ValueError('Expected two complete passes, each with four six-answer sheets')
    readings=[]
    for sheet in range(1,5):
        for row,(first,second) in enumerate(zip(pages[1,sheet],pages[2,sheet]),1):
            if any(first[k]!=second[k] for k in ('level','current_exp')):
                raise ValueError(f'Passes disagree at sheet {sheet}, row {row}; do not repair')
            readings.append(dict(id=f'H{len(readings)+1:02d}',sheet=f'review-{sheet:02d}.png',row=row,
                level=first['level'],current_exp=first['current_exp'],percentage=second['percentage'],
                pass1=first,pass2=second))
    return readings
