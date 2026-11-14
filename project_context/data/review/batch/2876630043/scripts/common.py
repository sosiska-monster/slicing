import hashlib
import json
import os
import struct
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path

import av
import numpy as np

RUN = Path(__file__).resolve().parents[1]
PROJECT = RUN.parents[3]
HQ = PROJECT / 'data/review/codex_pilot/full_hq'
SOURCE = HQ / 'data/vods/2876630043.mp4'
STAGE = RUN / '_work/cli_root'
INDEXED = STAGE / 'data/vods/2876630043.mp4'
FF = Path(os.environ['LOCALAPPDATA']) / 'slicing/ffmpeg/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe'
FP = FF.with_name('ffprobe.exe')
ENV = os.environ | {'SLICING_FFMPEG': str(FF), 'PYTHONDONTWRITEBYTECODE':'1',
                    'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','PYTHONIOENCODING':'utf-8'}

def read(p):
    return json.loads(p.read_bytes())

def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    tmp.replace(p)

def stamp():
    return datetime.now(timezone.utc).isoformat()

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024), b''): h.update(b)
    return h.hexdigest()

def rel(p):
    return p.resolve().relative_to(PROJECT).as_posix()

def command(tool, *args, cwd=RUN):
    c=subprocess.run([str(tool), *map(str,args)], cwd=cwd, env=ENV, capture_output=True)
    if c.returncode: raise RuntimeError(c.stderr.decode('utf-8','replace')[-4000:])
    return c.stdout

def progress(stage, **details):
    row={'time':stamp(),'stage':stage,**details}
    with (RUN/'events.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps(row,ensure_ascii=False),flush=True)

def png(p, im):
    p.parent.mkdir(parents=True,exist_ok=True)
    def chunk(k,b):return struct.pack('>I',len(b))+k+b+struct.pack('>I',zlib.crc32(k+b))
    h,w,_=im.shape
    raw=b''.join(b'\0'+r.tobytes() for r in im)
    p.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',w,h,8,2,0,0,0))+
                  chunk(b'IDAT',zlib.compress(raw,4))+chunk(b'IEND',b''))

DIGITS={
 '0':['111','101','101','101','111'],'1':['010','110','010','010','111'],
 '2':['111','001','111','100','111'],'3':['111','001','111','001','111'],
 '4':['101','101','111','001','001'],'5':['111','100','111','001','111'],
 '6':['111','100','111','101','111'],'7':['111','001','010','010','010'],
 '8':['111','101','111','101','111'],'9':['111','101','111','001','111'],
 ':':['000','010','000','010','000'],'.':['000','000','000','000','010'],
 '-':['000','000','111','000','000'],' ':['000']*5,
 'A':['010','101','111','101','101'],'B':['110','101','110','101','110'],
 'C':['111','100','100','100','111'],'D':['110','101','101','101','110'],
 'E':['111','100','110','100','111'],'F':['111','100','110','100','100'],
 'G':['111','100','101','101','111'],'H':['101','101','111','101','101'],
 'I':['111','010','010','010','111'],'J':['001','001','001','101','111'],
 'K':['101','101','110','101','101'],'L':['100','100','100','100','111'],
 'M':['101','111','111','101','101'],'N':['101','111','111','111','101'],
 'O':['111','101','101','101','111'],'P':['111','101','111','100','100'],
 'Q':['111','101','101','111','001'],'R':['110','101','110','101','101'],
 'S':['111','100','111','001','111'],'T':['111','010','010','010','010'],
 'U':['101','101','101','101','111'],'V':['101','101','101','101','010'],
 'W':['101','101','111','111','101'],'X':['101','101','010','101','101'],
 'Y':['101','101','010','010','010'],'Z':['111','001','010','100','111'],
 '/':['001','001','010','100','100']}

def label(im,text,x=7,y=5,scale=2,color=(225,235,255)):
    for char in text.upper():
        for yy,row in enumerate(DIGITS.get(char,DIGITS[' '])):
            for xx,p in enumerate(row):
                if p=='1':im[y+yy*scale:y+(yy+1)*scale,x+xx*scale:x+(xx+1)*scale]=color
        x+=4*scale

def tc(ms):
    s=ms//1000
    return f'{s//3600:02}:{s//60%60:02}:{s%60:02}.{ms%1000:03}'

def tile(im,text,width=320):
    v=av.VideoFrame.from_ndarray(im,format='rgb24').reformat(width=width,height=round(im.shape[0]*width/im.shape[1]),format='rgb24').to_ndarray()
    out=np.zeros((v.shape[0]+24,width,3),np.uint8)
    out[24:]=v; label(out,text)
    return out

def sheet(path,cards,cols=4):
    cards=list(cards)
    cards += [np.zeros_like(cards[0])]*((-len(cards))%cols)
    png(path,np.concatenate([np.concatenate(cards[i:i+cols],axis=1) for i in range(0,len(cards),cols)]))

def sample_frames(path,requests):
    from fractions import Fraction
    with av.open(str(path)) as c:
        s=c.streams.video[0];s.thread_type='AUTO'
        zero=Fraction(c.start_time or 0,1_000_000)
        for target in requests:
            c.seek(int((zero+Fraction(max(0,target),1000))/s.time_base),stream=s,backward=True)
            for f in c.decode(s):
                ms=(f.pts*f.time_base-zero)*1000
                if ms+Fraction(1,2) >= target:
                    yield target,float(ms),f.to_ndarray(format='rgb24')
                    break

def output_dir(cid):
    return HQ/'data/review/mvp/2876630043'/('BATCH_'+cid)

def refresh_index():
    p=RUN/'index.json'
    x=read(p)
    x['updated_at']=stamp()
    from collections import Counter
    x['counts']=dict(Counter(e['status'] for e in x['episodes']))
    for state in ['rendered','reserve','needs_review','failed']:x['counts'].setdefault(state,0)
    x['remaining']=sum(e['status'] not in ['rendered','reserve','needs_review','failed'] for e in x['episodes'])
    save(p,x)
    return x

