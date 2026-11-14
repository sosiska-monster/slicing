from fractions import Fraction
from common import *

def rows(c,s,lo,hi):
    zero=Fraction(c.start_time,1000000)
    c.seek(int((zero+Fraction(lo-500,1000))/s.time_base),stream=s,backward=True)
    out=[]
    for p in c.demux(s):
        if p.pts is None or p.dts is None:continue
        pt,dt=p.pts*p.time_base-zero,p.dts*p.time_base-zero
        if dt>Fraction(hi+100,1000):break
        if Fraction(lo-50,1000)<=pt<Fraction(hi+50,1000):out.append((pt,dt,p.is_keyframe,hashlib.sha256(bytes(p)).hexdigest()))
    return out

def sound(path,start):
    b=command(FF,'-v','error','-nostdin','-ss',str(start),'-t','7','-i',path,'-vn','-ar','16000','-ac','1','-f','f32le','-c:a','pcm_f32le','-')
    return np.frombuffer(b,np.float32).astype(np.float64)

def main():
    target=RUN/'source_alignment.json'
    if target.exists():progress('alignment_reused');return
    proof=[]
    with av.open(str(SOURCE)) as a,av.open(str(INDEXED)) as b:
        assert a.start_time==b.start_time==62016333
        for kind in ['video','audio']:
            sa=getattr(a.streams,kind)[0];sb=getattr(b.streams,kind)[0]
            assert sa.codec_context.extradata==sb.codec_context.extradata
            for lo,hi in [(87000,97500),(2915660,2945950),(6779000,6791000),(11297000,11311000),(12917000,12934500)]:
                aa,bb=rows(a,sa,lo,hi),rows(b,sb,lo,hi)
                assert aa==bb and aa
                proof.append({'stream':kind,'window_ms':[lo,hi],'packets':len(aa),'pts_dts_payload_equal':True})
    old=PROJECT/'data/vods/2876630043.mp4'
    corr=[]
    if old.exists():
        for at in [650,6800,11298]:
            aa,bb=sound(INDEXED,at),sound(old,at)
            aa=np.diff(aa);bb=np.diff(bb)
            n=min(len(aa),len(bb));aa=aa[:n]-aa[:n].mean();bb=bb[:n]-bb[:n].mean()
            size=1 << (2*n-1).bit_length()
            raw=np.fft.irfft(np.fft.rfft(aa,size)*np.conj(np.fft.rfft(bb,size)),size)
            lags=np.arange(-16000,16001); vals=raw[lags%size]
            lag=int(lags[vals.argmax()])
            if lag>=0:lhs,rhs=aa[lag:],bb[:n-lag]
            else:lhs,rhs=aa[:n+lag],bb[-lag:]
            value=float(np.corrcoef(lhs,rhs)[0,1])
            assert abs(lag/16000*1000+42.7)<5 and value>.75
            corr.append({'start_s':at,'hq_relative_to_480p_ms':lag/16,'correlation':value})
    save(target,{'source_sha256':read(RUN/'preparation.json')['source_sha256'],'indexed_copy':proof,
                  'old_480p_audio_alignment':corr,'hq_word_times':'No offset applied to saved HQ word drafts',
                  'old_transcript_time_policy':'Legacy audio is about 42.7 ms later; guide only; cuts and captions use HQ audio'})
    progress('source_alignment_passed',audio_offsets=corr)

if __name__=='__main__':main()
