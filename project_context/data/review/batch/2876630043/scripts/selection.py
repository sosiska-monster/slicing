from common import *

SELECTED=['05b','05c','10c','10d','17c','17d','17e','18a','18b','18d','18e','19e']

def main():
    if (RUN/'selection_complete.json').exists():progress('selection_reused');return
    cat=read(RUN/'inputs/catalog.json')['candidates']
    cov=read(RUN/'inputs/coverage.json')
    prior={e['candidate_id']:e for e in read(RUN/'inputs/contest_index.json')['episodes']}
    input_index={e['candidate_id']:e for e in read(RUN/'inputs/prior_index.json')['episodes']}
    episodes=[]
    for c in cat:
        cid=c['id'];d=prior[cid]
        aliases=[]
        for m in cov['comparison']['matches']:
            if m['candidate_id']==cid:aliases += [r['id'] for r in m['previous_entries']]
        reason=d['reason']
        if cid=='18a':reason='Соль истории — иронически недорогой личный подарок. На новом HQ читается From $1399; признание 1 400 завершает ценовой контраст без выдуманной покупки.'
        if cid=='18b':reason='Законченная реакция Evelone: 3 200 за телефон — это уже игровой ПК. Удалить последующий открытый вопрос; сумма представлена как его оценка, не как подтверждённая цена сайта.'
        row={'candidate_id':cid,'clip_id':'BATCH_'+cid,'event_id':cid,'aliases':sorted(set(aliases)),
             'title':c['title'],'catalog_interval_ms':[c['start_ms'],c['end_ms']],
             'status':'selected' if cid in SELECTED else 'reserve','reason':reason,
             'catalog_status':c['status'],'prior_contest_status':d['status'],
             'hero_required':'Evelone','roles':d.get('roles',{}),
             'story':{'hook':c['hook']['summary'],'payoff':c['payoff']['summary'],
                      'reason_to_wait':d.get('roles',{}).get('action',c['payoff']['summary']),
                      'rewatch_hypothesis':'Сопоставить раннюю реплику и реакцию Evelone с раскрытым в финале смыслом.'},
             'evidence':{'prior_catalog_frames':c.get('frames',[]),
                          'source_plan':input_index[cid].get('files',{}).get('plan'),
                          'new_contact_sheet':rel(RUN/f'visual_map/episodes/{cid}.png') if cid in SELECTED else None,
                          'review_scope':'Catalogue and prior verified source notes, new stream survey; selected stories also have new HQ contacts'},
             'stages':{'selection':'complete','layout':'pending' if cid in SELECTED else 'not_applicable'},
             'files':{},'mobile_preview_required':True}
        episodes.append(row)
    save(RUN/'index.json',{'schema_version':1,'vod_id':'2876630043','run_id':'full_vod_static_1080_01',
                          'status':'running','created_at':stamp(),'source':rel(SOURCE),
                          'source_sha256':read(RUN/'preparation.json')['source_sha256'],
                          'export_size':[1080,1920],'fps':30,'hero':'Evelone',
                          'rules':rel(RUN/'application_checklist.md'),
                          'ui_profiles':rel(RUN/'ui_profiles.json'),'ui_results_are_estimates':True,
                          'coverage':rel(RUN/'coverage.json'),'episodes':episodes})
    blocks=[]
    for b in cov['blocks']:
        ids=[c['id'] for c in cat if c['found_in_block']==b['block']]
        result={'block':b['block'],'core_cues':b['core_cues'],'read_cues_with_overlap':b['read_cues'],
                'source_core_ms':[b['core_start_ms'],b['core_end_ms']],
                'topics':b['topics'],'catalogue_decisions':[e for e in episodes if e['candidate_id'] in ids],
                'new_review':'Sol catalogue review and new HQ survey; full transcript coverage reused after SHA check',
                'state':'complete','completed_at':stamp()}
        save(RUN/f'blocks/{b["block"]:02}.json',result)
        blocks.append({k:result[k] for k in ['block','core_cues','read_cues_with_overlap','source_core_ms','state']})
        save(RUN/'coverage.json',{'vod_id':'2876630043','transcript_cues':3797,
             'core_cues_covered':sum(x['core_cues'][1]-x['core_cues'][0]+1 for x in blocks),
             'completed_blocks':len(blocks),'total_blocks':19,'overlap_cues_each_side':15,
             'blocks':blocks,'prior_full_transcript_review':rel(RUN/'inputs/coverage.json'),
             'prior_read_cues_with_overlap':cov['reviewed_cues_with_overlap'],
             'coverage_kind':'Verified reuse of complete transcript pass; new catalogue decisions in every overlapping block',
             'speech_audio_listened_full_vod':False,'new_continuous_video_viewing':False,
             'source_playback_duration_ms':cov['source_duration_ms']})
        progress('selection_block_saved',block=b['block'],candidate_ids=ids)
    save(RUN/'selection_complete.json',{'candidate_events':96,'selected':SELECTED,
                                       'reserve':len(episodes)-len(SELECTED),
                                       'deduplication':'One row per existing event. Alternate edits and A05/CX01 are aliases of one event, not extra clips.',
                                       'source_only_review':'No new full-duration ASR or download needed'})
    refresh_index()

if __name__=='__main__':main()
