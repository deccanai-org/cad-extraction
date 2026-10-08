import sys, os, re, time, json, subprocess
PIPE, job = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(PIPE, 'decode')); sys.path.insert(0, os.getcwd())
if len(sys.argv) > 3:
    sid = int(sys.argv[3])
    import brep, grating, to_step2 as T2
    from piece_table import read_pieces
    p = read_pieces(job)[sid]
    r = brep.parse(open(os.path.join(job, 'subm', str(sid)), 'rb').read())
    rec = T2._piece_record(job, sid, p['name'])
    t0 = time.time(); sh, info = grating.build(r[0], r[1], p['wt'], rec)
    print(json.dumps(dict(sid=sid, name=p['name'], ok=sh is not None, sec=round(time.time() - t0, 1), nf=len(r[1]),
                          **{k: info.get(k) for k in ('why', 'bodies', 'closed_as_stored', 'closed_at_stored_ends', 'cells', 'cross_bars', 'weight_ratio', 'cut_from_stock')})))
    sys.exit()
from piece_table import read_pieces
ids = [k for k, p in read_pieces(job).items() if re.match(r'G[TR]\d', p['name'])]
for sid in ids:
    try:
        out = subprocess.run([sys.executable, __file__, PIPE, job, str(sid)], capture_output=True, text=True, timeout=120).stdout.strip().splitlines()
        print(out[-1] if out else f'{sid} no output', flush=True)
    except subprocess.TimeoutExpired:
        print(json.dumps(dict(sid=sid, timeout=120)), flush=True)
