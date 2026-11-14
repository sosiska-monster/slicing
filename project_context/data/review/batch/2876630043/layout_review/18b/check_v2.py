"""Local, read-only media checks; reports stay in this review directory."""
import json
from pathlib import Path
import re
import subprocess
import sys

import av
import numpy as np

PROJECT = Path(__file__).resolve().parents[6]
REVIEW = Path(__file__).resolve().parent
RUN = PROJECT / 'data/review/batch/2876630043'
HQ = PROJECT / 'data/review/codex_pilot/full_hq'
sys.path[:0] = [str(PROJECT / 'src'), str(RUN / 'scripts')]
from common import FF, FP, read, save, sha, png, sample_frames, tile, sheet, label
from slicing.render_plan import _output_rect


def command(*args, cwd=REVIEW):
    result = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace'))
    return result.stdout


def intersection(a, b):
    x, y, w, h = a
    u, v, s, t = b
    return max(0, min(x+w, u+s)-max(x, u)) * max(0, min(y+h, v+t)-max(y, v))


def zones(p):
    return {'top': [0, 0, 1080, p['top']],
            'bottom': [0, 1920-p['bottom'], 1080, p['bottom']],
            'left_guard': [0, p['top'], p['left'], 1920-p['top']-p['bottom']],
            'upper_right_guard': [1080-p['right'], p['top'], p['right'], p['rail_top']-p['top']],
            'buttons': [1080-p['rail_right'], p['rail_top'], p['rail_right'], 1920-p['rail_top']-p['bottom']]}


def overlaps(box, p):
    return {name: round(100*intersection(box, rect)/(box[2]*box[3]), 5)
            for name, rect in zones(p).items() if intersection(box, rect)}


def guide(im):
    im = im.copy()
    for name, color in [('TikTok', (255, 95, 185)), ('Shorts', (80, 230, 250))]:
        p = read(RUN / 'ui_profiles.json')['platforms'][name]
        for y in (p['top'], 1920-p['bottom']):
            im[y:y+3] = color
        for x in (p['left'], 1080-p['right']):
            im[p['top']:p['rail_top'], x:x+3] = color
        x = 1080-p['rail_right']
        im[p['rail_top']:1920-p['bottom'], x:x+3] = color
    return im


def text_bounds(ass, count):
    text = command(FF, '-v', 'error', '-nostdin', '-filter_threads', '1', '-f', 'lavfi', '-i',
                   'color=s=1080x1920:r=30,format=yuv420p,lutyuv=y=128', '-vf',
                   f"subtitles={ass.name},lutyuv=y='255*(1-eq(val,128))',bbox=min_val=1,metadata=mode=print:file=-",
                   '-frames:v', count, '-f', 'null', '-', cwd=ass.parent).decode()
    pattern = (r'frame:(\d+)[^\n]*\s+lavfi\.bbox\.x1=(\d+)\s+lavfi\.bbox\.x2=(\d+)'
               r'\s+lavfi\.bbox\.y1=(\d+)\s+lavfi\.bbox\.y2=(\d+)')
    return {n: [x, y, r-x+1, b-y+1] for n, x, r, y, b in
            (map(int, match.groups()) for match in re.finditer(pattern, text)) if n < count}


def payload(path):
    packets = read_json_command(FP, '-v', 'error', '-select_streams', 'a:0', '-show_packets',
                               '-show_data_hash', 'sha256', '-show_entries',
                               'packet=pts,dts,duration,size,data_hash,side_data_list', '-of', 'json', path)['packets']
    return packets


def read_json_command(*args):
    return json.loads(command(*args))


def active_bounds(im, y0=200, y1=1160):
    # Exclude the overview title and original caption band. Report a 2px compression tolerance.
    diff = np.max(np.abs(im[y0:y1].astype(np.int16)-np.array([14, 24, 48])), axis=2)
    ys, xs = np.where(diff > 18)
    return [int(xs.min()), int(ys.min()+y0), int(xs.max()-xs.min()+1), int(ys.max()-ys.min()+1)]


