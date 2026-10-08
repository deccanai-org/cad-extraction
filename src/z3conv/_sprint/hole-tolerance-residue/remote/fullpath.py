"""fullpath.py KIT ID12 [ID12...] : production path of worker.py for one kit: convert_one.py (ifcopenshell 0.8.4) -> ifc2step6.py --mode hybrid
--prec 2 --threads 4 -> step_check.py (OCC read-back, per-solid validity). Summarises bolt_stats + the hole profiles written to the IFC
(BOLT_HOLE_D<d> circle profiles and how many cuts use each) + STEP check. Uploads full/<kit>/<id12>.json."""
import json, os, sys, subprocess, re, collections, time, gzip
KIT = os.path.abspath(sys.argv[1]); ids = sys.argv[2:]
PY84 = os.environ.get('HTR_PY84', '/opt/conv/ifc84/bin/python'); PY = os.environ.get('HTR_PY', '/opt/conv/env/bin/python')
S3OUT = 's3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/hole-tolerance-residue/full'
LAY = json.load(open(os.path.join(KIT, 'layouts.json')))
M = {m['id'][:12]: m for m in json.load(open('models2.json'))}
for i12 in ids:
    m = M[i12]; d = os.path.abspath(f'full/{os.path.basename(KIT)}/{i12}'); os.makedirs(d, exist_ok=True)
    db1 = os.path.abspath(f"db1/{m['id']}.db1"); ifc = f'{d}/m.ifc'; stp = f'{d}/m.stp'; stats = f'{d}/stats.json'
    lp = f'{d}/layout.json'; vp = f'{d}/variants.json'
    json.dump(LAY[m['engine']].get('layout'), open(lp, 'w')); json.dump([v['layout'] for v in LAY.values() if v.get('layout')], open(vp, 'w'))
    res = {'id': m['id'], 'kit': os.path.basename(KIT)}; t = time.time()
    r = subprocess.run([PY84, f'{KIT}/convert_one.py', db1, ifc, f'{KIT}/tekla_profiles.json', lp, stats, vp], capture_output=True, text=True)
    cs = json.load(open(stats)) if os.path.exists(stats) else {}
    res.update(convert_rc=r.returncode, convert_status=cs.get('status'), convert_sec=round(time.time() - t, 1), bolt_stats=cs.get('bolt_stats'),
               written=cs.get('written'), trace=(cs.get('trace') or '')[-600:] or None)
    if cs.get('status') == 'ok' and os.path.exists(ifc):
        # hole profiles and cut usage straight from the IFC text
        txt = open(ifc, errors='replace').read()
        prof = dict(re.findall(r"#(\d+)=IFCCIRCLEPROFILEDEF\(\.AREA\.,'BOLT_HOLE_D([0-9.]+)'", txt))
        use = collections.Counter()
        for pid, dd in prof.items():
            use[dd] = len(re.findall(r'IFCEXTRUDEDAREASOLID\(#%s,' % pid, txt))
        res['ifc_hole_profiles'] = dict(sorted(use.items(), key=lambda kv: -kv[1]))
        res['ifc_bytes'] = len(txt)
        t = time.time()
        r = subprocess.run([PY84, f'{KIT}/ifc2step6.py', ifc, stp, '--mode', 'hybrid', '--prec', '2', '--threads', '4'], capture_output=True, text=True)
        res.update(step_rc=r.returncode, step_sec=round(time.time() - t, 1), step_bytes=os.path.getsize(stp) if os.path.exists(stp) else None)
        if r.returncode == 0 and os.path.exists(stp):
            chk = f'{d}/m.check.json'; t = time.time()
            r = subprocess.run([PY, f'{KIT}/step_check.py', stp, chk, '--parts', f'{d}/step_parts.jsonl.gz'], capture_output=True, text=True)
            v = json.load(open(chk)) if os.path.exists(chk) else {}
            res['step_check'] = {k: v.get(k) for k in ('read_status', 'roots', 'transferred', 'solids', 'checked', 'valid', 'invalid', 'nonpos_vol',
                                                       'invalid_frac', 'products', 'approx_products', 'faces', 'bbox')}
            res['check_sec'] = round(time.time() - t, 1)
        else:
            res['step_err'] = (r.stderr or '')[-800:]
    o = f'full/{os.path.basename(KIT)}/{i12}.json'
    json.dump(res, open(o, 'w'), indent=1, default=str)
    subprocess.run(['aws', 's3', 'cp', '--quiet', o, f'{S3OUT}/{os.path.basename(KIT)}/'])
    for f in (ifc, stp):          # keep disk use low; the summary carries the numbers
        if os.path.exists(f): os.remove(f)
    print(json.dumps({k: res.get(k) for k in ('id', 'kit', 'convert_status', 'step_rc', 'ifc_hole_profiles')})[:600], flush=True)
