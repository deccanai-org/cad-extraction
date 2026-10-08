"""Cloud validation runner: fetch pairs from S3, build IFC truth, score the decoder,
write one JSON per pair to _state/db1-v2/val/. Usage: python3 run_val.py [procs]"""
import boto3, json, os, sys, hashlib, concurrent.futures as cf, pickle, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
B = 'annotationprod'; W = '/opt/db1v2/pairs'; os.makedirs(W, exist_ok=True)
def s3(): return boto3.client('s3', region_name='ap-south-1')
def job(p):
    import score as S, ifctruth as T
    c = s3()
    tag = f"{p['engine']}_{p['sha'][:10]}"
    a = f"{W}/{tag}.db1"; b = f"{W}/{tag}.ifc"
    try:
        if not os.path.exists(a): c.download_file(B, p['db1'], a)
        if not os.path.exists(b): c.download_file(B, p['ifc'][0], b)
        if not os.path.exists(b + '.truth.pkl'):
            pickle.dump(T.truth(b), open(b + '.truth.pkl', 'wb'))
        r = S.score(a, b + '.truth.pkl')
    except Exception as e:
        r = dict(err=f'{type(e).__name__}: {e}'[:400])
    r.update(tag=tag, engine=p['engine'], status=p['status'], db1=p['db1'], ifc_key=p['ifc'][0])
    c.put_object(Bucket=B, Key=f"cad-disk-extract/_state/db1-v2/val/{tag}.json", Body=json.dumps(r, default=str).encode())
    return tag, {k: r.get(k) for k in ('members', 'match', 'prof_ok', 'y_ok', 'ifc', 'secs', 'err')}
if __name__ == '__main__':
    P = json.loads(s3().get_object(Bucket=B, Key='cad-disk-extract/_control/db1-v2/pairs.json')['Body'].read())
    P.sort(key=lambda p: -p['db1_bytes'])
    with cf.ProcessPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else os.cpu_count()) as ex:
        for f in cf.as_completed([ex.submit(job, p) for p in P]):
            print(*f.result(), flush=True)
    print('VAL-DONE', flush=True)
