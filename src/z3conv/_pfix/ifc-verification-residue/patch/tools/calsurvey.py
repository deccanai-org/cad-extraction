# calsurvey.py DECODE_DIR JOBDIR... : layout calibrate() picks on 7.2xx jobs that have structural members
import sys, os, json
sys.path.insert(0, sys.argv[1])
import sds2job as S
for job in sys.argv[2:]:
    try:
        sh = S.read_shapes(job)
        L = S.calibrate(job, sh)
        Ls = {k: (hex(v) if isinstance(v, int) and k != 'fw' else v) for k, v in L.items()}
        mem, _ = S.read_members(job, L)
        from collections import Counter
        types = Counter(m.type for m in mem)
        secs = sum(1 for m in mem if m.type in ('BEAM', 'COLUMN') and m.section is not None)
        nb = sum(1 for m in mem if m.type in ('BEAM', 'COLUMN'))
        print(json.dumps(dict(job=os.path.basename(job.rstrip('/')), ver=S.read_version(job), layout=Ls, members=len(mem), types=types.most_common(6), beams_cols_with_section=f'{secs}/{nb}')))
    except Exception as e:
        print(json.dumps(dict(job=job, err=f'{type(e).__name__}: {e}')))
