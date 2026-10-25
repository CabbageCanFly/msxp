"""Experimental visual HUD worker in the existing OCR environment; no values are read here."""
import json
import math
import struct
import sys
import time

import cv2
import numpy as np

cv2.setNumThreads(1)
MAX_BYTES=32*1024*1024
MAX_PIXELS=4096*2160
MAX_BOXES=256


def meter_rows(image):
    height,width=image.shape[:2];scale=min(1.,960/width)
    small=cv2.resize(image,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
    edge=cv2.convertScaleAbs(cv2.Sobel(gray,cv2.CV_16S,0,1,ksize=1))
    binary=np.uint8(edge>15)*255
    lines=cv2.morphologyEx(binary,cv2.MORPH_OPEN,np.ones((1,18),np.uint8))
    segments=[];by_row={}
    for y,line in enumerate(lines):
        changes=np.flatnonzero(np.diff(np.r_[0,line>0,0]))
        row=[(int(a),y,int(b-a),1) for a,b in zip(changes[::2],changes[1::2]) if 18<=b-a<=220]
        segments.extend(row);by_row[y]=row
    prefix=np.pad(np.cumsum(binary>0,axis=1,dtype=np.int32),((0,0),(1,0)))
    found=[]
    for x,y,w,h in segments:
        for xx,yy,ww,hh in by_row[y]:
            step=xx-x
            if not (.85*w<=step<=1.3*w and .8*w<=ww<=1.2*w):continue
            if not any(abs(s[0]-xx-step)<=.08*step and .8*w<=s[2]<=1.3*w for s in by_row[y]):continue
            scores=np.min([((prefix[:,min(small.shape[1],round(x+(i+.85)*step))]-
                prefix[:,round(x+(i+.15)*step)])/(round(x+(i+.85)*step)-round(x+(i+.15)*step))) for i in range(3)],axis=0)
            scores=np.maximum.reduce([scores,np.r_[scores[0],scores[:-1]],np.r_[scores[1:],scores[-1]]])
            score=0.
            for bh in range(max(3,round(.06*step)),max(4,round(.22*step))):
                tops=np.arange(max(0,y-round(.22*step)),min(small.shape[0]-bh,y+round(.1*step)+1))
                if len(tops):score=max(score,float(np.minimum(scores[tops],scores[tops+bh]).max()))
            if score<.65:continue
            candidate=dict(x=x/scale,y=y/scale,step=step/scale)
            if any(abs(candidate['step']-p['step'])<.1*min(candidate['step'],p['step']) and
                abs(candidate['y']-p['y'])<.25*candidate['step'] and abs(candidate['x']-p['x'])<.2*candidate['step'] for p in found):continue
            found.append(candidate)
    return found


def text_rows(image):
    from collections import defaultdict
    height,width=image.shape[:2];scale=min(1.,960/width)
    small=cv2.resize(image,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    low=small.min(axis=2);high=small.max(axis=2)
    white=np.uint8((low>135)&((high.astype(np.int16)-low)<85))*255
    joined=cv2.morphologyEx(white,cv2.MORPH_CLOSE,np.ones((1,2),np.uint8))
    points=[]
    for binary in (white,joined):
        _,_,stats,_=cv2.connectedComponentsWithStats(binary,8)
        points.extend(tuple(map(int,s[:4])) for s in stats[1:] if 2<=s[3]<=64 and .2*s[3]<=s[2]<=14*s[3] and s[4]>=3)
    points=list(dict.fromkeys(points));buckets=defaultdict(list)
    for p in points:buckets[p[1]//3].append(p)
    found=[]
    for x,y,w,h in points:
        row=[p for n in range(y//3-1,y//3+2) for p in buckets[n] if .4*h<=p[3]<=2.5*h]
        levels=[p for n in range(y//3-3,y//3+4) for p in buckets[n] if .3*h<=p[3]<=3*h]
        for xx,yy,ww,hh in row:
            step=xx-x
            if not 5*max(h,hh)<=step<=small.shape[1]/3 or abs(yy-y)>.08*step:continue
            exps=[p for p in row if abs(p[0]-xx-step)<=.08*step and abs(p[1]-y)<=.08*step]
            if not exps:continue
            lv=any(abs(p[0]-(x-1.9*step))<=.12*step and -.08*step<=p[1]-y<=.18*step for p in levels)
            three=any(all(.08*step<=p[2]<=.30*step and .05*step<=p[3]<=.15*step
                for p in ((x,y,w,h),(xx,yy,ww,hh),exp)) for exp in exps)
            if not lv and not three:continue
            candidate=dict(x=x/scale,y=y/scale,step=step/scale)
            if any(abs(candidate['step']-p['step'])<.1*min(candidate['step'],p['step']) and
                abs(candidate['y']-p['y'])<.25*candidate['step'] and abs(candidate['x']-p['x'])<.2*candidate['step'] for p in found):continue
            found.append(candidate)
    return found


def label_score(gray,proposal,models,*,meter=False):
    step=proposal['step'];x=proposal['x']+2*step;y=proposal['y'];best=0.
    box=(max(0,math.floor(x-.15*step)),max(0,math.floor(y-(.4 if meter else .15)*step)),
        min(gray.shape[1],math.ceil(x+.55*step)),min(gray.shape[0],math.ceil(y+.3*step)))
    query=gray[box[1]:box[3],box[0]:box[2]]
    for template,reference in models:
        for adjustment in (.9,1.,1.1):
            scale=step/reference*adjustment
            size=(max(2,round(template.shape[1]*scale)),max(2,round(template.shape[0]*scale)))
            if size[0]>query.shape[1] or size[1]>query.shape[0]:continue
            resized=cv2.resize(template,size,interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_CUBIC)
            if resized.std()<5:continue
            best=max(best,float(cv2.minMaxLoc(cv2.matchTemplate(query,resized,cv2.TM_CCOEFF_NORMED))[1]))
    return best


def boxes_for(rows,size):
    width,height=size
    return list(dict.fromkeys((max(0,math.floor(p['x']-2.6*p['step'])),max(0,math.floor(p['y']-.5*p['step'])),
        min(width,math.ceil(p['x']+3.6*p['step'])),min(height,math.ceil(p['y']+.6*p['step']))) for p in rows))


class Detector:
    def __init__(self):self.models=[]

    def learn(self,image,box,step):
        height,width=image.shape[:2]
        if (not isinstance(box,list) or len(box)!=4 or any(type(n) is not int for n in box)
                or not 0<=box[0]<box[2]<=width or not 0<=box[1]<box[3]<=height
                or (box[2]-box[0])*(box[3]-box[1])>65536 or type(step) not in (float,int)
                or not math.isfinite(step) or not 5<=step<=width):raise ValueError('Invalid label calibration')
        pixels=cv2.cvtColor(image[box[1]:box[3],box[0]:box[2]],cv2.COLOR_BGR2GRAY)
        _,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(pixels>180)*255,8)
        components=[i+1 for i,s in enumerate(stats[1:]) if s[2]>=2 and s[3]>=3]
        ys,xs=np.where(np.isin(labels,components))
        if not len(xs):return
        pixels=pixels[ys.min():ys.max()+1,xs.min():xs.max()+1].copy()
        if pixels.std()<5:return
        # Keep representative label shapes rather than a new model for each compression/scale variation.
        if any(float(cv2.matchTemplate(p,cv2.resize(pixels,(p.shape[1],p.shape[0])),
                cv2.TM_CCOEFF_NORMED)[0,0])>=.9 for p,_ in self.models):return
        self.models.append((pixels,float(step)));self.models=self.models[-8:]

    def detect(self,image):
        height,width=image.shape[:2]
        if not self.models:return dict(full=True,reason='untrained',boxes=[])
        meters=meter_rows(image)
        if not meters:return dict(full=True,reason='no_meters',boxes=[])
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        if not any(label_score(gray,p,self.models,meter=True)>=.65 for p in meters):
            return dict(full=True,reason='unknown_label_style',boxes=[])
        boxes=boxes_for(meters,(width,height))
        if len(boxes)>MAX_BOXES:return dict(full=True,reason='too_many_regions',boxes=[])
        covered=np.zeros((height,width),np.uint8)
        for x0,y0,x1,y1 in boxes:covered[y0:y1,x0:x1]=1
        if np.count_nonzero(covered)>=.7*width*height:return dict(full=True,reason='broad_mask',boxes=[])
        for p in text_rows(image):
            x,y=p['x']+2*p['step'],p['y']+.05*p['step']
            if 0<=x<width and 0<=y<height and covered[int(y),int(x)]:continue
            if label_score(gray,p,self.models)>=.65:
                return dict(full=True,reason='unexplained_label',boxes=[])
        return dict(full=False,reason='matched',boxes=boxes)


def decode(payload):
    metadata,separator,png=payload.partition(b'\n')
    if not separator or len(metadata)>4096 or not 24<=len(png)<=MAX_BYTES or png[:16]!=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
        raise ValueError('Invalid visual request')
    width,height=struct.unpack('!II',png[16:24])
    if not 0<width<=4096 or not 0<height<=2160 or width*height>MAX_PIXELS:raise ValueError('Frame exceeds limits')
    metadata=json.loads(metadata)
    if not isinstance(metadata,dict) or metadata.get('op') not in ('detect','learn'):raise ValueError('Invalid operation')
    image=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
    if image is None or image.shape[:2]!=(height,width):raise ValueError('Invalid PNG')
    return metadata,image


def main():
    if sys.argv[1:]==['--check']:
        print(json.dumps(dict(opencv=cv2.__version__,numpy=np.__version__)));return
    if sys.argv[1:]!=['--serve']:raise SystemExit('Use --serve or --check')
    detector=Detector();stream=sys.stdin.buffer
    while header:=stream.read(4):
        if len(header)!=4:raise ValueError('Incomplete header')
        length=struct.unpack('!I',header)[0]
        if not 0<length<=MAX_BYTES+4097:raise ValueError('Request exceeds limit')
        payload=stream.read(length)
        if len(payload)!=length:raise ValueError('Incomplete request')
        started=time.process_time();metadata,image=decode(payload)
        if metadata['op']=='learn':
            detector.learn(image,metadata.get('box'),metadata.get('step'));result=dict(trained=True)
        else:result=detector.detect(image)
        result.update(version=1,size=[image.shape[1],image.shape[0]],cpu_seconds=time.process_time()-started)
        encoded=json.dumps(result,allow_nan=False)
        if len(encoded)>65536:raise ValueError('Response exceeds limit')
        print(encoded,flush=True)


if __name__=='__main__':main()
