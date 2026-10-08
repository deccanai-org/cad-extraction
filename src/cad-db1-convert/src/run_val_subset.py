"""re-run validation for tags matching a prefix list, recomputing truth (argv: prefixes...)"""
import sys, os, glob, json, pickle, concurrent.futures as cf, boto3
sys.path.insert(0, '/opt/db1v2/src')
W = '/opt/db1v2/pairs'
def job(tag):
    import score as S, ifctruth as T
    b = f'{W}/{tag}.ifc'
    if not os.path.exists(b + '.truth.pkl'): pickle.dump(T.truth(b), open(b + '.truth.pkl', 'wb'))
    L = json.load(open('/opt/db1v2/layouts.json')); V = [v['layout'] for v in L.values() if v.get('layout')]
    eng = tag.split('_')[0]
    r = S.score(f'{W}/{tag}.db1', b + '.truth.pkl', (L.get(eng) or {}).get('layout'), V); r['tag'] = tag; r['engine'] = eng
    boto3.client('s3', region_name='ap-south-1').put_object(Bucket='annotationprod', Key=f'cad-disk-extract/_state/db1-v2/val/{tag}.json', Body=json.dumps(r, default=str).encode())
    return tag, {k: r.get(k) for k in ('members', 'match', 'prof_ok', 'prof_diff', 'y_ok', 'frame_ok', 'ifc', 'noprof', 'rot_deg', 'shift_votes', 'err')}, r.get('prof_diff_top'), {k: r.get('lay', {}).get(k) for k in ('attr', 'attr_stride', 'prof_off', 'rest_ref', 'rest_off')}
tags = sorted({os.path.basename(p)[:-4] for p in glob.glob(f'{W}/*.db1') if any(os.path.basename(p).startswith(x) for x in sys.argv[1:])})
with cf.ProcessPoolExecutor(len(tags) or 1) as ex:
    for f in cf.as_completed([ex.submit(job, t) for t in tags]): print(*f.result(), flush=True)
