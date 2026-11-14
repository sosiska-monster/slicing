import re
from math import ceil
from slicing.render_plan import _output_rect,_read_ass_time,load_plan,_join_audio
from slicing.media import Media
from common import *

def intersection(a,b):
    x,y,w,h=a;u,v,s,t=b
    l,top=max(x,u),max(y,v);r,bot=min(x+w,u+s),min(y+h,v+t)
    return max(0,r-l)*max(0,bot-top)

def zones(z):
    return {'top':[0,0,1080,z['top']], 'bottom':[0,1920-z['bottom'],1080,z['bottom']],
            'left_guard':[0,z['top'],z['left'],1920-z['top']-z['bottom']],
            'right_guard':[1080-z['right'],z['top'],z['right'],z['rail_top']-z['top']],
            'button_rail':[1080-z['rail_right'],z['rail_top'],z['rail_right'],1920-z['rail_top']-z['bottom']]}

def bounds(ass,count):
    data=command(FF,'-v','error','-nostdin','-filter_threads','1','-f','lavfi','-i',
                 'color=s=1080x1920:r=30,format=yuv420p,lutyuv=y=128','-vf',
                 f"subtitles={ass.name},lutyuv=y='255*(1-eq(val,128))',bbox=min_val=1,metadata=mode=print:file=-",
                 '-frames:v',count,'-f','null','-',cwd=ass.parent).decode()
    pattern=(r'frame:(\d+)[^\n]*\s+lavfi\.bbox\.x1=(\d+)\s+lavfi\.bbox\.x2=(\d+)'
             r'\s+lavfi\.bbox\.y1=(\d+)\s+lavfi\.bbox\.y2=(\d+)')
    return {f:[x0,y0,x1-x0+1,y1-y0+1] for f,x0,x1,y0,y1 in
            (map(int,m.groups()) for m in re.finditer(pattern,data)) if f<count}

def audio_hash(path,codec):
    return command(FF,'-v','error','-i',path,'-map','0:a:0','-c:a',codec,'-f','hash','-hash','sha256','-').decode().strip()

def draw_guides(im,platform=None):
    im=im.copy();pp=read(RUN/'ui_profiles.json')['platforms']
    for name,c in [('TikTok',(255,95,185)),('Shorts',(80,230,250))]:
        if platform and platform!=name:continue
        z=pp[name]
        for y in [z['top'],1920-z['bottom']]:im[y:y+3,:]=c
        im[z['rail_top']:,1080-z['rail_right']:1080-z['rail_right']+3]=c
    return im

