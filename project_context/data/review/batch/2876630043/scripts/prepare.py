import shutil
import sys

from common import *

def main():
    state=RUN/'preparation.json'
    fingerprints={str(p.relative_to(PROJECT)):sha(p) for p in [
        PROJECT/'data/review/transcript_2876630043.json',
        PROJECT/'data/review/codex_pilot/full_vod/candidates.json',
        PROJECT/'data/review/codex_pilot/full_vod/coverage.json',
        HQ/'data/review/index.json',HQ/'data/review/contest/index.json',
        PROJECT/'src/slicing/render_plan.py',PROJECT/'src/slicing/framing.py']}
    old=read(state) if state.exists() else {}
    assert not old or old['input_hashes']==fingerprints,'Inputs changed; preserve run and review invalidation before continuing'
    if old.get('stage')=='complete' and INDEXED.is_file():
        progress('preparation_reused');return
    source_stat=SOURCE.stat()
    progress('preparation_start',source_bytes=source_stat.st_size,free_bytes=shutil.disk_usage(RUN).free)
    if not INDEXED.exists():
        assert shutil.disk_usage(RUN).free > source_stat.st_size+3*1024**3,'Insufficient room for seek cache plus render headroom'
        INDEXED.parent.mkdir(parents=True,exist_ok=True)
        command(FF,'-v','error','-nostdin','-n','-copyts','-i',SOURCE,'-map','0:v:0','-map','0:a:0',
                '-c','copy','-video_track_timescale','1000000','-movie_timescale','1000000',INDEXED)
    progress('hq_seek_copy_ready',size=INDEXED.stat().st_size)
    probe=json.loads(command(FP,'-v','error','-show_streams','-show_format','-of','json',INDEXED))
    assert (probe['streams'][0]['width'],probe['streams'][0]['height'])==(1920,1080)
    assert probe['streams'][0]['r_frame_rate']=='60/1'
    save(RUN/'hq_probe.json',probe)
    source_sha=old.get('source_sha256') or sha(SOURCE)
    cov=read(PROJECT/'data/review/codex_pilot/full_vod/coverage.json')
    tr=read(PROJECT/'data/review/transcript_2876630043.json')
    assert len(tr['cues'])==cov['total_cues']==3797
    assert sha(PROJECT/'data/review/transcript_2876630043.json')==cov['transcript_sha256']
    save(state,{'stage':'complete','input_hashes':fingerprints,'source_sha256':source_sha,
                'source':rel(SOURCE),'source_bytes':source_stat.st_size,'source_start_us':62016333,
                'playback_duration_ms':cov['source_duration_ms'],'metadata_probe':rel(RUN/'hq_probe.json'),
                'indexed_copy':rel(INDEXED),'whisper_timing':'HQ draft timestamps as saved; old 480p transcript visual guide only'})
    for name,path in [('catalog',PROJECT/'data/review/codex_pilot/full_vod/candidates.json'),
                      ('coverage',PROJECT/'data/review/codex_pilot/full_vod/coverage.json'),
                      ('prior_index',HQ/'data/review/index.json'),
                      ('contest_index',HQ/'data/review/contest/index.json')]:
        save(RUN/'inputs'/f'{name}.json',read(path))
    profiles=read(HQ/'data/review/contest/clips/PUB_17d_ui/ui_profiles.json')
    profiles['platforms']={k:profiles['platforms'][k] for k in ['TikTok','Shorts']}
    profiles['usage']='Saved Krumzi organic-feed estimate; not a phone measurement'
    save(RUN/'ui_profiles.json',profiles)
    (RUN/'application_checklist.md').write_bytes((HQ/'data/review/contest/application_checklist.md').read_bytes())
    progress('preparation_complete',source_sha256=source_sha,cues=3797)

if __name__=='__main__':main()
