import sys
from common import *

def main():
    idx=read(RUN/'index.json')
    for e in idx['episodes']:
        if e['status'] not in ['selected','rendered_pending_visual','failed']:continue
        cid=e['candidate_id'];clip='BATCH_'+cid;d=RUN/'clips'/cid;p=d/'edit_plan.json';target=output_dir(cid)
        try:
            if target.exists():
                assert read(target/'manifest.json')['edit_plan_sha256']==sha(p),'Existing BATCH output has a different plan; preserve it'
                progress('render_reused',id=cid)
            else:
                progress('render_start',id=cid)
                with (d/'render.log').open('w',encoding='utf-8') as log:
                    c=subprocess.run([sys.executable,'-B','-u','-X','utf8','-m','slicing','--edit-plan',str(p),'--clip',clip],
                                     cwd=STAGE,env=ENV,stdout=log,stderr=subprocess.STDOUT)
                if c.returncode:raise RuntimeError((d/'render.log').read_text('utf-8')[-2500:])
                staged=STAGE/f'data/review/mvp/2876630043/{clip}'
                assert staged.resolve().is_relative_to(STAGE.resolve())
                assert target.resolve()==(HQ/f'data/review/mvp/2876630043/{clip}').resolve()
                assert not (staged.lstat().st_file_attributes & 0x400),'Reparse point in stage'
                target.parent.mkdir(parents=True,exist_ok=True)
                staged.rename(target)
                if e.get('approved_audio_parent'):
                    mp4=target/f'{clip}.mp4';parent=PROJECT/e['approved_audio_parent']
                    tmp=d/'with_approved_audio.mp4'
                    if not tmp.exists():command(FF,'-v','error','-nostdin','-n','-i',mp4,'-i',parent,'-map','0:v:0','-map','1:a:0',
                                               '-c','copy','-map_metadata','-1','-movflags','+faststart',tmp)
                    tmp.replace(mp4)
                    manifest=read(target/'manifest.json');manifest['audio']['approved_audio_parent']=e['approved_audio_parent']
                    manifest['audio']['stream_copy']=True;save(target/'manifest.json',manifest)
            e['files'].update(mp4=rel(target/f'{clip}.mp4'),ass=rel(target/f'{clip}.ass'),manifest=rel(target/'manifest.json'))
            e['stages']['render']='complete';e['status']='rendered_pending_visual'
            e['plan_sha256']=sha(p);e['mp4_sha256']=sha(target/f'{clip}.mp4')
            progress('render_complete',id=cid,bytes=(target/f'{clip}.mp4').stat().st_size)
        except Exception as ex:
            e['status']='failed';e['reason']='Local render failed: '+str(ex)
            save(d/'error.json',{'stage':'render','error':str(ex),'time':stamp()})
            progress('render_failed',id=cid,error=str(ex)[:200])
        save(RUN/'index.json',idx);refresh_index()
    progress('render_batch_complete',counts=refresh_index()['counts'])

if __name__=='__main__':main()