def main():
    idx=read(RUN/'index.json');pp=read(RUN/'ui_profiles.json')['platforms']
    for e in idx['episodes']:
        if e['status'] not in ['rendered_pending_visual','rendered','needs_review']:continue
        cid=e['candidate_id'];d=RUN/'clips'/cid;target=output_dir(cid);mp4=target/f'BATCH_{cid}.mp4';ass=target/f'BATCH_{cid}.ass'
        qpath=d/'qa.json';signature={'plan':sha(d/'edit_plan.json'),'video':sha(mp4),'ass':sha(ass)}
        if qpath.exists() and read(qpath).get('hashes')==signature:
            progress('technical_qa_reused',id=cid);continue
        try:
            probe=json.loads(command(FP,'-v','error','-show_streams','-show_format','-of','json',mp4))
            v=next(s for s in probe['streams'] if s['codec_type']=='video');a=next(s for s in probe['streams'] if s['codec_type']=='audio')
            assert [v['width'],v['height']]==[1080,1920] and v['codec_name']=='h264' and v['avg_frame_rate']=='30/1'
            assert a['codec_name']=='aac' and a['sample_rate']=='48000' and a['channels']==2
            assert abs(float(probe['format']['duration'])-e['duration_ms']/1000)<=1/30
            command(FF,'-v','error','-nostdin','-xerror','-i',mp4,'-map','0:v:0','-map','0:a:0','-f','null','-')
            doc=read(d/'edit_plan.json');ss=doc['clips'][0]['segments'];man=read(target/'manifest.json')
            geometry=[]
            for i,s in enumerate(ss):
                for j,p in enumerate(s['framing']['panels']):
                    rect=_output_rect(p['place'],(1080,1920));crop=p['crop']
                    err=abs((rect[2]/rect[3])/(crop[2]/crop[3])-1)
                    assert err<.003,(cid,rect,crop,err)
                    geometry.append({'segment':i,'panel':j,'crop':crop,'place_px':rect,'aspect_error':err})
                if doc['editorial']['layout_family']=='two_equal':
                    cameras=[r for r in s['framing']['panels'] if r['place'][3]==538]
                    assert len(cameras)==2
                    assert all(_output_rect(p['place'],(1080,1920))[2:]==(1080,808) for p in cameras)
            count=int(v['nb_frames']);events=[];ends=[r['output_end_ms'] for r in man['segments']]
            for line in ass.read_text('utf-8-sig').splitlines():
                if not line.startswith('Dialogue: '):continue
                row=line.split(',',9);start,end=_read_ass_time(row[1])*10,_read_ass_time(row[2])*10
                assert row[9].count(r'\N')<=1 and not '{' in row[9]
                assert not any(start<cut<end for cut in ends[:-1])
                assert 0<=start<end<=e['duration_ms']+5
                events.append({'start_ms':start,'end_ms':end,'text':row[9]})
            boxes=bounds(ass,count);text_checks={}
            for platform,z in pp.items():
                bad=[]
                for n,box in boxes.items():
                    overlap={name:round(100*intersection(box,rect)/(box[2]*box[3]),4) for name,rect in zones(z).items() if intersection(box,rect)}
                    if overlap:bad.append({'frame':n,'time_ms':n*1000//30,'bounds_xywh':box,'elements_percent':overlap})
                text_checks[platform]={'kind':'estimate','frames_with_text':len(boxes),'overlapping_bounds_frames':bad}
            req=sorted(set([0,min(count-1,24),count//2,count-2]+[n for s in man['segments'] for n in
                           [s['video_start_frame'],max(0,s['video_start_frame']-1),(s['video_start_frame']+s['video_end_frame'])//2]]))
            if cid in ['17d','18e']:req=sorted(set(req+list(range(0,count,6))))
            cards=[];key=[];frame_numbers=[];masked_checked=0;mask_failures=[]
            with av.open(str(mp4)) as c:
                for n,f in enumerate(c.decode(video=0)):
                    si=next(i for i,s in enumerate(man['segments']) if s['video_start_frame']<=n<s['video_end_frame'])
                    masks=man['segments'][si].get('masks',[])
                    if n in req or masks:
                        im=f.to_ndarray(format='rgb24')
                        if masks:
                            masked_checked+=1
                            for box in masks:
                                x,y,w,h=box
                                pixels=im[y+3:y+h-3:5,x+3:x+w-3:5]
                                if pixels.size and float(np.abs(pixels.astype(np.int16)-np.array([14,24,48])).mean())>12:
                                    mask_failures.append(n)
                        if n in req:
                            cards.append(tile(draw_guides(im),f'{cid} {tc(n*1000//30)}',320));frame_numbers.append(n)
                        if n in [0,min(count-1,24),count//2,count-2]:
                            png(d/f'frame_{n:04}.png',im)
                            if len(key)<3:key.append((n,im.copy()))
            for page,i in enumerate(range(0,len(cards),12)):
                sheet(d/f'control_{page:02}.png',cards[i:i+12],3)
            for platform in pp:
                sheet(d/f'control_{platform.lower()}.png',[tile(draw_guides(im,platform),f'{cid} {tc(n*1000//30)}',360) for n,im in key],3)
            decoded=command(FF,'-v','error','-i',mp4,'-map','0:a:0','-f','f32le','-c:a','pcm_f32le','-')
            pcm=np.frombuffer(decoded,np.float32).reshape(-1,2)
            sound={'samples_decoded':len(pcm),'peak':float(np.abs(pcm).max()),'rms':float(np.sqrt(np.mean(pcm**2))),
                   'human_listening':False,'aac_sha256':audio_hash(mp4,'copy')}
            assert sound['rms']>1e-5
            if e.get('approved_audio_parent'):
                sound['parent']=e['approved_audio_parent'];sound['same_aac_payload_as_parent']=sound['aac_sha256']==audio_hash(PROJECT/e['approved_audio_parent'],'copy')
                assert sound['same_aac_payload_as_parent']
            else:
                wav=d/'joined_hq.wav'
                if not wav.exists():_join_audio(Media(FF,FP),load_plan(d/'edit_plan.json','BATCH_'+cid,STAGE,Media(FF,FP)),wav)
                b=command(FF,'-v','error','-i',wav,'-f','f32le','-c:a','pcm_f32le','-')
                source_pcm=np.frombuffer(b,np.float32).reshape(-1,2);n=min(len(pcm),len(source_pcm))
                corr=float(np.corrcoef(pcm[:n].reshape(-1),source_pcm[:n].reshape(-1))[0,1]);assert corr>.98
                sound['hq_pcm_correlation_zero_shift']=corr
                sound['seams']=[{'output_ms':end,'jump':float(np.max(np.abs(source_pcm[end*48]-source_pcm[end*48-1])))} for end in ends[:-1]]
            qa={'clip_id':e['clip_id'],'hashes':signature,'full_decode':True,'probe':probe,
                 'geometry':geometry,'caption_events':events,'ass_measured_frame_bounds':boxes,
                 'ui_text':text_checks,'sound':sound,'masked_frames_checked':masked_checked,
                 'mask_pixel_failure_frames':sorted(set(mask_failures)),
                 'prepared_visual_review_frames':frame_numbers,'visual_review':'pending Sol inspection',
                 'ui_profiles':'Krumzi saved organic feed estimates, no mobile measurement'}
            save(qpath,qa);e['files']['qa']=rel(qpath);e['stages']['technical_qa']='complete'
            if mask_failures:progress('mask_inspection_needed',id=cid,count=len(set(mask_failures)))
            progress('technical_qa_passed',id=cid,frames=count,controls=len(frame_numbers),text_ui={k:len(v['overlapping_bounds_frames']) for k,v in text_checks.items()})
        except Exception as ex:
            e['status']='failed';e['reason']='Technical QA failed: '+str(ex)
            save(d/'qa_error.json',{'error':str(ex),'time':stamp()});progress('qa_failed',id=cid,error=str(ex)[:250])
        save(RUN/'index.json',idx);refresh_index()

if __name__=='__main__':main()
