from fractions import Fraction
from faster_whisper import WhisperModel
from faster_whisper.utils import download_model
from slicing.render_plan import _output_rect
from check_batch import intersection,zones
from common import *

def overlaps(box,profile):
    return {name:round(100*intersection(box,z)/(box[2]*box[3]),3) for name,z in zones(profile).items() if intersection(box,z)}

def white_box(im):
    mask=(im.min(2)>200)&(im.max(2).astype(int)-im.min(2).astype(int)<45)
    rows=np.flatnonzero(mask.sum(1)>max(15,im.shape[1]//12))
    if len(rows)<10:return None
    runs=np.split(rows,np.flatnonzero(np.diff(rows)>1)+1);rr=max(runs,key=len)
    if len(rr)<10:return None
    cols=np.flatnonzero(mask[rr].sum(0)>max(10,len(rr)//10))
    if len(cols)<10:return None
    return [int(cols.min()),int(rr.min()),int(cols.max()-cols.min()+1),int(rr.max()-rr.min()+1)]

def main():
    idx=read(RUN/'index.json');profiles=read(RUN/'ui_profiles.json')['platforms']
    summary=read(RUN/'evidence_summary.json')['geometry'] if (RUN/'evidence_summary.json').exists() else []
    for e in idx['episodes']:
        if e['status']!='rendered_pending_visual':continue
        cid=e['candidate_id'];d=RUN/'clips'/cid;plan=read(d/'edit_plan.json');ss=plan['clips'][0]['segments']
        out=output_dir(cid);man=read(out/'manifest.json');q=read(d/'qa.json');n=int(q['probe']['streams'][0]['nb_frames'])
        sample_ns=[0,n//2,max(0,n-10)];actual={}
        with av.open(str(out/f'BATCH_{cid}.mp4')) as c:
            for i,f in enumerate(c.decode(video=0)):
                if i in sample_ns:actual[i]=f.to_ndarray(format='rgb24')
        comparisons=[]
        for fn,im in actual.items():
            si=next(i for i,s in enumerate(man['segments']) if s['video_start_frame']<=fn<s['video_end_frame'])
            s=man['segments'][si];target=s['source_start_ms']+round((fn-s['video_start_frame'])*1000/30)
            candidates=[(ms,pix) for _,ms,pix in sample_frames(INDEXED,[target-30,target,target+30])]
            for pi,p in enumerate(ss[si]['framing']['panels']):
                x,y,w,h=_output_rect(p['place'],(1080,1920));cx,cy,cw,ch=p['crop']
                xs=np.r_[np.arange(2,w-2,max(5,w//25)),0,1,w-2,w-1]
                ys=np.r_[np.arange(2,h-2,max(5,h//25)),0,1,h-2,h-1]
                gx,gy=np.meshgrid(xs+x,ys+y);visible=np.ones(gx.shape,bool)
                for xx,yy,ww,hh in s.get('masks',[]):visible &= ~((gx>=xx)&(gx<xx+ww)&(gy>=yy)&(gy<yy+hh))
                tb=q['ass_measured_frame_bounds'].get(str(fn))
                if tb:
                    xx,yy,ww,hh=tb;visible &= ~((gx>=xx)&(gx<xx+ww)&(gy>=yy)&(gy<yy+hh))
                if visible.sum()<10:continue
                values=[]
                for ms,src in candidates:
                    crop=src[cy:cy+ch,cx:cx+cw]
                    expected=av.VideoFrame.from_ndarray(crop,format='rgb24').reformat(width=w,height=h,format='rgb24').to_ndarray()
                    diff=np.abs(im[np.ix_(y+ys,x+xs)].astype(np.int16)-expected[np.ix_(ys,xs)].astype(np.int16)).mean(2)
                    values.append((float(diff[visible].mean()),ms))
                best=min(values);comparisons.append({'frame':fn,'panel':pi,'mae':best[0],'source_frame_ms':best[1]})
        assert max(r['mae'] for r in comparisons)<24,(cid,comparisons)
        objects=[]
        family=plan['editorial']['layout_family']
        if family=='two_equal':
            head_boxes=([1370,380,330,300],[140,350,340,300]) if cid=='05b' else ([1390,200,350,340],[160,250,350,300])
            cameras=[p for p in ss[0]['framing']['panels'] if p['place'][3]==538]
            for who,box,p in zip(['Evelone head','Maxim head'],head_boxes,cameras):
                x,y,w,h=p['crop'];px,py,pw,ph=_output_rect(p['place'],(1080,1920));bx,by,bw,bh=box
                projected=[round(px+(bx-x)*pw/w),round(py+(by-y)*ph/h),round(bw*pw/w),round(bh*ph/h)]
                loss=100*(1-intersection(box,p['crop'])/(bw*bh))
                objects.append({'object':who,'basis':'conservative manually estimated head envelope, checked against controls',
                                'source_box_xywh':box,'projected_xywh':projected,'crop_loss_percent':round(loss,3),
                                'interval_ms':[0,e['duration_ms']],
                                'platform_ui_percent':{k:overlaps(projected,z) for k,z in profiles.items()}})
        else:
            main=_output_rect(ss[0]['framing']['panels'][0]['place'],(1080,1920))
            objects.append({'object':'whole camera containing Evelone face and relevant gestures','output_xywh':main,
                            'interval_ms':[0,e['duration_ms']], 'platform_ui_percent':{k:overlaps(main,z) for k,z in profiles.items()}})
            if family=='gameplay':objects.append({'object':'active Dota character envelope','output_xywh':[200,796,600,584],
                                                   'basis':'manual control-frame envelope; background may lie beneath UI',
                                                   'platform_ui_percent':{k:overlaps([200,796,600,584],z) for k,z in profiles.items()},
                                                   'note':'Evelone stands up near the end; forehead leaves the original webcam, not introduced by crop.'})
            if family=='product':
                for pi,name in [(1,'watch product'),(2,'actual From $1399 label')]:
                    box=_output_rect(ss[-1]['framing']['panels'][pi]['place'],(1080,1920))
                    objects.append({'object':name,'output_xywh':box,'interval_ms':[5570,7670],
                                    'platform_ui_percent':{k:overlaps(box,z) for k,z in profiles.items()}})
        if cid=='17d':
            track=[]
            with av.open(str(out/'BATCH_17d.mp4')) as c:
                for fn,f in enumerate(c.decode(video=0)):
                    im=f.to_ndarray(format='rgb24');box=white_box(im[810:1350,72:612])
                    if box:
                        box[0]+=72;box[1]+=810
                        track.append({'frame':fn,'time_ms':fn*1000//30,'visible_white_preview_xywh':box,
                                      'platform_ui_percent':{k:overlaps(box,z) for k,z in profiles.items()},
                                      'subtitle_bbox_overlap_area':intersection(box,q['ass_measured_frame_bounds'].get(str(fn),[0,0,1,1]))})
            required=[r for r in track if r['frame']<30 or r['frame']>=139]
            assert len(required)>=70 and all(not any(r['platform_ui_percent'].values()) for r in required)
            assert all(r['subtitle_bbox_overlap_area']==0 for r in required)
            save(d/'phone_motion_check.json',{'checked_decoded_frames':n,'method':'bright neutral display field; upper full-camera context also retained',
                                             'source_detail_crop':[240,626,250,250],'track':track,'required_hook_and_final_detected_frames':len(required),
                                             'ui_estimate_only':True})
            objects.append({'object':'active white phone preview field','per_frame_track':rel(d/'phone_motion_check.json'),
                            'intervals_ms':[[0,1000],[4640,6230]],'ui_intersections_in_required_frames':0})
        save(d/'object_checks.json',{'profiles':'Saved Krumzi estimates','objects':objects,'camera_pixel_comparisons':comparisons,
                                     'actual_checked_frames':sample_ns,'not_a_mobile_preview':True})
        summary=[r for r in summary if r['id']!=cid]+[{'id':cid,'comparisons':len(comparisons),'max_pixel_mae':max(r['mae'] for r in comparisons)}]
        progress('object_geometry_evidence_saved',id=cid,comparisons=len(comparisons))
    # Source/codec data and corrected wording are already saved; this ASR only checks new joined audio continuity.
    model=WhisperModel(download_model('base',local_files_only=True,use_auth_token=False),device='cpu',compute_type='int8',cpu_threads=8)
    for cid in ['17c','18a','18b','18d','18e','19e']:
        p=RUN/f'clips/{cid}/speech_check.json'
        if p.exists():continue
        segments,_=model.transcribe(str(output_dir(cid)/f'BATCH_{cid}.mp4'),language='ru',beam_size=5,
                                    word_timestamps=True,vad_filter=False,condition_on_previous_text=False)
        rows=[{'start':s.start,'end':s.end,'text':s.text} for s in segments]
        save(p,{'scope':'Only selected final clip audio, not full VOD','rows':rows,'human_listening':False,
                'timing_used_for_render':False,'model':'cached Whisper base int8'})
        progress('speech_continuity_checked',id=cid,text=' '.join(r['text'] for r in rows))
    save(RUN/'evidence_summary.json',{'geometry':summary,'code_unchanged':all(sha(PROJECT/p)==h for p,h in read(RUN/'preparation.json')['input_hashes'].items() if Path(p).parts[0]=='src'),
                                      'human_listening':False,'mobile_preview':False})

if __name__=='__main__':main()
