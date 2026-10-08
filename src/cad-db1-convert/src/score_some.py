import sys, json, concurrent.futures as cf
sys.path.insert(0, '/opt/db1v2/src')
def one(tag):
    import score as S
    r = S.score(f'/opt/db1v2/pairs/{tag}.db1', f'/opt/db1v2/pairs/{tag}.ifc.truth.pkl')
    return tag, {k: r.get(k) for k in ('members', 'noprof', 'match', 'prof_ok', 'prof_diff', 'y_ok', 'frame_ok', 'ifc', 'shift_votes', 'secs', 'err')}, r.get('prof_diff_top'), {k: (r.get('lay') or {}).get(k) for k in ('attr', 'attr_stride', 'prof_off', 'rest_ref', 'rest_stride', 'rest_off', 'csys', 'csys_stride', 'csys_k')}
with cf.ProcessPoolExecutor(len(sys.argv) - 1) as ex:
    for f in cf.as_completed([ex.submit(one, t) for t in sys.argv[1:]]): print(*f.result(), flush=True)
