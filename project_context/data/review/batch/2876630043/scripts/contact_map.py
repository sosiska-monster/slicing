from common import *

def main():
    duration=read(RUN/'preparation.json')['playback_duration_ms']
    p=RUN/'visual_map/survey.json'
    if p.exists() and read(p).get('complete'):
        progress('survey_reused');return
    requests=list(range(0,duration,60000))+[duration-400]
    rows=[];cards=[];previous=None;page=0
    for target,ms,im in sample_frames(INDEXED,requests):
        small=im[::36,::32].astype(np.float32)
        delta=None if previous is None else float(np.abs(small-previous).mean())
        previous=small
        cards.append(tile(im,tc(target)))
        row={'requested_ms':target,'actual_ms':ms,'page':page,'cell':len(cards)-1,'frame_delta':delta}
        rows.append(row)
        if len(cards)==24 or target==requests[-1]:
            dest=RUN/f'visual_map/survey_{page:02}.png';sheet(dest,cards)
            for r in rows:
                if r['page']==page:r['sheet']=rel(dest)
            save(p,{'complete':False,'period_ms':60000,'duration_ms':duration,'frames':rows})
            cards=[];page+=1;progress('survey_page',page=page,frames=len(rows))
    save(p,{'complete':True,'period_ms':60000,'duration_ms':duration,'frames':rows})
    # Contacts at the previous hook/payoff times of the ten potentially suitable stories.
    cat={r['id']:r for r in read(RUN/'inputs/catalog.json')['candidates']}
    chosen=[r for r in read(RUN/'inputs/contest_index.json')['episodes'] if r['status']=='ready']
    for e in chosen:
        cid=e['candidate_id'];out=RUN/'visual_map/episodes'/f'{cid}.png'
        if out.exists():continue
        doc=read(HQ/e['files']['plan']);ss=doc['clips'][0]['segments']
        times=sorted(set([t for s in ss for t in [s['start_ms']+100,(s['start_ms']+s['end_ms'])//2,s['end_ms']-100]]))
        cards=[];points=[]
        for target,ms,im in sample_frames(INDEXED,times):
            cards.append(tile(im,tc(target),480));points.append({'requested_ms':target,'actual_ms':ms})
        sheet(out,cards,3)
        save(out.with_suffix('.json'),{'candidate_id':cid,'frames':points})
        progress('candidate_contacts',id=cid,frames=len(points))
    progress('visual_survey_complete',frames=len(rows),episodes=len(chosen))

if __name__=='__main__':main()
