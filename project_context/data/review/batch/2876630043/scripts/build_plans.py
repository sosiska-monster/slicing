import copy
import sys
import textwrap
from math import ceil, floor

from slicing.render_plan import _read_draft_words, _apply_subtitle_edits, Caption, _output_rect
from common import *
from selection import SELECTED
from layout_options import SOLO, PHONE, GAME, PRODUCT, DIALOG

CHOICES={
 'solo':('SQUARE','Полное лицо, запас сверху и снизу; широкий вариант слишком мелкий, узкий ограничивает жесты.'),
 'phone':('PREVIEW','Верхний общий план сохраняет лицо, кисти и раскрытие. Нижний квадрат отдельно увеличивает рабочую область предпросмотра.'),
 'gameplay':('ACTION','Персонаж и его перемещение помещаются целиком. ZOOM теряет край движения, WIDE уменьшает действие.'),
 'product':('WATCH_PRICE','Товар и точная исходная сумма показаны раздельно, без мелкого текста всей карточки.'),
 'two_equal':('LOW','Сохранена утверждённая геометрия. Нижний источник сдвинут вверх в панели; целостность головы и UI подлежат отдельному контролю.'),
}

def pick(variants,ident):return copy.deepcopy(next(v for v in variants if v['id']==ident))

def original(cid):
    if cid=='05b':return HQ/'data/review/retention_pilot/05b', 'edit_plan_A.json'
    if cid=='17d':return HQ/'data/review/contest/clips/PUB_17d_publish', 'edit_plan.json'
    if cid in ['18a','18b']:return HQ/f'data/review/editorial/{cid}', 'edit_plan.json'
    return HQ/f'data/review/contest/clips/PUB_{cid}', 'edit_plan.json'

def reviewed_source(directory,filename):
    doc=read(directory/filename);cl=doc['clips'][0]
    if cl.get('segments',[{}])[0].get('captions') is not None:
        return doc,cl,None
    dp=directory/cl['subtitle_review']['draft'];ep=directory/cl['subtitle_review']['edits']
    draft,edits=read(dp),read(ep)
    assert sha(dp)==edits['draft_sha256']
    ends=[];total=0
    for s in cl['segments']:total+=s['end_ms']-s['start_ms'];ends.append(total)
    ws=_read_draft_words(draft['words'],ends)
    approved=_apply_subtitle_edits(ws,edits['edits'])
    out=[]
    for item in approved:
        i=next(i for i,e in enumerate(ends) if item.start_ms<e)
        offset=cl['segments'][i]['start_ms']-(0 if i==0 else ends[i-1])
        out.append({'start_ms':item.start_ms+offset,'end_ms':item.end_ms+offset,
                    'text':' '.join(item.lines) if isinstance(item,Caption) else item.text,
                    'source_word_ids':[w['id'] for w in draft['words']
                                       if w['start_ms']>=item.start_ms and w['end_ms']<=item.end_ms]})
    return doc,cl,{'draft':draft,'edits':edits,'draft_sha256':sha(dp),'edits_sha256':sha(ep),'source_items':out}

def wrap(text):
    return textwrap.wrap(text,width=24,break_long_words=False,break_on_hyphens=False)

def phrase_captions(items,lo,hi):
    items=[r for r in items if lo<=r['start_ms']<r['end_ms']<=hi and r['text'].strip()]
    phrases=[];current=[]
    for r in items:
        proposed=' '.join(x['text'] for x in current+[r])
        if current and (len(wrap(proposed))>2 or r['start_ms']-current[-1]['end_ms']>650):
            phrases.append(current);current=[]
        current.append(r)
        if r['text'].endswith(('.','?','!')) and len(' '.join(x['text'] for x in current))>12:
            phrases.append(current);current=[]
    if current:phrases.append(current)
    # Combine short flashes within a source cut when the whole phrase still fits two lines.
    i=0
    while i<len(phrases)-1:
        a,b=phrases[i:i+2];both=' '.join(x['text'] for x in a+b)
        if (a[-1]['end_ms']-a[0]['start_ms']<600 or b[-1]['end_ms']-b[0]['start_ms']<500) and len(wrap(both))<=2:
            phrases[i:i+2]=[a+b]
        else:i+=1
    result=[]
    for i,p in enumerate(phrases):
        start=p[0]['start_ms'];end=p[-1]['end_ms']
        next_start=phrases[i+1][0]['start_ms'] if i+1<len(phrases) else hi
        end=min(hi,next_start-10,max(end,min(start+650,end+180)))
        lines=wrap(' '.join(x['text'] for x in p));assert len(lines)<=2
        result.append({'start_ms':start,'end_ms':end,'lines':lines})
    return [r for r in result if r['end_ms']>r['start_ms']]

