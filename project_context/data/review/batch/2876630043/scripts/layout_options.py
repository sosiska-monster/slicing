from slicing.render_plan import _output_rect
from common import *

def panel(crop,place):return {'crop':crop,'place':place}
SOLO=[
 {'id':'SQUARE','panels':[panel([104,596,280,280],[40,180,540,540])],'caption_bottom_ref':390},
 {'id':'WIDE','panels':[panel([0,596,504,280],[40,180,540,300])],'caption_bottom_ref':531},
 {'id':'TALL','panels':[panel([142,596,202,260],[40,180,540,696])],'caption_bottom_ref':260},
]
PHONE=[
 {'id':'FULL_PHONE','panels':[panel([0,596,504,280],[40,180,540,300]),panel([270,596,208,280],[48,540,278,374])],'caption_bottom_ref':260},
 {'id':'PREVIEW','panels':[panel([0,596,504,280],[40,180,540,300]),panel([240,630,240,240],[48,540,360,360])],'caption_bottom_ref':260},
 {'id':'WIDE_ONLY','panels':[panel([0,596,504,280],[0,240,720,400])],'caption_bottom_ref':390},
]
GAME=[
 {'id':'ACTION','panels':[panel([0,0,504,280],[40,180,540,300]),panel([640,230,750,520],[48,530,600,416])],'caption_bottom_ref':260},
 {'id':'ZOOM','panels':[panel([0,0,504,280],[40,180,540,300]),panel([800,300,450,450],[48,530,360,360])],'caption_bottom_ref':260},
 {'id':'WIDE','panels':[panel([0,0,504,280],[40,180,540,300]),panel([400,120,1440,800],[0,530,720,400])],'caption_bottom_ref':260},
]
PRODUCT=[
 {'id':'WATCH_PRICE','panels':[panel([0,596,504,280],[40,180,540,300]),
                            panel([510,320,400,500],[48,620,224,280]),panel([952,412,130,24],[300,620,260,48])],'caption_bottom_ref':260},
 {'id':'CARD','panels':[panel([0,596,504,280],[40,180,540,300]),panel([480,310,940,600],[48,600,600,384])],'caption_bottom_ref':260},
 {'id':'WATCH','panels':[panel([0,596,504,280],[40,180,540,300]),panel([510,320,400,500],[48,580,280,350])],'caption_bottom_ref':260},
]
DIALOG=[
 {'id':'HIGH','panels':[panel([1286,40,540,404],[0,0,720,538]),panel([60,200,540,404],[0,742,720,538])],'caption_bottom_ref':531},
 {'id':'MID','panels':[panel([1286,90,540,404],[0,0,720,538]),panel([60,250,540,404],[0,742,720,538])],'caption_bottom_ref':531},
 {'id':'LOW','panels':[panel([1286,140,540,404],[0,0,720,538]),panel([60,300,540,404],[0,742,720,538])],'caption_bottom_ref':531},
]

def composite(im,layout):
    canvas=np.full((1920,1080,3),(14,24,48),np.uint8)
    for p in layout['panels']:
        x,y,w,h=p['crop'];a,b,c,d=_output_rect(p['place'],(1080,1920))
        crop=im[y:y+h,x:x+w]
        assert crop.shape[:2]==(h,w)
        scaled=av.VideoFrame.from_ndarray(crop,format='rgb24').reformat(width=c,height=d,format='rgb24').to_ndarray()
        canvas[b:b+d,a:a+c]=scaled
    return canvas

def guides(im):
    im=im.copy();p=read(RUN/'ui_profiles.json')['platforms']
    for name,col in [('TikTok',(255,95,185)),('Shorts',(80,230,250))]:
        z=p[name]
        for y in [z['top'],1920-z['bottom']]:im[y:y+3,:]=col
        im[z['rail_top']:,1080-z['rail_right']:1080-z['rail_right']+3]=col
    return im

def main():
    datasets=[('solo',SOLO,[11465500,11477000,11483500]),
              ('phone',PHONE,[11273000,11301700,11309800]),
              ('gameplay',GAME,[12169100,12171500,12174700]),
              ('product',PRODUCT,[11605580,11606500,11607300]),
              ('two_equal',DIALOG,[29752000//10,2979600,2984500])]
    data={}
    for name,variants,requests in datasets:
        frames=[(t,im) for t,_,im in sample_frames(INDEXED,requests)]
        cards=[]
        for n,(t,im) in enumerate(frames):
            for v in variants:
                cards.append(tile(guides(composite(im,v)),f'{v["id"]} {tc(t)}',360))
        sheet(RUN/f'layout_options/{name}.png',cards,3)
        data[name]={'variants':variants,'source_frames_ms':requests,'guides':'Saved Krumzi estimates',
                    'sheet':rel(RUN/f'layout_options/{name}.png')}
    save(RUN/'layout_options/options.json',data)
    progress('layout_options_ready',types=list(data))

if __name__=='__main__':main()
