"""Whole-frame layout followed by selective label recognition and retained-page fallback.

Live native engines run only inside the existing timeout-controlled workers.
"""
import ctypes
import math
import re

from PIL import Image

from adaptive_hud import label,locate_from_tokens
from benchmark_rapidocr import context_box
from exp_tracker.recognition import _tokens
from exp_tracker.shadow_grammar import interpret_exp
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


def recover_exp_label(tokens,binary,engine):
    """Verify a missing label in pixels, using three already-read HUD anchors."""
    boxes=[]
    for hp in tokens:
        if label(hp)!='HP':continue
        for mp in tokens:
            if label(mp)!='MP':continue
            step=mp['x']-hp['x']
            if step<5*max(hp['height'],mp['height']) or abs(mp['y']-hp['y'])>.08*step:continue
            if not any(re.fullmatch(r'LV[.:]?',lv['text'],re.I)
                    and 1.6*step<=hp['x']-lv['x']<=2.2*step
                    and -.04*step<=lv['y']-hp['y']<=.15*step for lv in tokens):continue
            if any(label(t)=='EXP' and .8*step<=t['x']-mp['x']<=1.2*step
                    and abs(t['y']-hp['y'])<=.08*step for t in tokens):continue
            box=(math.floor(hp['x']+1.97*step),math.floor(hp['y']-.03*step),
                 math.ceil(hp['x']+2.28*step),math.ceil(hp['y']+.15*step))
            if box not in boxes and 0<=box[0]<box[2]<=binary.width and 0<=box[1]<box[3]<=binary.height:
                boxes.append(box)
                if len(boxes)>8:return tokens,0
    extra=[]
    for box in boxes:
        crop=binary.crop(box)
        # A standalone label can need word segmentation, as orange level badges do.
        for psm in (7,8):
            found=[t for t in _tokens(as_data(engine.tsv('L',crop.size,crop.tobytes(),psm)))
                   if label(t)=='EXP' and t['confidence']>=.4]
            if found:
                extra.extend({**t,'x':t['x']+box[0],'y':t['y']+box[1]} for t in found)
                break
    return tokens+extra,len(boxes)


def confirmed_field(response):
    """Ask the existing grammar for one complete field; never rewrite its raw evidence."""
    text=response.get('text') if isinstance(response,dict) else None
    if not isinstance(text,str):return False
    parsed=interpret_exp(text,source_complete=response.get('source_complete'))
    if parsed['strict_full'] is not None or parsed['strict_percentage_only'] is not None:return True
    if response.get('source_complete') is False:return False
    full=parsed['full_exp']
    if full['classification']=='unique_proposal' and len(full['proposals'])==1:
        proposal=full['proposals'][0]
        if proposal.get('required_context'):return False
        edits=proposal['edits']
        # These two existing repairs need independent arithmetic/context, not just text.
        return not any(e['category']=='ungrouped_exp_opener' or
            e['category']=='exp_digit' and e['index']==0 and e['old'] in ('S','B') for e in edits)
    percentage=parsed['percentage']
    # A percentage alone cannot prove that an accompanying absolute EXP field is complete.
    return bool(percentage['classification']=='unique_proposal' and len(percentage['proposals'])==1
        and not percentage['proposals'][0].get('required_context')
        and percentage['proposals'][0]['field_span'][0]==(1 if text.startswith('P[') else 0))


class LayoutPages:
    """Two retained full-frame pages, exclusively held until confirmation or fallback."""
    def __init__(self,engines,crop_engine):
        if len(engines)!=2 or len({id(e) for e in (*engines,crop_engine)})!=3:
            raise ValueError('Two layout engines and a separate crop engine required')
        self.engines,self.crop_engine=engines,crop_engine
        self.states=[];self.image=None

    def start(self,image):
        self.states=[];self.image=image;pages=[];details=[];original=[]
        prepared=list(prepared_pages(image))
        for engine,(binary,scale) in zip(self.engines,prepared):
            tokens,detail=recognize_page(engine,self.crop_engine,binary)
            original.append(tokens);pages.append(mapped(tokens,scale));details.append(detail)
        # Preserve successful or competing geometry before trying to recover a missing HUD.
        if not locate_from_tokens(image,pages):
            for index,((binary,scale),tokens) in enumerate(zip(prepared,original)):
                tokens,retries=recover_exp_label(tokens,binary,self.crop_engine)
                if retries:details[index]['anchor_label_retries']=retries
                original[index]=tokens
                pages[index]=mapped(tokens,scale)
        for engine,(_,scale),tokens,detail in zip(self.engines,prepared,original,details):
            self.states.append((engine,scale,tokens if detail['fallback'] else None))
        return pages,details

    def full(self):
        if len(self.states)!=2:raise RuntimeError('No retained layout pages')
        original=[previous if previous is not None else engine.finish() for engine,_,previous in self.states]
        pages=[mapped(tokens,scale) for tokens,(_,scale,_) in zip(original,self.states)]
        # Full OCR can find the three anchors that selective probes missed.
        if not locate_from_tokens(self.image,pages):
            for index,((binary,scale),tokens) in enumerate(zip(prepared_pages(self.image),original)):
                tokens,_=recover_exp_label(tokens,binary,self.crop_engine)
                pages[index]=mapped(tokens,scale)
        return pages

    def clear(self):
        for engine in self.engines:engine.clear()
        self.states=[];self.image=None


class LayoutLocator:
    """A frame-local locator; no positions, pixels or readings survive the next call."""
    def __init__(self,engines,crop_engine,reader,*,experimental=False,pages=None):
        self.pages=pages if pages is not None else LayoutPages(engines,crop_engine)
        self.reader=reader
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
        return locate_from_tokens(image,self.pages.full())

    def __call__(self,image):
        self.cached=None;self.info=dict(path='full',reason='not_run',pages=[])
        try:
            pages,details=self.pages.start(image);self.info['pages']=details
            found=locate_from_tokens(image,pages)
            if all(detail['fallback'] for detail in details):
                self.info.update(path='full',reason='page_fallback');return found
            if len(found)!=1 or found[0]['regions']['level'] is None:return self.full(image,'incomplete_or_ambiguous')
            regions=found[0]['regions'];crop=image.crop(context_box(regions['exp'],image.size,2))
            crops=(crop,image.crop(regions['level'].pixels(*image.size))) if self.experimental else (crop,)
            # Confirmation is included in localization timing; compare total recognition time.
            try:response=self.reader(*crops)
            except (OSError,RuntimeError,ValueError):return self.full(image,'field_failed')
            if not confirmed_field(response):return self.full(image,'imperfect_exp')
            self.cached=(self.key(crops),response);self.info.update(path='selective',reason='confirmed_field')
            return found
        finally:
            self.pages.clear()
