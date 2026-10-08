# sec_check.py DECODE JOBDIR... : 2494-B slot jobs: section field 0x1D4 vs 0x1D8 (and roll 0x1DA vs 0x1DE) on the structural members,
# calibrate()'s heuristic score and the main-piece agreement for both offsets (read-only)
import sys, os, json, struct, collections, re
sys.path.insert(0, sys.argv[1])
import sds2job as S
import numpy as np
for job in sys.argv[2:]:
    rec = {'job': job.split('/jobs/')[-1].split('/')[0][:12]}
    try:
        sh = S.read_shapes(job); rec['ver'] = S.read_version(job)
        md = os.path.join(job, 'mem'); idx = open(os.path.join(md, 'mem_idx'), 'rb').read()
        ids = sorted(int(n) for n in os.listdir(md) if n.isdigit()); slot = 2494; toff = 0x988
        if (len(idx) - 256) % slot:
            rec['err'] = 'not 2494'; print(json.dumps(rec)); continue
        st = [n for n in ids if S._ascii(idx[n * slot + toff:n * slot + toff + 20]) in ('BEAM', 'COLUMN', 'VERTICAL BRACE', 'HORIZONTAL BRACE')]
        beams = [n for n in st if S._ascii(idx[n * slot + toff:n * slot + toff + 20]) == 'BEAM'][:3000]
        def i16(n, o): return struct.unpack('>h', idx[n * slot + o:n * slot + o + 2])[0]
        def f64(n, o): return struct.unpack('>d', idx[n * slot + o:n * slot + o + 8])[0]
        rec['structural'] = len(st)
        if not st:
            print(json.dumps(rec)); continue
        same = sum(1 for n in st if i16(n, 0x1D4) == i16(n, 0x1D8))
        rec['sec_1D4_eq_1D8'] = f'{same}/{len(st)}'
        for o in (0x1D4, 0x1D8):
            vals = [i16(n, o) for n in beams]; ok = [v for v in vals if v in sh and sh[v].family in S.SHAPE_FAMILIES]
            rec[f'heur_{o:#x}'] = round(len(ok) / max(1, len(vals)) * min(len(set(ok)), 20), 3) if vals else None
            rec[f'mapped_{o:#x}'] = f'{sum(1 for n in st if i16(n, o) in sh)}/{len(st)}'
            rec[f'fam_{o:#x}'] = collections.Counter(sh[i16(n, o)].family for n in st if i16(n, o) in sh).most_common(4)
        for o in (0x1DA, 0x1DE):
            r = np.array([f64(n, o) for n in st]); fin = np.isfinite(r) & (np.abs(r) <= 7)
            rec[f'roll_{o:#x}'] = {'finite_le7': int(fin.sum()), 'nonzero': int((fin & (np.abs(r) > 1e-9)).sum()), 'distinct': len(set(np.round(r[fin], 6)))}
        rec['agree'] = {hex(k): round(v, 3) for k, v in S._main_piece_agreement(job, idx, slot, toff, ids, sh, [0x1D4, 0x1D8, 0x1BA]).items()}
    except Exception as e:
        rec['err'] = f'{type(e).__name__}: {e}'
    print(json.dumps(rec, default=str), flush=True)
