"""Offline research only: whole-frame layout followed by selective label recognition.

Not wired into capture. Each locator owns one current frame and must have exclusive
use of two LayoutEngine instances plus a separate crop reader until it returns.
"""
import ctypes
import math

from PIL import Image

from adaptive_hud import label,locate_from_tokens
from analyze_temporal_ocr import complete_pair
from benchmark_rapidocr import context_box
from exp_tracker.recognition import _tokens
from exp_tracker.shadow_types import parse_percentage_only
from resident_tesseract import NativeTesseract,MAX_PIXELS,as_data


class LayoutEngine(NativeTesseract):
    def __init__(self,info):
        super().__init__(info)
        pointer,integer=ctypes.c_void_p,ctypes.c_int
        for name,args,result in [
            ('TessBaseAPIAnalyseLayout',[pointer],pointer),
            ('TessBaseAPIRecognize',[pointer,pointer],integer),
            ('TessPageIteratorBoundingBox',[pointer,integer,*([ctypes.POINTER(integer)]*4)],integer),
            ('TessPageIteratorNext',[pointer,integer],integer),
            ('TessPageIteratorBlockType',[pointer],integer),
            ('TessPageIteratorDelete',[pointer],None)]:
            function=getattr(self.lib,name);function.argtypes=args;function.restype=result

    def words(self,image):
        if image.mode!='L' or not 0<image.width*image.height<=MAX_PIXELS:
            raise ValueError('Expected bounded grayscale input')
        lib,api=self.lib,self.api;pixels=image.tobytes()
        if not lib.TessBaseAPISetVariable(api,b'tessedit_char_whitelist',b''):
            raise RuntimeError('Cannot reset label whitelist')
        lib.TessBaseAPISetPageSegMode(api,11)
        lib.TessBaseAPISetImage(api,pixels,image.width,image.height,1,image.width)
        iterator=lib.TessBaseAPIAnalyseLayout(api);boxes=[]
        try:
            if iterator:
                while True:
                    bounds=[ctypes.c_int() for _ in range(4)]
                    # Non-text image blocks can masquerade as whole-frame word boxes.
                    if (1<=lib.TessPageIteratorBlockType(iterator)<=8
                            and lib.TessPageIteratorBoundingBox(iterator,3,*(ctypes.byref(n) for n in bounds))):
                        box=tuple(n.value for n in bounds)
                        if 0<=box[0]<box[2]<=image.width and 0<=box[1]<box[3]<=image.height:boxes.append(box)
                    if not lib.TessPageIteratorNext(iterator,3):break
        finally:
            if iterator:lib.TessPageIteratorDelete(iterator)
        return boxes

    def clear(self):
        self.lib.TessBaseAPIClear(self.api);self.lib.TessBaseAPIClearAdaptiveClassifier(self.api)

    def finish(self):
        # TSV alone sees AnalyseLayout's unrecognized PAGE_RES and can assert in Tesseract 5.4.
        if self.lib.TessBaseAPIRecognize(self.api,None)!=0:
            self.clear();raise RuntimeError('Recognition failed after layout')
        pointer=self.lib.TessBaseAPIGetTsvText(self.api,0)
        try:
            if not pointer:raise RuntimeError('Missing full OCR reply')
            return _tokens(as_data(ctypes.string_at(pointer).decode('utf-8')))
        finally:
            if pointer:self.lib.TessDeleteText(pointer)
            self.clear()


def prepared_pages(image):
    if not 0<image.width*image.height<=4096*2160:raise ValueError('Frame exceeds pixel limit')
    gray=image.convert('L')
    for magnification in (2.,3.):
        scale=min(magnification,math.sqrt(1920*1080*magnification**2/(image.width*image.height)))
        yield gray.resize((round(gray.width*scale),round(gray.height*scale)),Image.Resampling.BICUBIC).point(lambda p:0 if p>160 else 255),scale


def exp_options(words):
    """Loose text-row proposals; keep triples even when the LV label is absent."""
    points=[(a,b,c-a,d-b) for a,b,c,d in words];options={}
    for i,(x,y,w,h) in enumerate(points):
        if h<3 or not .7*h<=w<=13*h:continue
        row=[(j,p) for j,p in enumerate(points) if abs(p[1]-y)<=2.4*h and .6*h<=p[3]<=1.6*h]
        for j,(xx,yy,ww,hh) in row:
            step=xx-x
            if not 5*max(h,hh)<=step<=30*min(h,hh) or abs(yy-y)>.08*step or max(w,ww)>1.3*step:continue
            for k,(ex,ey,ew,eh) in row:
                if not (.75*step<=ex-xx<=1.25*step and abs(ey-y)<=.08*step and ew<=1.3*step):continue
                chosen=options.setdefault(k,set());chosen.update((i,j,k))
                chosen.update(l for l,(lx,ly,lw,lh) in enumerate(points) if 1.5*step<=x-lx<=2.3*step
                    and -.1*step<=ly-y<=.25*step and .5*h<=lh<=3*h)
    return options


