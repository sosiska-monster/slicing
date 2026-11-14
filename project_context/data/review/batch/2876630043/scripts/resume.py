import argparse
from common import *

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    idx=read(RUN/'index.json');prep=read(RUN/'preparation.json')
    assert sha(SOURCE)==prep['source_sha256'],'HQ source changed; editorial mapping must be revalidated'
    for name,digest in prep['input_hashes'].items():assert sha(PROJECT/name)==digest,('Input changed',name)
    stale=[]
    for e in idx['episodes']:
        if not e.get('files',{}).get('mp4'):continue
        q=read(PROJECT/e['files']['qa'])
        for key,field in [('plan','plan'),('video','mp4'),('ass','ass')]:
            if sha(PROJECT/e['files'][field])!=q['hashes'][key]:stale.append((e['candidate_id'],field))
    assert not stale,('Stale artifacts preserved; require a concrete revised plan before replacement',stale)
    pending=[e['candidate_id'] for e in idx['episodes'] if e['status'] not in ['rendered','reserve','needs_review','failed']]
    if pending and not args.verify_only:
        assert INDEXED.exists(),'Prepared local seek cache missing; run scripts/prepare.py first'
        from render_batch import main as render
        from check_batch import main as check
        render();check()
        result={'pending_editorial_or_visual_review':pending,'note':'Sol decisions are not fabricated by the local runner'}
    else:
        result={'counts':idx['counts'],'pending':pending,'render_calls':0,'whisper_calls':0,'sol_calls':0,
                 'source_and_artifact_hashes_verified':True,'review_follow_up':idx.get('follow_up_review_ids',[])}
    save(RUN/'repeat_verification.json',result);progress('repeat_reuse_verified',**result)

if __name__=='__main__':main()
