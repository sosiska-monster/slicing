from common import *

def at(ms):
    cs=round(ms/10);s,c=divmod(cs,100);m,s=divmod(s,60);h,m=divmod(m,60)
    return f'{h}:{m:02}:{s:02}.{c:02}'

def main():
    entries=[('17d',0,187,'RENDERED · телефон','Рабочий предпросмотр, раскрытие, финальный вопрос'),
             ('18a',0,230,'RENDERED · товар и цена','Иронически «недорогой» подарок; исходный ценник'),
             ('18e',0,179,'RENDERED · геймплей','Свой персонаж и живая реакция Evelone'),
             ('18b',0,266,'RENDERED · монолог','Телефон по цене игрового ПК'),
             ('05c',0,120,'NEEDS_REVIEW · фрагмент','Голова обрезана; лицо попадает под UI. Krumzi — оценка'),
             ('12g',19700,90,'RESERVE · фрагмент прежнего монтажа','Илья выбирает ответ и выигрывает: герой истории — Илья')]
    paths=[output_dir(cid)/f'BATCH_{cid}.mp4' if cid!='12g' else HQ/'data/review/mvp/2876630043/STATIC_12g_equal/STATIC_12g_equal.mp4'
           for cid,*_ in entries]
    ass='''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,Arial,38,&H00FFFFFF,&H00000000,&H00101824,&H00101824,-1,0,0,0,100,100,0,0,1,2,0,8,36,36,30,1
Style: Sub,Arial,29,&H00FFFFFF,&H00000000,&H00101824,&H00101824,0,0,0,0,100,100,0,0,1,2,0,8,32,32,90,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    start=0;filters=[];chapters=[];inputs=[]
    for i,((cid,lo,n,title,sub),path) in enumerate(zip(entries,paths)):
        length=n/30;end=start+round(length*1000)
        inputs+=['-i',str(path)]
        ui=''
        if cid=='05c':
            ui=(',drawbox=0:0:1080:240:0xFF5FB9@0.25:fill,'
                'drawbox=0:1540:1080:380:0xFF5FB9@0.25:fill,'
                'drawbox=880:780:200:760:0xFF5FB9@0.25:fill,'
                'drawbox=0:1600:1080:320:0x50E6FA@0.20:fill,'
                'drawbox=850:1130:230:470:0x50E6FA@0.20:fill')
        filters.append(f'[{i}:v:0]trim=start={lo/1000:.3f}:duration={length:.9f},setpts=PTS-STARTPTS,fps=30,setsar=1{ui},drawbox=0:0:1080:155:0x0E1830:fill[v{i}]')
        filters.append(f'[{i}:a:0]atrim=start={lo/1000:.3f}:duration={length:.9f},asetpts=PTS-STARTPTS,aresample=48000,apad,atrim=end_sample={n*1600},asetpts=N/SR/TB[a{i}]')
        ass+=f'Dialogue: 5,{at(start)},{at(end)},Title,,0,0,0,,{cid} | {title}\n'
        ass+=f'Dialogue: 5,{at(start)},{at(end)},Sub,,0,0,0,,{sub}\n'
        chapters.append({'candidate_id':cid,'status':'reserve' if cid=='12g' else 'needs_review' if cid=='05c' else 'rendered',
                          'start_ms':start,'end_ms':end,'source':rel(path),'excerpt_start_ms':lo})
        start=end
    (RUN/'overview.ass').write_text(ass,encoding='utf-8')
    joins=''.join(f'[v{i}][a{i}]' for i in range(len(entries)))
    filters.append(joins+f'concat=n={len(entries)}:v=1:a=1[vc][audio]')
    filters.append('[vc]subtitles=overview.ass[video]')
    target=RUN/'BATCH_2876630043_OVERVIEW.mp4'
    if not target.exists():
        command(FF,'-v','error','-nostdin','-n',*inputs,'-filter_complex_threads','2','-filter_complex',';'.join(filters),
                '-map','[video]','-map','[audio]','-c:v','libx264','-preset','fast','-crf','19',
                '-pix_fmt','yuv420p','-r','30','-c:a','aac','-b:a','192k','-movflags','+faststart','-map_metadata','-1',target)
    probe=json.loads(command(FP,'-v','error','-show_streams','-show_format','-of','json',target))
    assert probe['streams'][0]['width']==1080 and probe['streams'][0]['height']==1920
    assert int(probe['streams'][0]['nb_frames'])==sum(x[2] for x in entries)
    command(FF,'-v','error','-nostdin','-xerror','-i',target,'-map','0:v:0','-map','0:a:0','-f','null','-')
    cards=[]
    for requested,actual,im in sample_frames(target,[c['start_ms']+min(900,(c['end_ms']-c['start_ms'])//2) for c in chapters]):
        cards.append(tile(im,tc(requested),360))
    sheet(RUN/'overview_control.png',cards,3)
    data={'file':rel(target),'absolute_path':target.as_posix(),'duration_seconds':float(probe['format']['duration']),
          'chapters':chapters,'full_decode':True,'not_for_publication':True,'sha256':sha(target)}
    save(RUN/'overview.json',data);save(RUN/'overview_probe.json',probe)
    idx=read(RUN/'index.json');idx['overview']=data;idx['status']='complete_with_review';save(RUN/'index.json',idx);refresh_index()
    progress('overview_complete',duration=data['duration_seconds'])

if __name__=='__main__':main()
