from slicing.render_plan import _join_audio,load_plan
from slicing.media import Media
from common import *

def main():
    cid='18d';d=RUN/'clips'/cid;out=output_dir(cid);media=Media(FF,FP)
    wav=d/'joined_hq.wav'
    if not wav.exists():_join_audio(media,load_plan(d/'edit_plan.json','BATCH_18d',STAGE,media),wav)
    tmp=d/'new_audio.mp4'
    if not tmp.exists():command(FF,'-v','error','-nostdin','-n','-i',out/'BATCH_18d.mp4','-i',wav,
                               '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k',
                               '-movflags','+faststart','-map_metadata','-1',tmp)
    tmp.replace(out/'BATCH_18d.mp4')
    m=read(out/'manifest.json');m['audio']={'speech':'original','music':None,'note':'New selected HQ audio join for shortened 18d; no parent audio copied'}
    save(out/'manifest.json',m)
    idx=read(RUN/'index.json');e=next(e for e in idx['episodes'] if e['candidate_id']==cid)
    e.pop('approved_audio_parent',None);e['status']='rendered_pending_visual';e['mp4_sha256']=sha(out/'BATCH_18d.mp4')
    e['reason']='Самостоятельный вопрос Evelone о перемотке времени и завершённый расчёт: на жизнь останется пять часов.'
    save(RUN/'index.json',idx);refresh_index();progress('audio_18d_rebuilt_from_hq')

if __name__=='__main__':main()
