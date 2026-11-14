from itertools import groupby
from common import *

def family(ms):
    m=ms//60000
    if m in [4,6,7,8,9,10,11,12,14,15,16,17] or 188<=m<=200 or m in [205,210,211,212,213,215,216,217,218,219,221,222,223]:return 'browser'
    if m==13:return 'game_results'
    if m in [40,42,116,117]:return 'quiz_menu'
    if 38<=m<=178 and m!=41:
        if m in [38,39,43,44,45,49,58,60,65,80,92,98,103,118,120,124,126,132,142,160,161]:return 'quiz_ladder'
        return 'quiz_question'
    if 201<=m<=204:return 'gameplay'
    if m in [206,207,208,209,214,220]:return 'watching_video'
    return 'black_canvas_camera'

def main():
    survey=read(RUN/'visual_map/survey.json')
    samples=[{**r,'sol_scene_family':family(r['requested_ms'])} for r in survey['frames']]
    intervals=[]
    for name,group in groupby(samples,key=lambda r:r['sol_scene_family']):
        rows=list(group);intervals.append({'family':name,'start_ms':rows[0]['requested_ms'],
            'last_observed_ms':rows[-1]['actual_ms'],'next_sample_boundary_ms':min(survey['duration_ms'],rows[-1]['requested_ms']+60000),
            'boundary_precision':'survey bracket, not a frame-exact change point','samples':len(rows)})
    regions={
      'quiz_question':{'Evelone_camera':[1276,68,616,540],'second_camera':[28,72,616,540],
                       'question_answers':[400,700,1160,340],'amount':[824,36,270,100]},
      'quiz_ladder':{'Evelone_camera_approx':[1280,250,616,470],'second_camera_approx':[24,250,616,470],
                     'ladder_approx':[660,70,600,960]},
      'browser':{'late_camera_bottom':[0,596,504,280],'late_camera_top':[0,0,504,280],
                 'rest':'Webpages, third-party video and potential banners; exclude unless the episode needs the product itself'},
      'gameplay':{'Evelone_camera':[0,0,504,280],'selected_action':read(RUN/'clips/18e/edit_plan.json')['clips'][0]['segments'][0]['framing']['panels'][1]['crop']},
      'watching_video':{'Evelone_camera':[0,0,504,280],'external_video':'Not selected as a standalone Evelone story'},
      'black_canvas_camera':{'note':'Camera position and scale vary. Remove moving-camera introduction in 17c; retained interval uses [0,596,504,280].'},
    }
    exact=[]
    for e in read(RUN/'index.json')['episodes']:
        if not e['files'].get('plan'):continue
        doc=read(PROJECT/e['files']['plan'])
        for s in doc['clips'][0]['segments']:
            exact.append({'clip_id':e['clip_id'],'start_ms':s['start_ms'],'end_ms':s['end_ms'],
                          'source_regions':[p['crop'] for p in s['framing']['panels']],
                          'output_places_720x1280':[p['place'] for p in s['framing']['panels']],
                          'masks_720x1280':s['framing'].get('masks',[]),
                          'validation':'Targeted HQ source contacts and finished MP4 controls'})
    save(RUN/'visual_map/scene_map.json',{'vod_id':'2876630043','source_size':[1920,1080],
         'survey_samples':samples,'survey_intervals':intervals,'scene_families':regions,
         'render_validated_intervals':exact,
         'moving_object':{'episode':'17d','whole_camera':[0,596,504,280],
                           'detail_crop':read(RUN/'clips/17d/edit_plan.json')['clips'][0]['segments'][0]['framing']['panels'][1]['crop'],
                           'focus':'Full phone and both hands in upper context view; active preview field in lower detail view',
                           'dense_finished_video_review':'42 prepared frames across 6.23 seconds, including every 0.2 second and cuts'},
         'third_person_layout':'No selected story with three visible participants. Third phone-call voice in quiz does not imply a third camera.',
         'scope':'Whole-duration sparse visual survey, extra contacts around RGB changes, detailed checks only in selected source ranges. No claim of continuous full-VOD visual/audio viewing.'})
    coverage=read(RUN/'coverage.json')
    coverage['new_visual_survey_frames']=len(samples)
    coverage['new_transition_hint_frames']=len(read(RUN/'visual_map/refinement.json')['frames'])
    coverage['new_candidate_source_frames']=sum(len(read(p)['frames']) for p in (RUN/'visual_map/episodes').glob('*.json'))
    coverage['visual_map']=rel(RUN/'visual_map/scene_map.json')
    coverage['new_survey_and_transition_sheets_inspected_by_sol']=15
    save(RUN/'coverage.json',coverage)
    progress('scene_map_saved',survey=len(samples),exact_render_intervals=len(exact))

if __name__=='__main__':main()
