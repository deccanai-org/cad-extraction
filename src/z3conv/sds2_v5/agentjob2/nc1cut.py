"""v5.5.4 NC1 opt-in dry run: plan + extra holes + boolean per matched W piece. usage: nc1cut.py <decode> <out.jsonl> <job id>..."""
import sys, os, re, json, gzip, collections, traceback, shutil
import boto3
sys.path.insert(0, sys.argv[1])
import nc1 as NC, brep
from sds2job import read_members
from piece_table import read_pieces
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
F = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/'; W = '/work/agentwork/sds2v54'
NC1C = '/work/agentwork/sds2-recall-nc1/nc1cache'
pairs = json.load(open(f'{W}/nc1/eval_pairs.json'))
out = open(sys.argv[2], 'a')
for jid in sys.argv[3:]:
    r = dict(id=jid)
    jd = f'{W}/jobs_nc1/c_{jid[:8]}'
    try:
        key = s3.list_objects_v2(Bucket=B, Prefix=F + jid[:8])['Contents'][0]['Key']
        mf = json.loads(gzip.decompress(s3.get_object(Bucket=B, Key=key)['Body'].read()))
        k = next(f['key'] for f in mf if f['p'].replace('\\', '/').lower().endswith('main/jsetup') and f.get('key'))
        root = k[:-len('main/jsetup')]; os.environ['SDS2_JOB_NAME'] = root.rstrip('/').split('/')[-1]
        r['job_name'] = os.environ['SDS2_JOB_NAME']
        os.system(f'{W}/env/bin/python {W}/getjob3k.py {key} {W}/jobs_nc1 c_{jid[:8]} > /dev/null 2>&1')
        os.makedirs(f'{jd}/pcm', exist_ok=True)
        open(f'{jd}/pcm/pcm_list', 'wb').write(s3.get_object(Bucket=B, Key=root + 'pcm/pcm_list')['Body'].read())
        nd = f'{W}/jobs_nc1/n_{jid[:8]}'; os.makedirs(nd, exist_ok=True)
        for i, e in enumerate(pairs.get(jid, [])):
            p = os.path.join(NC1C, e['sha256'][:2], e['sha256'])
            if os.path.exists(p): shutil.copy(p, os.path.join(nd, f'{i}_{os.path.basename(e["path"])}'))
        mems, L = read_members(jd); P = read_pieces(jd)
        plan, st = NC.plan(jd, nd, mems, L, P)
        r['plan'] = dict(st)
        tot = collections.Counter(); ex = []
        for sid, part in plan.items():
            b = open(f'{jd}/subm/{sid}', 'rb').read(); rr = brep.parse(b); H = brep.holes(b)
            if rr is None: tot['no B-rep'] += 1; continue
            extra, s2 = NC.extra_holes(part, rr[0], rr[1], H); tot.update(s2)
            if extra:
                sh = brep.solid(*rr)
                if sh is None: tot['pieces: B-rep not a solid'] += 1; continue
                c1 = brep.cut_holes(sh, H) if H else sh
                c2 = brep.cut_holes(c1, extra)
                tot['pieces with NC1 holes'] += 1
                tot['boolean ok' if c2 is not c1 else 'boolean failed'] += 1
                if len(ex) < 6: ex.append((part['mark'], part['profile'], len(extra), len(part['holes']), len(H), sorted({h['face'] for h in part['holes']})))
        r['holes'] = dict(tot); r['examples'] = ex
    except Exception:
        r['error'] = traceback.format_exc()[-400:]
    shutil.rmtree(jd, ignore_errors=True); shutil.rmtree(f'{W}/jobs_nc1/n_{jid[:8]}', ignore_errors=True)
    out.write(json.dumps(r) + '\n'); out.flush()