def main():
    old_entry = read(REVIEW / 'input_snapshot.json')['episode']
    master = PROJECT / old_entry['files']['mp4']
    target = HQ / 'data/review/mvp/2876630043/BATCH_18b_v2'
    video = target / 'BATCH_18b_v2.mp4'
    ass = target / 'BATCH_18b_v2.ass'
    probe = read_json_command(FP, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', video)
    save(REVIEW / 'ffprobe.json', probe)
    v = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    a = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
    assert [v['width'], v['height']] == [1080, 1920]
    assert v['codec_name'] == 'h264' and v['avg_frame_rate'] == '30/1'
    assert v['sample_aspect_ratio'] == '1:1' and v['display_aspect_ratio'] == '9:16'
    assert a['codec_name'] == 'aac' and a['sample_rate'] == '48000' and a['channels'] == 2
    assert abs(float(probe['format']['duration']) - 8.88) < 0.00001
    count = int(v['nb_frames'])
    assert count == 266
    command(FF, '-v', 'error', '-nostdin', '-xerror', '-i', video,
            '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-')
    old_packets, new_packets = payload(master), payload(video)
    assert old_packets == new_packets, 'AAC packets, time stamps or padding changed'
    old_pcm = command(FF, '-v', 'error', '-i', master, '-map', '0:a:0', '-c:a', 'pcm_f32le', '-f', 'f32le', '-')
    new_pcm = command(FF, '-v', 'error', '-i', video, '-map', '0:a:0', '-c:a', 'pcm_f32le', '-f', 'f32le', '-')
    assert old_pcm == new_pcm, 'Decoded audio changed'
    old_probe = read_json_command(FP, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                  'stream=duration,nb_frames,width,height', '-of', 'json', master)['streams'][0]
    assert old_probe['nb_frames'] == v['nb_frames'] and old_probe['duration'] == v['duration']
    pp = read(RUN / 'ui_profiles.json')
    boxes = text_bounds(ass, count)
    save(REVIEW / 'caption_bounds.json', boxes)
    events = [line for line in ass.read_text('utf-8-sig').splitlines() if line.startswith('Dialogue: ')]
    assert len(events) == 4 and all(line.split(',', 9)[9].count(r'\N') == 0 for line in events)
    text_ui = {name: [{'frame': n, 'time_ms': round(n*1000/30, 3), 'bounds': box, 'ui': overlaps(box, p)}
                      for n, box in boxes.items() if overlaps(box, p)] for name, p in pp['platforms'].items()}
    assert not any(text_ui.values()), text_ui
    # Conservative manually reviewed anatomical face envelope (hair/ear cups are a separate envelope).
    crop = [144, 20, 144, 256]
    face = [168, 120, 89, 103]
    head = [149, 67, 136, 157]
    project = lambda b: [(b[0]-crop[0])*7.5, (b[1]-crop[1])*7.5, b[2]*7.5, b[3]*7.5]
    assert all(crop[0] <= b[0] and crop[1] <= b[1] and b[0]+b[2] <= crop[0]+crop[2]
               and b[1]+b[3] <= crop[1]+crop[3] for b in [face, head])
    face_ui = {name: overlaps(project(face), p) for name, p in pp['platforms'].items()}
    assert not any(face_ui.values()), face_ui
    assert all(not intersection(box, project(head)) for box in boxes.values()), 'Caption/head envelope intersection'
    cards, keycards, inspected = [], [], []
    panel_border_pass, image_bbox = [], []
    with av.open(str(video)) as container:
        for n, frame in enumerate(container.decode(video=0)):
            im = frame.to_ndarray(format='rgb24')
            # Flat navy gutters would have no useful color/texture in one or more edge strips.
            strips = [im[:12], im[-12:], im[:, :12], im[:, -12:]]
            means = [float(np.max(np.abs(s.astype(np.int16)-np.array([14, 24, 48])), axis=2).mean()) for s in strips]
            assert min(means) > 18, (n, means)
            panel_border_pass.append(n)
            if n % 3 == 0 or n == count-1:
                cards.append(tile(guide(im), f'F{n:03} {n/30:.2f} S', 180))
                inspected.append(n)
            if n in [0, 24, 81, 133, 192, 265]:
                png(REVIEW / f'final_frame_{n:03}.png', im)
                keycards.append(tile(guide(im), f'F{n:03} {n/30:.2f} S', 360))
    for page, offset in enumerate(range(0, len(cards), 30)):
        sheet(REVIEW / f'full_clip_control_{page:02}.png', cards[offset:offset+30], 6)
    sheet(REVIEW / 'control_keyframes.png', keycards, 3)
    # Same source frame before and after overview concatenation; no resize exists in overview.py.
    comparisons = []
    for n in [0, 133, 265]:
        _, _, old_im = next(sample_frames(master, [round(n*1000/30)]))
        _, _, overview_im = next(sample_frames(RUN/'BATCH_2876630043_OVERVIEW.mp4', [round((596+n)*1000/30)]))
        old_rect, overview_rect = active_bounds(old_im), active_bounds(overview_im)
        mae = float(np.abs(old_im[270:1080, 60:870].astype(np.int16)-overview_im[270:1080, 60:870]).mean())
        comparisons.append({'master_frame': n, 'overview_frame': 596+n,
                            'master_camera_active_bounds': old_rect, 'overview_camera_active_bounds': overview_rect,
                            'roi_mae': mae})
        assert old_rect == overview_rect and mae < 5, comparisons[-1]
    inputs = read(REVIEW / 'inputs.json')
    unchanged = {
        'batch_index': sha(RUN/'index.json') == inputs['index_sha256'],
        'old_master': sha(master) == inputs['parent_master_sha256'],
        'old_plan': sha(PROJECT/old_entry['files']['plan']) == inputs['parent_plan_sha256'],
        'overview': sha(RUN/'BATCH_2876630043_OVERVIEW.mp4') == inputs['overview_sha256'],
        'renderer': sha(PROJECT/'src/slicing/render_plan.py') == inputs['renderer_sha256'],
    }
    assert all(unchanged.values()), unchanged
    result = {
        'clip_id': 'BATCH_18b_v2', 'status': 'technical_pass_visual_review_pending',
        'source_of_borders': {
            'stage': 'Original BATCH_18b edit plan / stock master render, before overview assembly',
            'plan': old_entry['files']['plan'], 'layout_choice': 'SQUARE',
            'old_source_crop_xywh': [104, 0, 280, 280],
            'old_place_reference_xywh': [40, 180, 540, 540],
            'old_place_output_xywh': [60, 270, 810, 810],
            'old_camera_canvas_coverage_percent': 31.640625,
            'overview_resized_camera': False, 'comparison': comparisons,
        },
        'before': {'canvas_px': [1080, 1920], 'video_image_px': [810, 810],
                   'image_position_xy': [60, 270], 'master': str(master)},
        'after': {'canvas_px': [1080, 1920], 'video_image_px': [1080, 1920],
                  'image_position_xy': [0, 0], 'source_camera_window_xywh': [0, 0, 504, 280],
                  'source_crop_xywh': crop, 'static_crop': True,
                  'horizontal_scale': 7.5, 'vertical_scale': 7.5, 'aspect_error': 0,
                  'master': str(video), 'plan': str(REVIEW/'edit_plan.json'),
                  'full_canvas_edge_checks_passed_frames': len(panel_border_pass)},
        'media': {'full_decode': True, 'decoded_video_frames': count,
                  'format_duration_seconds': float(probe['format']['duration']),
                  'video_duration_seconds': float(v['duration']),
                  'audio_duration_seconds': float(a['duration']),
                  'same_video_frame_count_and_duration': True,
                  'source_intervals_ms': [[11781420, 11790300]],
                  'codec': ['h264', 'aac'], 'fps': '30/1', 'sample_rate': 48000, 'channels': 2},
        'audio': {'stream_copied_from_parent': str(master), 'aac_packets_equal': True,
                  'packet_count': len(new_packets), 'packet_pts_dts_duration_padding_equal': True,
                  'decoded_pcm_identical': True, 'decoded_samples_per_channel': len(new_pcm)//8,
                  'human_listening': False, 'no_new_audio_cuts': True},
        'captions': {'text_changed': False, 'whole_phrases': True, 'max_lines': 1,
                     'events': len(events), 'measured_active_frames': len(boxes),
                     'outline_and_shadow_included': True,
                     'fixed_position': 'upper room background, above head',
                     'measured_bounds_by_frame': str(REVIEW/'caption_bounds.json'),
                     'ui_conflicts': text_ui, 'head_envelope_conflicts': [],
                     'reflow': str(REVIEW/'caption_reflow.json')},
        'face': {'method': 'Conservative manual envelope, checked visually on output contacts; not automatic detection',
                 'source_face_xywh': face, 'output_face_xywh': project(face),
                 'source_head_and_headphones_xywh': head, 'output_head_xywh': project(head),
                 'head_wholly_inside_crop': True, 'face_ui_conflicts': face_ui,
                 'headphones_and_background_may_enter_ui': True},
        'ui_profiles': {'file': str(RUN/'ui_profiles.json'), 'source': pp['source'],
                        'kind': 'Krumzi calculated estimates, not a phone preview',
                        'platforms': list(pp['platforms']), 'mobile_preview': False},
        'visual_review': {'status': 'pending', 'prepared_frames': inspected,
                          'interval_step_seconds': 0.1, 'last_frame_included': True,
                          'key_frames_native_png': [0, 24, 81, 133, 192, 265],
                          'controls': [str(p) for p in sorted(REVIEW.glob('full_clip_control_*.png'))]},
        'original_files_unchanged': unchanged,
        'code_changed': False, 'new_dependencies': False, 'new_recognition_calls': 0,
        'changed_files': [],
    }
    save(REVIEW/'layout_check.json', result)
    print(json.dumps({'technical_pass': True, 'mp4': str(video), 'frames': count,
                      'text_frames': len(boxes), 'controls': len(inspected), 'same_audio': True}))


if __name__ == '__main__':
    main()