def projected_mask(box,p):
    x,y,w,h=box;cx,cy,cw,ch=p['crop'];px,py,pw,ph=p['place']
    l,t=max(x,cx),max(y,cy);r,b=min(x+w,cx+cw),min(y+h,cy+ch)
    if l>=r or t>=b:return None
    left=2*floor((px+(l-cx)*pw/cw)/2);top=2*floor((py+(t-cy)*ph/ch)/2)
    right=2*ceil((px+(r-cx)*pw/cw)/2);bottom=2*ceil((py+(b-cy)*ph/ch)/2)
    return [left,top,right-left,bottom-top]

def layout(cid):
    if cid in ['05b','05c','10c','10d']:
        v=pick(DIALOG,'LOW');family='two_equal'
        if cid=='05b':v['panels']=[{'crop':[1320,300,540,404],'place':[0,0,720,538]},
                                    {'crop':[38,300,540,404],'place':[0,742,720,538]}]
        if cid=='05c':v['panels'].insert(1,{'crop':[820,320,300,80],'place':[48,540,300,80]})
    elif cid=='17d':v=pick(PHONE,'PREVIEW');family='phone'
    elif cid=='18e':v=pick(GAME,'ACTION');family='gameplay'
    elif cid=='18a':
        v=pick(PRODUCT,'WATCH_PRICE');family='product'
        v['panels'][2]={'crop':[952,412,90,24],'place':[300,620,180,48]}
    else:
        v=pick(SOLO,'SQUARE');family='solo'
        if cid in ['18b','18d','19e']:v['panels'][0]['crop'][1]=0
    return family,v

HOOKS={
 '05c':['Что для Макса','2 000 рублей?'],
 '10c':['300 000 —','десяти победителям?'],
 '10d':['Свадьба за','семь миллиардов?'],
 '17c':['Чего не хватает','без стримов?'],
 '17d':['Селфи на','основную камеру?'],
 '17e':['Какой цвет телефона','выбрать?'],
 '18a':['«Недорогой» подарок?'],
 '18b':['3 200 за телефон?'],
 '18d':['А ты бы перематывал','скучное время?'],
 '18e':['Эвелон и эмоция','его героя Dota'],
 '19e':['Перепутали доставку?'],
}

