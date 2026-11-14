import sys
from build_plans import projected_mask
from polish import group
from common import *

def main():
    idx=read(RUN/'index.json')
    for cid in ['05b','05c','17e','18a','18d','19e','17d','18e']:
        if len(sys.argv)>1 and cid not in sys.argv[1:]:continue
        e=next(r for r in idx['episodes'] if r['candidate_id']==cid)
        d=RUN/'clips'/cid;p=d/'edit_plan.json';doc=read(p);ss=doc['clips'][0]['segments'];out=output_dir(cid)
        assert sha(out/f'BATCH_{cid}.mp4')==e['mp4_sha256'],'Output changed since this run rendered it'
        if cid=='05b':
            ads=read(HQ/'data/review/contest/clips/PUB_05b/edit_plan.json')['editorial']['source_ad_rects']
            doc['editorial']['source_ad_rects']=ads
            for s in ss:
                s['framing']['masks']=[m for ad in ads for pp in s['framing']['panels'] if (m:=projected_mask(ad,pp))]
        if cid=='05c':
            for i,s in enumerate(ss):
                s['framing']['panels'][1]={'crop':[752,276,420,140],'place':[48,540,300,100]}
                s['framing']['masks']=[m for m in s['framing'].get('masks',[]) if m[0]!=48]
                if i:s['framing'].setdefault('masks',[]).append([48,540,300,100])
        if cid=='17e':
            g=group(read(d/'saved_review.json'),13,22,['Какой цвет: то ли','он будет красный,'])
            ss[1]['captions'].insert(0,{k:g[k] for k in ['start_ms','end_ms','lines']})
        if cid=='18a':
            for s in ss:
                s['framing']['panels'][2]={'crop':[950,412,88,24],'place':[300,620,176,48]}
                s['framing']['masks']=[([300,620,176,48] if m[0]==300 else m) for m in s['framing'].get('masks',[])]
        if cid=='17d':
            for s in ss:s['framing']['panels'][1]['crop']=[240,626,250,250]
        if cid=='18e':
            for s in ss:s['framing']['panels'][1]['crop']=[600,60,900,624]
        if cid in ['18d','19e']:
            a,b,lines=(6,10,['Скипать время —','вы бы скипали?']) if cid=='18d' else (12,16,['Заказываю сладости','и молоко.'])
            g=group(read(d/'saved_review.json'),a,b,lines)
            lo,hi=ss[0]['start_ms'],ss[0]['end_ms']
            if cid=='18d' and hi<g['end_ms']:
                ss[0]['end_ms']=g['end_ms'];hi=g['end_ms']
                wav=d/'joined_hq.wav'
                if wav.exists():wav.rename(d/'joined_hq_before_word_tail_fix.wav')
            assert lo<g['start_ms']<g['end_ms']<=hi
            ss[0]['captions'][0]['end_ms']=min(ss[0]['captions'][0]['end_ms'],g['start_ms']-10)
            ss[0]['captions'].append({k:g[k] for k in ['start_ms','end_ms','lines']})
        for s in ss:
            previous=s['start_ms']
            for cue in s['captions']:
                assert previous<=cue['start_ms']<cue['end_ms']<=s['end_ms'],(cid,cue)
                previous=cue['end_ms']
        save(p,doc)
        progress('refined_render_start',id=cid)
        stage=STAGE/f'data/review/mvp/2876630043/BATCH_{cid}'
        if stage.exists():
            assert stage.resolve().is_relative_to(STAGE.resolve()) and not (stage.lstat().st_file_attributes & 0x400)
            assert not any(stage.iterdir()),'Preserve nonempty staging output'
            stage.rmdir()  # Only our empty staging directory, after its files were published.
        with (d/'render_refined.log').open('w',encoding='utf-8') as log:
            r=subprocess.run([sys.executable,'-B','-u','-X','utf8','-m','slicing','--edit-plan',str(p),'--clip','BATCH_'+cid],
                             cwd=STAGE,env=ENV,stdout=log,stderr=subprocess.STDOUT)
        assert r.returncode==0,(cid,(d/'render_refined.log').read_text('utf-8')[-1000:])
        for name in [f'BATCH_{cid}.mp4',f'BATCH_{cid}.ass','manifest.json']:(stage/name).replace(out/name)
        if e.get('approved_audio_parent'):
            tmp=d/'approved_audio_refined.mp4';mp4=out/f'BATCH_{cid}.mp4'
            command(FF,'-v','error','-nostdin','-n','-i',mp4,'-i',PROJECT/e['approved_audio_parent'],
                    '-map','0:v:0','-map','1:a:0','-c','copy','-movflags','+faststart','-map_metadata','-1',tmp)
            tmp.replace(mp4)
            m=read(out/'manifest.json');m['audio'].update(stream_copy=True,approved_audio_parent=e['approved_audio_parent']);save(out/'manifest.json',m)
        e['mp4_sha256']=sha(out/f'BATCH_{cid}.mp4');e['plan_sha256']=sha(p);e['status']='rendered_pending_visual'
        e['duration_ms']=sum(s['end_ms']-s['start_ms'] for s in ss)
        e['source_intervals_ms']=[[s['start_ms'],s['end_ms']] for s in ss]
        save(RUN/'index.json',idx);refresh_index();progress('refined_render_complete',id=cid)

if __name__=='__main__':main()