def recognize_page(engine,crop_engine,binary):
    words=engine.words(binary);options=exp_options(words)
    if not options or len(options)>240:
        return engine.finish(),dict(fallback=True,reason='proposal_budget',probes=0)
    cache={};tokens=[]
    def probe(index):
        if index not in cache:
            x,y,right,bottom=words[index];height=bottom-y;padding=max(2,round(height*.15))
            box=(max(0,x-padding),max(0,y-padding),min(binary.width,right+padding,x+5*height+padding),min(binary.height,bottom+padding))
            crop=binary.crop(box)
            values=_tokens(as_data(crop_engine.tsv('L',crop.size,crop.tobytes(),7)))
            for token in values:token['x']+=box[0];token['y']+=box[1]
            cache[index]=values;tokens.extend(values)
        return cache[index]
    needed=set()
    try:
        for index in sorted(options):
            if any(label(token)=='EXP' for token in probe(index)):needed.update(options[index])
        for index in sorted(needed):probe(index)
    except (OSError,RuntimeError,ValueError):
        return engine.finish(),dict(fallback=True,reason='crop_failed',probes=len(cache))
    if not any(t['text'].upper().startswith(('HP','MP','EXP')) for t in tokens):
        return engine.finish(),dict(fallback=True,reason='no_labels',probes=len(cache))
    return tokens,dict(fallback=False,reason='selective',probes=len(cache))


def mapped(tokens,scale):
    return [{**token,**{key:token[key]/scale for key in ('x','y','width','height')}} for token in tokens]


class LayoutLocator:
    """A frame-local experiment; no positions, pixels or recognized values survive it."""
    def __init__(self,engines,crop_engine,reader,*,experimental=False):
        if len(engines)!=2 or len({id(e) for e in (*engines,crop_engine)})!=3:
            raise ValueError('Two layout engines and a separate crop engine required')
        self.engines,self.crop_engine,self.reader=engines,crop_engine,reader
        self.experimental=experimental;self.cached=None
        self.info=dict(path='full',reason='not_run',pages=[])

    @staticmethod
    def key(crops):return tuple(None if crop is None else (crop.mode,crop.size,crop.tobytes()) for crop in crops)

    def read(self,*crops):
        if self.cached is not None and self.key(crops)==self.cached[0]:
            _,response=self.cached;self.cached=None;return response
        return self.reader(*crops)

    def full(self,image,reason):
        self.info.update(path='full',reason=reason);self.cached=None
        pages=[previous if previous is not None else mapped(engine.finish(),scale) for engine,scale,previous in self.states]
        return locate_from_tokens(image,pages)

    def __call__(self,image):
        self.cached=None;self.info=dict(path='full',reason='not_run',pages=[])
        self.states=[];pages=[]
        try:
            for engine,(binary,scale) in zip(self.engines,prepared_pages(image)):
                tokens,details=recognize_page(engine,self.crop_engine,binary)
                tokens=mapped(tokens,scale);pages.append(tokens)
                self.states.append((engine,scale,tokens if details['fallback'] else None))
                self.info['pages'].append(details)
            found=locate_from_tokens(image,pages)
            if all(previous is not None for _,_,previous in self.states):
                self.info.update(path='full',reason='page_fallback');return found
            if len(found)!=1 or found[0]['regions']['level'] is None:return self.full(image,'incomplete_or_ambiguous')
            regions=found[0]['regions'];crop=image.crop(context_box(regions['exp'],image.size,2))
            crops=(crop,image.crop(regions['level'].pixels(*image.size))) if self.experimental else (crop,)
            # shortcut: field confirmation is inside localization timing; use total CPU for this experiment.
            try:response=self.reader(*crops)
            except (OSError,RuntimeError,ValueError):return self.full(image,'field_failed')
            text=response.get('text') if isinstance(response,dict) else None
            if complete_pair(text) is None and parse_percentage_only(text) is None:return self.full(image,'imperfect_exp')
            self.cached=(self.key(crops),response);self.info.update(path='selective',reason='confirmed_field')
            return found
        finally:
            for engine in self.engines:engine.clear()
