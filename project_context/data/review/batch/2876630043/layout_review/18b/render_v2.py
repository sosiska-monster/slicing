"""Data-only monologue correction using the installed stock renderer."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[6]
REVIEW = Path(__file__).resolve().parent
HQ = PROJECT / 'data/review/codex_pilot/full_hq'
RUN = PROJECT / 'data/review/batch/2876630043'
sys.path.insert(0, str(PROJECT / 'src'))
sys.path.insert(0, str(RUN / 'scripts'))
from common import FF, FP, read, save, sha
from slicing.media import Media
from slicing.render_plan import render_plan


def command(*args):
    result = subprocess.run(list(map(str, args)), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace'))
    return result.stdout


def main():
    entry = next(e for e in read(RUN / 'index.json')['episodes'] if e['candidate_id'] == '18b')
    old_plan = PROJECT / entry['files']['plan']
    master = PROJECT / entry['files']['mp4']
    document = copy.deepcopy(read(old_plan))
    clip = document['clips'][0]
    clip['id'] = 'BATCH_18b_v2'
    clip['safe_margins'] = {
        'left': 52 / 720, 'right': 156 / 720,
        'top': 0, 'bottom': 1040 / 1280,
    }
    segment = clip['segments'][0]
    assert [segment['start_ms'], segment['end_ms']] == [11781420, 11790300]
    assert len(clip['segments']) == 1
    segment['framing'] = {
        'name': 'static_monologue_full_portrait',
        'panels': [{'crop': [144, 20, 144, 256], 'place': [0, 0, 720, 1280]}],
    }
    final = segment['captions'].pop()
    assert final['lines'] == ['То есть 3 200 —', 'это прям ПК уже.']
    # Saved HQ w012 ends / w013 starts at clip 6400 ms. No recognition call.
    boundary = 11787820
    segment['captions'].extend([
        {'start_ms': final['start_ms'], 'end_ms': boundary, 'lines': [final['lines'][0]]},
        {'start_ms': boundary, 'end_ms': final['end_ms'], 'lines': [final['lines'][1]]},
    ])
    document['editorial'].update({
        'parent_clip': 'BATCH_18b', 'parent_plan': old_plan.relative_to(PROJECT).as_posix(),
        'parent_plan_sha256': sha(old_plan),
        'layout_choice': 'FULL_PORTRAIT',
        'layout_family': 'solo',
        'source_camera_window_xywh': [0, 0, 504, 280],
        'crop_selection': 'One constant exact 9:16 crop wholly inside the source camera window; no padding or stretching.',
        'caption_placement': 'Fixed upper background above the head. Last two-line phrase split at saved HQ w012/w013 boundary (clip 6400 ms).',
        'ui_profiles': (RUN / 'ui_profiles.json').relative_to(PROJECT).as_posix(),
        'ui_status': 'Saved Krumzi organic-feed estimates; mobile preview not performed.',
        'changes': 'Picture and caption placement/reflow only. Same utterances, source interval, duration and approved AAC packets.',
    })
    plan = REVIEW / 'edit_plan.json'
    save(plan, document)
    save(REVIEW / 'caption_reflow.json', {
        'source_review': (RUN / 'clips/18b/saved_review.json').relative_to(PROJECT).as_posix(),
        'source_review_sha256': sha(RUN / 'clips/18b/saved_review.json'),
        'text_changed': False, 'new_whisper_calls': 0,
        'split_source_word_ids': ['w012', 'w013'], 'split_clip_ms': 6400,
        'source_captions': read(old_plan)['clips'][0]['segments'][0]['captions'],
        'captions': segment['captions'],
    })
    save(REVIEW / 'inputs.json', {
        'index_sha256': sha(RUN / 'index.json'),
        'parent_master_sha256': sha(master), 'parent_plan_sha256': sha(old_plan),
        'overview_sha256': sha(RUN / 'BATCH_2876630043_OVERVIEW.mp4'),
        'renderer_sha256': sha(PROJECT / 'src/slicing/render_plan.py'),
        'source': str(HQ / 'data/vods/2876630043.mp4'),
        'source_bytes': (HQ / 'data/vods/2876630043.mp4').stat().st_size,
    })
    work = REVIEW / 'work'
    work.mkdir(exist_ok=True)
    target = HQ / 'data/review/mvp/2876630043/BATCH_18b_v2'
    if not target.exists():
        output = render_plan(plan, clip['id'], None, HQ, Media(FF, FP), work_directory=work)
    else:
        assert read(target / 'manifest.json')['edit_plan_sha256'] == sha(plan)
        output = target / 'BATCH_18b_v2.mp4'
    temp = REVIEW / 'with_original_audio.mp4'
    command(FF, '-v', 'error', '-nostdin', '-y', '-i', output, '-i', master,
            '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', '-map_metadata', '-1',
            '-movflags', '+faststart', temp)
    temp.replace(output)
    manifest_path = target / 'manifest.json'
    manifest = read(manifest_path)
    manifest['audio'].update({
        'approved_audio_parent': master.relative_to(PROJECT).as_posix(),
        'stream_copy': True,
    })
    save(manifest_path, manifest)
    print(json.dumps({'mp4': str(output), 'plan': str(plan)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
