from build_plans import phrase_captions, reviewed_source, original, HOOKS
from common import *
from slicing.render_plan import _read_draft_words,_apply_subtitle_edits,Caption

CUSTOM={
 '05c':[(18,22,['Это, по сути,','чаевые курьеру.']), (23,26,['Правильно? А, да.'])],
 '17c':[(20,27,['Какую-то хуйню','у вас поспрашивать.']),
        (28,37,['Я сижу, думаю:','у вас спросить...']),
        (38,45,['Вот это или вот это','мнение, знаете, типа...']),
        (46,53,['И просто не стримлю,','не спрашиваю.'])],
 '17e':[(5,11,['Я ещё не смог','определиться с цветом.']),
        (12,22,['Какой цвет: то ли','он будет красный,']),
        (23,27,['то ли бордовый,','то ли через жопу.']),
        (28,33,['И мне пришлось','заказать все три.']),
        (34,38,['Поэтому можете','меня пожалеть.'])],
 '18b':[(3,8,['3 200 за телефон.']), (9,16,['То есть 3 200 —','это прям ПК уже.'])],
 '18d':[(6,10,['Скипать время —','вы бы скипали?']),
        (23,28,['Ну, смотрите, вы бы','скипали часть, например:']),
        (29,34,['либо работу,','либо школу, да, например.']),
        (35,43,['Потом пришлось бы','ещё спать часов 7–8.']),
        (44,55,['Для жизни оставалось,','дай бог, пять часов.'])],
 '19e':[(12,16,['Заказываю сладости','и молоко.']),
        (17,23,['Ну и мне пришло мясо,']),
        (24,30,['какие-то овощи и уголь.']),
        (31,38,['Ну и я подумал:','шашлыки ебану.']),
        (39,43,['Нахуй ссориться,','да, согласны?'])],
}

def group(review,a,b,lines):
    ids={f'w{i:03}' for i in range(a,b+1)}
    rr=[r for r in review['source_items'] if set(r['source_word_ids']) & ids]
    assert rr,(a,b)
    return {'start_ms':min(r['start_ms'] for r in rr),'end_ms':max(r['end_ms'] for r in rr),
            'lines':lines,'source_word_ids':sorted(ids)}

def main():
    for cid in [e['candidate_id'] for e in read(RUN/'index.json')['episodes'] if e['status']=='selected']:
        d=RUN/'clips'/cid;plan=read(d/'edit_plan.json');ss=plan['clips'][0]['segments'];audit=[]
        if cid in CUSTOM:
            review=read(d/'saved_review.json')
            groups=[group(review,a,b,lines) for a,b,lines in CUSTOM[cid]]
            for j,s in enumerate(ss):
                lo,hi=s['start_ms'],s['end_ms']
                if cid=='05c' and j<3:continue
                cues=[]
                hook=s['captions'][0] if j==0 and s['captions'] else None
                for g in groups:
                    if lo<=g['start_ms']<g['end_ms']<=hi:
                        if hook and g['start_ms']<hook['end_ms']:continue
                        cues.append({'start_ms':g['start_ms'],'end_ms':min(hi,g['end_ms']+150),'lines':g['lines']})
                        audit.append(g)
                for a,b in zip(cues,cues[1:]):a['end_ms']=min(a['end_ms'],b['start_ms'])
                s['captions']=([hook] if hook else [])+cues
        if cid=='05b':
            ss[0]['captions'][0]['lines']=['Ведущий спрашивает','правила у чата?']
        if cid=='18a':
            dp=d/'word_draft_v2.json';draft=read(dp)
            edits={'schema_version':1,'editor':'Sol / current Codex editorial review',
                   'draft_sha256':sha(dp),'edits':[
                       {'word_ids':['w008'],'text':''},
                       {'word_ids':['w009'],'text':''},
                       {'word_ids':['w010'],'text':'дешёвый'},
                       {'word_ids':['w015'],'text':'коллаборации'},
                       {'word_ids':['w016'],'text':'с Hermès.'},
                       {'word_ids':['w017'],'text':'Преордер.'},
                       {'word_ids':['w018'],'text':'1 400'},
                   ]}
            save(d/'sol_edits_v2.json',edits)
            ws=_read_draft_words(draft['words'],[1570,5570,7670]);items=_apply_subtitle_edits(ws,edits['edits'])
            out=[]
            for item in items:
                si=next(i for i,e in enumerate([1570,5570,7670]) if item.start_ms<e)
                offset=ss[si]['start_ms']-([0,1570,5570][si])
                out.append({'start_ms':item.start_ms+offset,'end_ms':item.end_ms+offset,
                            'text':' '.join(item.lines) if isinstance(item,Caption) else item.text})
            for s in ss:s['captions']=phrase_captions(out,s['start_ms'],s['end_ms'])
            ss[0]['captions']=[{'start_ms':ss[0]['start_ms'],'end_ms':ss[0]['end_ms'],'lines':HOOKS[cid]}]
            ss[1]['captions']=[{'start_ms':11535910,'end_ms':11536770,'lines':['Дешёвый подарок.']},
                               {'start_ms':11537010,'end_ms':11539200,'lines':['Apple Watch в','коллаборации с Hermès.']}]
            ss[2]['captions']=[{'start_ms':11605590,'end_ms':11607500,'lines':['Преордер.','1 400 — старт.']}]
            plan['editorial']['fresh_review']={'draft':rel(dp),'edits':rel(d/'sol_edits_v2.json'),
                                               'note':'Cut-straddling recognizer noise w008/w009 removed; corrections bound to saved HQ audio IDs.'}
            audit=[{'source_word_ids':['w010','w011'],'text':'Дешёвый подарок.'},
                   {'source_word_ids':['w012','w013','w014','w015','w016'],'text':'Apple Watch в коллаборации с Hermès.'},
                   {'source_word_ids':['w017','w018','w019'],'text':'Преордер. 1 400 — старт.'}]
        for s in ss:
            last=s['start_ms']
            for c in s['captions']:
                assert last<=c['start_ms']<c['end_ms']<=s['end_ms'],(cid,c,s)
                assert 1<=len(c['lines'])<=2
                last=c['end_ms']
        save(d/'phrase_review.json',{'editor':'Sol / current Codex editorial pass','groups':audit,
                                     'policy':'Remove false repetitions and recognizer noise, keep semantic content. Whole phrases; unknown internal word boundaries not invented.'})
        save(d/'edit_plan.json',plan)
        progress('captions_reviewed',id=cid,events=sum(len(s['captions']) for s in ss))
    index=read(RUN/'index.json')
    for e in index['episodes']:
        if e['status']=='selected':
            e['files']['phrase_review']=rel(RUN/f'clips/{e["candidate_id"]}/phrase_review.json')
            e['stages']['subtitles']='reviewed_whole_phrases'
    save(RUN/'index.json',index)

if __name__=='__main__':main()
