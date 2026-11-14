from collections import Counter
from common import *

REVIEW={
 '05b':'При наклоне Максима нижний интерфейс перекрывает часть лица и реакции. На главном плане верх головы Evelone попадает в верхнюю зону UI. Из проверенных статичных кропов 42/16/42 чистый вариант не выбран.',
 '05c':'Нижний постоянный кроп срезает верх головы Максима; при наклоне лицо пересекается с нижним UI. Сумма 2 000 ₽ читается, рекламный переход закрыт, но композиция не проходит выпускной контроль.',
 '10c':'На согласии Максима часть головы обрезана, а лицо и реакция пересекаются с нижним UI. Текст и деньги читаются; требуется доработка исходных кропов внутри фиксированных панелей.',
 '10d':'В статичной раскладке верх головы Evelone заходит под верхний UI, нижний кроп режет голову Максима и пересекает его лицо с нижним интерфейсом. Готовый файл сохранён как образец needs_review.',
}
COPY={
 '05b':('Ведущий забыл свои правила','Эвелон спрашивает правила у чата, а потом вспоминает, кто их составлял.'),
 '05c':('Что для Макса две тысячи рублей?','Эвелон нашёл неожиданное сравнение для ставки в две тысячи рублей.'),
 '10c':('Эвелон предложил поделить выигрыш','Эвелон предлагает распределить выигрыш между десятью победителями. Это разговор из архива, а не действующий розыгрыш.'),
 '10d':('Свадьба за семь миллиардов?','Шутка Эвелона о свадьбе за семь миллиардов и полёте на «Боингах».'),
 '17c':('Чего Эвелону не хватает без стримов','Когда привык спрашивать мнение чата даже вне эфира. Эвелон объясняет, чего ему не хватало.'),
 '17d':('Эвелон показывает предпросмотр камеры','Эвелон раскрывает складной телефон и показывает работающий предпросмотр основной камеры.'),
 '17e':('Не выбрал цвет и заказал все три','Эвелон не смог определиться с цветом телефона и нашёл своё решение.'),
 '18a':('«Недорогой» подарок Эвелона','Эвелон показывает, какой «недорогой» подарок хочет. В архивном кадре — часы с ценником от $1399.'),
 '18b':('Телефон по цене игрового ПК?','Эвелон прикидывает стоимость телефона и сравнивает её с игровым ПК. Сумма в ролике — его оценка.'),
 '18d':('Стоит ли перематывать скучное время?','Перемотать работу и школу? Эвелон посчитал, сколько времени тогда останется на жизнь.'),
 '18e':('Эвелон и эмоция его героя Dota','Эвелон запускает эмоцию своего героя Dota и реагирует на анимацию.'),
 '19e':('Вместо сладостей — набор для шашлыков','Вместо сладостей и молока приехали мясо, овощи и уголь. Эвелон придумал, что с этим делать.'),
}
STORY={
 '05b':('Стоп! Можно ли забрать деньги?', 'Почему ведущий сам сверяется с чатом?', 'Я же правила составлял.',2941570,'Улыбка Максима и ранняя уверенность ведущего приобретают другой смысл.'),
 '05c':('Знаешь, что такое две тысячи рублей?', 'Какое сравнение найдёт Evelone?', 'Чаевые курьеру.',2983040,'Сравнить реакцию Максима до сравнения и после него.'),
 '10c':('Предложение отправить выигрыш зрителям.', 'Сколько победителей и согласится ли Максим?', 'Десять по тридцать тысяч; давай разыграем, только не сейчас.',6786420,'Переслушать, как ведущий формулирует распределение суммы.'),
 '10d':('Свадьба за семь миллиардов.', 'Чем Evelone объяснит абсурдную сумму?', 'Жених и невеста будут лететь на Боингах.',6839680,'Улыбка Evelone и сдержанная реакция Максима.'),
 '17c':('Чего не хватает без стримов?', 'Что он автоматически хочет делать вне эфира?', 'Хочет спросить мнение чата, но не стримит — не спрашивает.',11217180,'Узнать знакомый жест обращения к воображаемому чату.'),
 '17d':('Сразу виден работающий предпросмотр.', 'Как раскрытый аппарат позволяет кадрировать съёмку?', 'Ты сам себя видишь и фоткаешь?',11308980,'Рассмотреть объектив и крепление на реальном экране предпросмотра.'),
 '17e':('Как выбрать цвет телефона?', 'Как разрешится сомнение между оттенками?', 'Пришлось заказать все три; можете меня пожалеть.',11478200,'Услышать, как сравнение красного и бордового ведёт к покупке трёх вариантов.'),
 '18a':('Недорогой подарок?', 'Какой подарок он назовёт дешёвым?', 'Apple Watch Hermès и округлённые 1 400; на карточке From $1399.',11606380,'Сопоставить слово недорогой с реальным ценником и его реакцией.'),
 '18b':('3 200 за телефон?', 'С чем Evelone сравнит такую трату?', 'Это прям ПК уже.',11787820,'Проверить переход от собственной оценки цены к сравнению с ПК.'),
 '18d':('А ты бы перематывал скучное время?', 'Сколько свободного времени останется после работы, школы и сна?', 'Для жизни оставалось, дай бог, пять часов.',11969460,'Повторно прикинуть арифметику и собственный ответ.'),
 '18e':('Анимация героя Dota уже видна.', 'Как отреагирует Evelone?', 'Персонаж продолжает эмоцию, Evelone встаёт и жестикулирует.',12173500,'Сравнить движение персонажа и живую реакцию стримера.'),
 '19e':('Перепутали доставку?', 'Что привезли и что с этим делать?', 'Шашлыки ебану. Нахуй ссориться?',12930490,'Переслушать перечень продуктов, который подготавливает решение.'),
}