def main():
    save(RUN/'layout_options/choices.json',{'editor':'Sol / current Codex editorial pass','choices':
         {k:{'selected':v[0],'reason':v[1]} for k,v in CHOICES.items()},
         'same_source_frames_for_variants':True,'ui_profiles':'Krumzi estimates',
         'static_policy':'Places and camera crops are fixed within each clip. Empty action slots are masked until their actual source content appears.'})
    index=read(RUN/'index.json')
    for e in index['episodes']:
        cid=e['candidate_id']
        if cid not in SELECTED:continue
        d=RUN/'clips'/cid;d.mkdir(parents=True,exist_ok=True)
        od,filename=original(cid);original_doc,old,review=reviewed_source(od,filename)
        family,v=layout(cid)
        ss=copy.deepcopy(old['segments'])
        if cid=='17c':ss=[ss[-1]]
        if cid=='18b':ss=[ss[0]]
        if cid=='18e':ss=[ss[-1]]
        if cid=='18d':
            ss=[ss[0],ss[-1]]
            ss[0]['end_ms']=11913270
        if cid=='18a':ss=[{'start_ms':11518180,'end_ms':11519750},
                         {'start_ms':11535400,'end_ms':11539400},
                         {'start_ms':11605500,'end_ms':11607600}]
        if cid=='19e':
            start=next(r['start_ms'] for r in review['source_items'] if 'Прикиньте' in r['text'])-100
            ss[0]['start_ms']=start
        new=[]
        ads=original_doc.get('editorial',{}).get('source_ad_rects',[])
        for i,s in enumerate(ss):
            lo,hi=s['start_ms'],s['end_ms']
            framing={'name':family+'_'+v['id'].lower(),'panels':copy.deepcopy(v['panels'])}
            masks=[]
            for ad in ads:
                if ad[0]<700:
                    for p in framing['panels']:
                        m=projected_mask(ad,p)
                        if m:masks.append(m)
            if cid=='05c' and lo>=2978870:masks.append([48,540,300,80])
            if cid=='18a':
                if i==0:masks += [p['place'] for p in framing['panels'][1:]]
                if i==1:
                    framing['panels'][1]['crop']=[760,380,480,600]
                    masks += [p['place'] for p in framing['panels'][1:]]
            if masks:framing['masks']=masks
            if cid=='05b':captions=s['captions']
            elif cid=='18a':captions=[]
            else:captions=phrase_captions(review['source_items'],lo,hi)
            new.append({'start_ms':lo,'end_ms':hi,'framing':framing,'captions':captions})
        if cid!='05b' and cid!='18a':
            lo,hi=new[0]['start_ms'],new[0]['end_ms']
            hook_end=min(hi,lo+(1000 if cid=='17d' else 1500))
            # Opening title replaces whole overlapping speech groups, rather than showing them late.
            keep=[c for c in new[0]['captions'] if c['start_ms']>=hook_end]
            new[0]['captions']=[{'start_ms':lo,'end_ms':hook_end,'lines':HOOKS[cid]}]+keep
        if review:save(d/'saved_review.json',review)
        plan={'schema_version':1,'source':{'vod_id':'2876630043','file':'data/vods/2876630043.mp4'},
              'editorial':{'candidate_id':cid,'hero':'Evelone','source_plan':rel(od/filename),
                            'source_plan_sha256':sha(od/filename),'layout_family':family,
                            'layout_choice':v['id'],'static_layout':True,'caption_mode':'whole phrases',
                            'source_ad_rects':ads,'source_timebase':'HQ playback milliseconds',
                            'caption_timing':'saved HQ words as-is; no 480p shift',
                            'changes':{'17c':'Removed camera-movement introduction; title restores the question, final self-contained explanation retained.',
                                       '19e':'Removed hostile filler about mixed orders; start on personal delivery story.',
                                       '18b':'Ends on finished PC comparison; later open question removed.',
                                       '18a':'New selected phrase windows; local word draft required for complete Hermès line.'}.get(cid,'Reuse approved sound intervals; static image and whole-phrase captions')},
              'clips':[{'id':'BATCH_'+cid,'title':e['title'],'export_size':[1080,1920],
                         'safe_margins':{'left':52/720,'right':156/720,'top':0,'bottom':v['caption_bottom_ref']/1280},
                         'segments':new}]}
        if cid=='18a':
            rec=copy.deepcopy(plan)
            rec['clips'][0]['subtitle_review']={'draft':'word_draft_v2.json','edits':'sol_edits_v2.json'}
            for s in rec['clips'][0]['segments']:s.pop('captions')
            save(d/'recognition_plan.json',rec)
        save(d/'edit_plan.json',plan)
        save(d/'layout.json',v)
        e['stages'].update(layout='selected_from_contacts',plan='complete',subtitles='draft_required' if cid=='18a' else 'saved_review_retimed')
        e['files'].update(plan=rel(d/'edit_plan.json'),layout=rel(d/'layout.json'))
        e['source_intervals_ms']=[[s['start_ms'],s['end_ms']] for s in new]
        e['duration_ms']=sum(s['end_ms']-s['start_ms'] for s in new)
        e.pop('approved_audio_parent',None)
        if cid in ['05c','10c','10d','17d','17e']:
            e['approved_audio_parent']=rel(HQ/f'data/review/mvp/2876630043/PUB_{cid}/PUB_{cid}.mp4')
        if cid=='17d':e['approved_audio_parent']=rel(HQ/'data/review/mvp/2876630043/PUB_17d_publish/PUB_17d_publish.mp4')
        if cid=='05b':e['approved_audio_parent']=rel(HQ/'data/review/mvp/2876630043/RET_05b_A/RET_05b_A.mp4')
        # Selection checkpoint after each completed plan.
        save(RUN/'index.json',index);refresh_index();progress('plan_saved',id=cid,duration=e['duration_ms'],family=family)
    progress('plans_ready')

if __name__=='__main__':main()
