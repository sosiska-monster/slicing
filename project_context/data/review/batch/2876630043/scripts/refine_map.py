from common import *

def main():
    p=RUN/'visual_map/refinement.json'
    if not p.exists():
        survey=read(RUN/'visual_map/survey.json')['frames']
        flags=sorted([r for r in survey if r['frame_delta'] is not None],key=lambda r:-r['frame_delta'])
        picked=[]
        for r in flags:
            if all(abs(r['requested_ms']-v)>90000 for v in picked):picked.append(r['requested_ms'])
            if len(picked)==18:break
        duration=read(RUN/'preparation.json')['playback_duration_ms']
        requests=sorted(set(max(0,min(duration-1000,t+d)) for t in picked for d in [-45000,-15000,-2000,0,2000,15000]))
        rows=[];cards=[];page=0
        for target,ms,im in sample_frames(INDEXED,requests):
            cards.append(tile(im,tc(target)))
            rows.append({'requested_ms':target,'actual_ms':ms,'page':page,'cell':len(cards)-1})
            if len(cards)==24 or target==requests[-1]:
                dest=RUN/f'visual_map/refine_{page:02}.png';sheet(dest,cards)
                for r in rows:
                    if r['page']==page:r['sheet']=rel(dest)
                cards=[];page+=1;progress('refine_page',page=page)
        save(p,{'technical_flags':picked,'basis':'largest coarse RGB deltas, hints for Sol inspection only',
                'frames':rows,'complete':True})
    for cid in ['18a','18b']:
        out=RUN/f'visual_map/episodes/{cid}.png'
        if out.exists():continue
        doc=read(HQ/f'data/review/editorial/{cid}/edit_plan.json');ss=doc['clips'][0]['segments']
        req=sorted(set(t for s in ss for t in [s['start_ms']+100,(s['start_ms']+s['end_ms'])//2,s['end_ms']-100]))
        cards=[];rows=[]
        for target,ms,im in sample_frames(INDEXED,req):
            cards.append(tile(im,tc(target),480));rows.append({'requested_ms':target,'actual_ms':ms})
            if cid=='18a' and 11605000<target<11611000:png(RUN/f'visual_map/episodes/watch_{target}.png',im)
        sheet(out,cards,3);save(out.with_suffix('.json'),{'frames':rows})
    progress('refined_map_ready')

if __name__=='__main__':main()
