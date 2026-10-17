"""Bounded two-crop transport and untrusted level diagnostics; no tracking state."""

from io import BytesIO
import math
import re
import struct

from PIL import Image

MAX_BYTES = 1024*1024
EXP_SIZE = (1024, 256)
LEVEL_SIZE = (256, 128)
MAX_REQUEST = 2*MAX_BYTES+8


def png_bytes(image, bounds):
    if min(image.size) < 1 or image.width > bounds[0] or image.height > bounds[1]:
        raise ValueError('Crop exceeds dimension limit')
    payload = BytesIO()
    image.save(payload, format='PNG')
    if payload.tell() > MAX_BYTES:
        raise ValueError('Crop exceeds byte limit')
    return payload.getvalue()


def pack(exp, level):
    a = png_bytes(exp, EXP_SIZE)
    b = png_bytes(level, LEVEL_SIZE) if level is not None else b''
    return struct.pack('!I',len(a))+a+struct.pack('!I',len(b))+b


def unpack(payload):
    if len(payload)>MAX_REQUEST:
        raise ValueError('Request exceeds byte limit')
    crops=[]; offset=0
    for i in range(2):
        if offset+4>len(payload):
            raise ValueError('Incomplete request')
        length=struct.unpack('!I',payload[offset:offset+4])[0]; offset+=4
        if length>MAX_BYTES or not i and not length or offset+length>len(payload):
            raise ValueError('Invalid crop length')
        crops.append(payload[offset:offset+length]); offset+=length
    if offset!=len(payload):
        raise ValueError('Unexpected trailing bytes')
    return crops


def load_crop(payload, bounds):
    if not payload or len(payload)>MAX_BYTES:
        raise ValueError('Missing or oversized PNG')
    with Image.open(BytesIO(payload)) as source:
        if source.format!='PNG' or source.width>bounds[0] or source.height>bounds[1]:
            raise ValueError('Invalid crop format/dimensions')
        return source.convert('RGB')


def empty_level(status):
    return dict(status=status,text=None,raw=None,level=None,score=None,
                preprocessing='neutral4',preprocess_seconds=None,inference_seconds=None,
                source_complete=None,trusted=False)


def level_result(raw, inference_seconds, preprocess_seconds):
    from benchmark_rapidocr_levels import numeric_level
    texts, scores = raw.get('txts'), raw.get('scores')
    if (texts is not None and (not isinstance(texts,(list,tuple)) or len(texts)>8
            or any(not isinstance(t,str) or len(t)>160 for t in texts))):
        return empty_level('invalid_response')
    if scores is not None and (not isinstance(scores,(list,tuple)) or len(scores)!=len(texts or [])
            or any(type(s) not in (int,float) or not math.isfinite(s) or not 0<=s<=1 for s in scores)):
        return empty_level('invalid_response')
    text=texts[0] if isinstance(texts,(list,tuple)) and len(texts)==1 else None
    if text is not None and (not isinstance(text,str) or len(text)>160):
        return empty_level('invalid_response')
    level=numeric_level(text)
    status=('numeric_candidate' if level is not None else 'no_output' if not texts or text=='' else
            'ambiguous_output' if text is None else 'invalid_numeric' if re.fullmatch(r'[0-9]+',text.strip()) else 'nonnumeric')
    score=scores[0] if isinstance(scores,(list,tuple)) and len(scores)==1 else None
    if score is not None and (type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=1):
        return empty_level('invalid_response')
    return dict(status=status,text=text,raw=raw,level=level,score=score,
                preprocessing='neutral4',preprocess_seconds=preprocess_seconds,inference_seconds=inference_seconds,
                source_complete=None,trusted=False)


def checked_level(value):
    """Reject inconsistent worker metadata without losing its independent EXP result."""
    if not isinstance(value,dict) or value.get('trusted') is not False or value.get('preprocessing')!='neutral4':
        return empty_level('invalid_response')
    if value.get('status') in ('missing_crop','invalid_crop','failed'):
        return empty_level(value['status']) if value.get('level') is None and value.get('text') is None else empty_level('invalid_response')
    raw=value.get('raw')
    times=[value.get('inference_seconds'),value.get('preprocess_seconds')]
    if not isinstance(raw,dict) or any(type(t) not in (int,float) or not math.isfinite(t) or not 0<=t<=30 for t in times):
        return empty_level('invalid_response')
    expected=level_result(raw,*times)
    if value.get('level') is not None and type(value['level']) is not int:
        return empty_level('invalid_response')
    if any(value.get(key)!=expected[key] for key in ('text','level','score','status')):
        return empty_level('invalid_response')
    return expected