def main():
    idx=read(RUN/'index.json');total_frames=total_controls=total_text=total_masks=0
    for e in idx['episodes']:
        cid=e['candidate_id'];e.setdefault('source_intervals_ms',[e['catalog_interval_ms']])
        if e['status']=='reserve':
            e['publication_ready']=False
            e['hero_assessment']='Другой участник или чужой ролик' if any(s in e['reason'] for s in ['Илья','Максим','чужой','чужого']) else 'Evelone, но условия или самостоятельность эпизода не проходят'
            continue
        d=RUN/'clips'/cid;q=read(d/'qa.json');p=read(d/'edit_plan.json')
        assert q['hashes']['video']==sha(output_dir(cid)/f'BATCH_{cid}.mp4')
        assert not q['mask_pixel_failure_frames']
        assert all(not x['overlapping_bounds_frames'] for x in q['ui_text'].values())
        assert (d/'object_checks.json').exists()
        e['status']='needs_review' if cid in REVIEW else 'rendered'
        if cid in REVIEW:e['reason']=REVIEW[cid]
        elif cid in ['17c','17d','17e','18a','18b','18d','18e','19e']:e['reason']='Самостоятельный законченный эпизод Evelone; статичная композиция и важные детали прошли локальный просмотр. Мобильный предпросмотр ещё нужен.'
        e['hero_assessment']='Evelone leads the hook, core statement/action and payoff; other people only support the scene'
        hook,wait,payoff,time,replay=STORY[cid]
        e['story']={'hero':'Evelone','hook':hook,'hook_source_ms':e['source_intervals_ms'][0][0],
                    'reason_to_wait':wait,'payoff':payoff,'payoff_source_ms':time,
                    'rewatch_hypothesis':replay,'retention_measured':False}
        title,description=COPY[cid]
        e['publication']={'state':'local_only','tiktok':{'description':description+'\n\n#evelone twitch: evelone2004',
                         'date':None,'account':None,'url':None,'organic_views':None},
                         'youtube_shorts':{'title':title+' | #evelone twitch: evelone2004',
                         'date':None,'account':None,'url':None,'organic_views':None}}
        e['publication_ready']=False
        e['local_master_accepted']=cid not in REVIEW
        e['duration_seconds']=float(q['probe']['format']['duration'])
        e['files'].update(object_checks=rel(d/'object_checks.json'),controls=rel(d/'control_00.png'),
                          tiktok_controls=rel(d/'control_tiktok.png'),shorts_controls=rel(d/'control_shorts.png'),
                          subtitle_data=rel(d/('word_draft_v2.json' if cid=='18a' else 'saved_review.json')) if cid!='05b' else rel(HQ/'data/review/retention_pilot/05b/source_word_map.json'))
        e['absolute_mp4']=(output_dir(cid)/f'BATCH_{cid}.mp4').as_posix()
        e['stages'].update(technical_qa='complete',visual_review='needs_review' if cid in REVIEW else 'passed_on_control_frames')
        e['review_scope']={'finished_frames_inspected':q['prepared_visual_review_frames'],
                          'full_decode':True,'caption_bounds_all_active_frames':True,'advertisement_masks_all_active_frames':True,
                          'human_listening':False,'mobile_preview':False,'UI':'Krumzi estimate, separately TikTok and Shorts'}
        q['visual_review']={'status':e['stages']['visual_review'],'frames_inspected':q['prepared_visual_review_frames'],
                             'note':REVIEW.get(cid,'Hook, motion/statement, cuts and payoff readable on prepared controls'),
                             'human_listening':False,'mobile_preview':False}
        save(d/'qa.json',q)
        e['plan_sha256']=sha(PROJECT/e['files']['plan']);e['mp4_sha256']=q['hashes']['video']
        mpath=output_dir(cid)/'manifest.json';m=read(mpath);m['batch_run']={'index':rel(RUN/'index.json'),'status':e['status'],
                  'caption_mode':'whole phrases, white outline, no word highlight','ui_estimate':True,'human_listening':False}
        save(mpath,m)
        # Save final selected parameters, including motion-padding refinements, independently of prototype options.
        layout=read(d/'layout.json');layout['final_source_panels_by_segment']=[s['framing']['panels'] for s in p['clips'][0]['segments']]
        save(d/'layout.json',layout)
        total_frames+=int(q['probe']['streams'][0]['nb_frames']);total_controls+=len(q['prepared_visual_review_frames'])
        total_text+=len(q['ass_measured_frame_bounds']);total_masks+=q['masked_frames_checked']
        save(RUN/'index.json',idx);refresh_index();progress('episode_finalized',id=cid,status=e['status'])
    idx['paths_relative_to']=PROJECT.as_posix();idx['status']='complete_pending_overview'
    idx['source_playback_duration_ms']=13367602;idx['coverage_cues']={'covered':3797,'total':3797,'blocks':19,'overlap_each_side':15,'kind':'verified reuse plus new catalogue pass'}
    idx['local_verification']={'decoded_mp4':12,'decoded_frames':total_frames,'finished_control_frames_inspected':total_controls,
                                'measured_text_frames':total_text,'masked_video_frames_checked':total_masks,
                                'human_listening':False,'mobile_preview':False,'ui_profiles':'Krumzi estimates'}
    idx['scene_map']=rel(RUN/'visual_map/scene_map.json');idx['selection']=rel(RUN/'selection_complete.json')
    idx['remaining_editorial_items']=[];idx['next_unfinished']=None
    idx['follow_up_review_ids']=list(REVIEW);idx['code_changed']=False
    idx['source_mtime_ns']=SOURCE.stat().st_mtime_ns
    save(RUN/'index.json',idx);refresh_index()
    progress('decisions_complete',counts=refresh_index()['counts'])

if __name__=='__main__':main()
