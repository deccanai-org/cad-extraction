"""NC1 opt-in evaluation on real jobs (box). For each job id: strict-match NC1 main parts (order == job folder name,
mark == member mark via pcm_list, one main piece, length within 3 mm, same profile); per matched part and NC1 face:
decoded holes present at the mapped position (fit hypotheses), or piece without decoded holes (NC1 would add them).
usage: nc1eval.py <decode dir> <out.jsonl> <job id> ..."""
import sys, os, re, json, gzip, struct, collections, itertools, traceback, shutil
import numpy as np
import boto3
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, '/work/agentwork/sds2-recall-nc1')
import sds2job, brep, nc1_holes_check as N
from piece_table import read_pieces
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
F = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/'
W = '/work/agentwork/sds2v54'
NC1C = '/work/agentwork/sds2-recall-nc1/nc1cache'
pairs_nc1 = json.load(open(f'{W}/nc1/eval_pairs.json'))
norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())
pn = lambda s: re.sub(r'[^A-Z0-9/.]', '', (s or '').upper())
out = open(sys.argv[2], 'a')
for jid in sys.argv[3:]:
    r = dict(id=jid)
    try:
        key = s3.list_objects_v2(Bucket=B, Prefix=F + jid[:8])['Contents'][0]['Key']
        mf = json.loads(gzip.decompress(s3.get_object(Bucket=B, Key=key)['Body'].read()))
        k = next(f['key'] for f in mf if f['p'].replace('\\', '/').lower().endswith('main/jsetup') and f.get('key'))
        root = k[:-len('main/jsetup')]
        jname = root.rstrip('/').split('/')[-1]
        r['job_name'] = jname
        jd = f'{W}/jobs_nc1/{jid[:8]}'
        os.system(f'{W}/env/bin/python {W}/getjob3k.py {key} {W}/jobs_nc1 {jid[:8]} > /dev/null 2>&1')
        os.makedirs(f'{jd}/pcm', exist_ok=True)
        open(f'{jd}/pcm/pcm_list', 'wb').write(s3.get_object(Bucket=B, Key=root + 'pcm/pcm_list')['Body'].read())
        r['version'] = sds2job.read_version(jd)
        mem, L = sds2job.read_members(jd)
        idx = open(os.path.join(jd, 'mem', 'mem_idx'), 'rb').read()
        b = open(f'{jd}/pcm/pcm_list', 'rb').read(); nm = (len(b) - 256) // 72
        marks = [b[256 + 72 * i: 256 + 72 * i + 40].split(b'\x00')[0].decode('latin-1') for i in range(nm)]
        P = read_pieces(jd)
        by_mark = collections.defaultdict(list)
        for m in mem:
            s = idx[m.id * L['slot']:(m.id + 1) * L['slot']]
            v = struct.unpack('>h', s[L['sec'] + 4:L['sec'] + 6])[0]
            if 0 < v < nm and marks[v]:
                try:
                    sid = struct.unpack('>i', open(os.path.join(jd, 'mem', str(m.id)), 'rb').read(0xEC)[0xE8:0xEC])[0]
                except Exception:
                    sid = None
                by_mark[marks[v]].append(sid)
        parts = []; seen = set()
        for e in pairs_nc1.get(jid, []):
            p = os.path.join(NC1C, e['sha256'][:2], e['sha256'])
            if e['sha256'] in seen or not os.path.exists(p): continue
            seen.add(e['sha256']); parts.append(N.parse_nc1(open(p, 'rb').read().decode('latin-1'), e['path']))
        c = collections.Counter(); fits = collections.Counter(); bymark = collections.defaultdict(list)
        for pt in parts:
            if pt['code'] in ('I', 'U', 'L', 'C', 'T', 'M', 'RO', 'RU') and pt['holes']:
                bymark[pt['mark']].append(pt)
        for mk, pts in bymark.items():
            c['nc1 main marks with holes'] += 1
            if len({(round(p['length'] or 0, 1), len(p['holes'])) for p in pts}) > 1: c['mark: NC1 revisions disagree'] += 1; continue
            pt = pts[0]
            if norm(pt['order']) != norm(jname): c['order differs'] += 1; continue
            sids = {s for s in by_mark.get(mk, []) if s in P}
            if not by_mark.get(mk): c['mark not on a member'] += 1; continue
            if len(sids) != 1: c['mark on members with different main pieces'] += 1; continue
            sid = sids.pop(); p = P[sid]
            if pt['length'] is None or abs(p['L'] * 25.4 - pt['length']) > 3: c['length differs > 3 mm'] += 1; continue
            if pn(p['name']) != pn(pt['profile']): c['profile differs'] += 1; continue
            c['strict parts'] += 1; c['strict nc1 holes'] += len(pt['holes'])
            data = open(os.path.join(jd, 'subm', str(sid)), 'rb').read()
            H = brep.holes(data); rr = brep.parse(data)
            if rr is None: c['strict: no B-rep'] += 1; continue
            V, Fc = rr; used = sorted({q for f in Fc for q in f}); lo, hi = V[used].min(0) * 25.4, V[used].max(0) * 25.4
            if not H:
                c['strict parts without decoded holes'] += 1; c['nc1 holes on parts without decoded holes'] += len(pt['holes'])
                fits[(pt['code'], 'no decoded holes')] += 1
                continue
            D = [(h['c'] * 25.4, h['dia'] * 25.4) for h in H]
            for face in sorted({h['face'] for h in pt['holes']}):
                Hn = [h for h in pt['holes'] if h['face'] == face]; best = None
                for a1 in range(3):
                    for a2 in range(3):
                        if a1 == a2: continue
                        for sx, sy in itertools.product((1, -1), (1, -1)):
                            x0 = lo[a1] if sx > 0 else hi[a1]; y0 = lo[a2] if sy > 0 else hi[a2]
                            hit = sum(1 for h in Hn if any(abs(cc[a1] - (x0 + sx * h['x'])) < 1.5 and abs(cc[a2] - (y0 + sy * h['y'])) < 1.5
                                                           and abs(d - h['d']) < 1.0 for cc, d in D))
                            if best is None or hit > best[1]: best = ((a1, a2, sx, sy), hit)
                fits[(pt['code'], face, str(best[0]), 'all' if best[1] == len(Hn) else 'some' if best[1] else 'none')] += 1
                if 0 < best[1] < len(Hn):
                    a1, a2, sx, sy = best[0]; x0 = lo[a1] if sx > 0 else hi[a1]; y0 = lo[a2] if sy > 0 else hi[a2]
                    for h in Hn:
                        dd = min((np.hypot(cc[a1] - (x0 + sx * h['x']), cc[a2] - (y0 + sy * h['y'])), abs(d - h['d'])) for cc, d in D)
                        if dd[0] < 1.5 and dd[1] < 1.0: continue
                        kind = 'slot' if h.get('slot') else 'round'
                        c[f'unmatched {kind}: ' + ('decoded hole within 1.5 mm, other diameter' if dd[0] < 1.5 else 'decoded hole 1.5-25 mm away' if dd[0] < 25 else 'no decoded hole within 25 mm')] += 1
                c['strict faces'] += 1; c['strict faces: all NC1 holes already decoded'] += best[1] == len(Hn)
                c['strict nc1 holes already decoded'] += best[1]
        r.update(counts=dict(c), fits={' '.join(map(str, k)): v for k, v in fits.most_common(40)})
    except Exception:
        r['error'] = traceback.format_exc()[-500:]
    shutil.rmtree(f'{W}/jobs_nc1/{jid[:8]}', ignore_errors=True)
    out.write(json.dumps(r) + '\n'); out.flush(); print(json.dumps(r)[:400], flush=True)
