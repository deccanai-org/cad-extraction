#!/usr/bin/env python3
"""project_all.py ROWS.json -> for every live 'sds2 pieces not built' model: partial fetch (piece table, sections, skipped
piece files), replay each skipped piece on v5.5.3 and on v5.5.3 + patch (project_one.py), upload per-model JSON."""
import sys, os, json, csv, io, subprocess, shutil, collections, concurrent.futures as cf, boto3
W = '/work/agentwork/sds2-pieces-not-built'
B = 'bim-proprietary-data'
R = 'cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-pieces-not-built/projection/'
s3 = boto3.client('s3', region_name='ap-south-1')
rows = json.load(open(sys.argv[1]))
PAR = int(sys.argv[2]) if len(sys.argv) > 2 else 6
os.makedirs(f'{W}/pjobs', exist_ok=True); os.makedirs(f'{W}/proj', exist_ok=True)
PY = f'{W}/env/bin/python'


def one(r):
    rid = r['id']; od = f'{W}/proj/{rid}'
    if os.path.exists(f'{od}/DONE'):
        return rid, 'cached'
    os.makedirs(od, exist_ok=True)
    try:
        base = r['step_key'][:-len('.step')]
        b = s3.get_object(Bucket=B, Key=base + '_skipped.csv')['Body'].read()
        open(f'{od}/skipped.csv', 'wb').write(b)
        cnt = collections.Counter()
        for x in csv.DictReader(io.StringIO(b.decode('utf-8', 'replace'))):
            cnt[x.get('piece')] += 1
        sids = [s for s, _ in cnt.most_common(300)]
        open(f'{od}/sids.txt', 'w').write('\n'.join(sids))
        nm = os.path.basename(base)[:-len('_stage2')].rsplit('_', 1)[0]
        p = subprocess.run(['/opt/conv/env/bin/python', f'{W}/stage/pfetch.py', f'{W}/pjobs', rid, nm, f'@{od}/sids.txt'],
                           capture_output=True, text=True, timeout=1800)
        name = p.stdout.strip().split('\n')[-1]
        open(f'{od}/fetch.log', 'w').write(p.stderr[-2000:])
        jd = f'{W}/pjobs/{name}'
        for V in ('v553', 'v553q'):
            q = subprocess.run(['timeout', '1500', PY, f'{W}/stage/project_one.py', f'{W}/trees/{V}/decode', jd, f'{od}/skipped.csv',
                                f'{od}/{V}.json', '300'], capture_output=True, text=True)
            open(f'{od}/{V}.log', 'w').write((q.stdout + q.stderr)[-3000:])
        shutil.rmtree(jd, ignore_errors=True)
        for f in os.listdir(od):
            s3.upload_file(f'{od}/{f}', B, f'{R}{rid}/{f}')
        open(f'{od}/DONE', 'w').close()
        return rid, 'ok'
    except Exception as e:
        return rid, f'error {type(e).__name__}: {e}'


with cf.ThreadPoolExecutor(PAR) as ex:
    for rid, st in ex.map(one, rows):
        print(rid, st, flush=True)
open(f'{W}/out/PROJ_DONE', 'w').close()
s3.upload_file(f'{W}/out/PROJ_DONE', B, R + 'PROJ_DONE')
