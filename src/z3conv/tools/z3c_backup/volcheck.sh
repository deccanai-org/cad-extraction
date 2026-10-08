#!/bin/bash
# IFC volume cross-check (owner-approved 2026-10-05 "volume rule"): for every IFC model with parts_outside_volume_tolerance, decide per
# flagged part whether the STEP reproduces the SOURCE GEOMETRY (ifcopenshell kernel volume of that IfcProduct, openings applied) within
# 0.5 % - then the 5 % miss is against the file's own stated quantity (e.g. Tekla NetVolume minus holes the geometry never had), a source
# inconsistency, not a converter defect. READ-ONLY on every input; writes only bim cad-disk-extract/_state/volcheck/<id>.json.
# Idempotent / resumable: models with a result for the same converter code are skipped. First call starts unit z3volcheck.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/volcheck; mkdir -p $D/work
if systemctl is-active -q z3volcheck; then echo "running since $(cat $D/started)"; tail -n 3 $D/log.txt; exit 0; fi
if [ -f $D/finished ]; then echo "finished $(cat $D/finished)"; tail -n 8 $D/log.txt; exit 0; fi
cat > $D/run.py <<'PYEOF'
import os, sys, json, gzip, time, signal, collections, zipfile, shutil, traceback
from multiprocessing import Pool
sys.path.insert(0, '/opt/z3c/kit/coord')
import grade_join as gj
import boto3
from botocore.config import Config
B = 'bim-proprietary-data'; OUT = 'cad-disk-extract/_state/volcheck/'; W = '/opt/volcheck/work'
ROOTS = {'d3': 'cad-disk-extract/zenitude-data-3/_state/conv', 'd4': 'cad-disk-extract/zentitude-data-4/_state/conv2'}
TOL = 0.005; MAXB = int(os.environ.get('VC_MAX_BYTES', str(1500 << 20)))
s3 = None
def init():
    global s3
    s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 10, 'mode': 'standard'}))
def getj(k):
    try:
        b = s3.get_object(Bucket=B, Key=k)['Body'].read()
        if b[:2] == b'\x1f\x8b': b = gzip.decompress(b)
        return b
    except Exception:
        return None
def vsuf(code):
    if '+s' not in (code or ''): return ''
    v = code.split('+s', 1)[1].split('+')[0]
    return '.v6' if v == '6' else '.v' + v.replace('.', '')
def outside_pairs(src, step):
    """the grader's own pairing (grade_join.join, gid mode) -> every part counted in parts_outside_volume_tolerance"""
    bypid = {}
    for s_ in step:
        if s_.get('pid') and gj.present(s_): bypid.setdefault(s_['pid'], s_)
    out = []
    for p in src:
        s_ = bypid.get(p.get('gid'))
        if s_ is None: continue
        v = s_.get('volume'); e = gj.expected_volume(p)
        if not v or not e or e <= 0 or not gj.solid(s_): continue
        bb = s_.get('bbox')
        if e < 1000.0 or (isinstance(bb, (list, tuple)) and len(bb) == 6 and min(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]) < 1.0): continue
        r = v / e
        if abs(r - 1) > 0.05:
            if p.get('an') and p.get('pt') in gj.CURVED:
                if gj.CURVED_BAND[0] <= r <= gj.CURVED_BAND[1]: continue
            out.append((p, s_, r))
    return out
def mesh_volume_mm3(shape):
    import numpy as np
    g = shape.geometry
    v = np.array(g.verts, dtype=float).reshape(-1, 3); f = np.array(g.faces, dtype=np.int64).reshape(-1, 3)
    if not len(f): return None
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return abs(float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum()) / 6.0) * 1e9      # kernel works in metres
class TO(Exception): pass
def _alarm(*a): raise TO()
def one(task):
    disk, row = task
    mid = row['id']; code = row.get('converter_code')
    key = f'{OUT}{mid}.json'
    try:
        prev = json.loads(s3.get_object(Bucket=B, Key=key)['Body'].read())
        if prev.get('converter_code') == code and prev.get('status') in ('ok', 'skipped'): return mid, prev.get('status'), prev.get('explained', 0), prev.get('outside', 0)
    except Exception:
        pass
    signal.signal(signal.SIGALRM, _alarm); signal.alarm(3600)
    wd = f'{W}/{mid[:16]}'; os.makedirs(wd, exist_ok=True)
    rec = {'id': mid, 'disk': disk, 'converter_code': code, 'step_key': row.get('step_key'), 'tol': TOL, 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'kernel': 'ifcopenshell (geom, world coords, openings applied) triangulated volume'}
    try:
        vs = vsuf(code); src = step = res = None
        for dk in ([disk] + [x for x in ROOTS if x != disk]):
            src = getj(f'{ROOTS[dk]}/ifc/detail/{mid}{vs}.src_parts.jsonl.gz'); step = getj(f'{ROOTS[dk]}/ifc/detail/{mid}{vs}.step_parts.jsonl.gz')
            res = getj(f'{ROOTS[dk]}/ifc/results/{mid}.json')
            if src and step and res: break
        if not (src and step and res):
            rec.update(status='skipped', reason='detail_or_result_missing'); raise StopIteration
        src = [json.loads(l) for l in src.decode().split('\n') if l.strip()]; step = [json.loads(l) for l in step.decode().split('\n') if l.strip()]
        res = json.loads(res)
        outs = outside_pairs(src, step)
        rec['outside'] = len(outs)
        if not outs:
            rec.update(status='ok', explained=0, unexplained=[]); raise StopIteration
        ik = res.get('input_key'); size = res.get('size') or row.get('size') or 0
        if not ik:
            rec.update(status='skipped', reason='no_input_key'); raise StopIteration
        if size > MAXB:
            rec.update(status='skipped', reason=f'input_over_{MAXB >> 20}MB'); raise StopIteration
        loc = f'{wd}/in'
        s3.download_file(B, ik, loc)
        path = loc
        if zipfile.is_zipfile(loc):
            with zipfile.ZipFile(loc) as z:
                names = [n for n in z.namelist() if n.lower().endswith('.ifc')]
                if not names: rec.update(status='skipped', reason='ifczip_without_ifc'); raise StopIteration
                z.extract(names[0], wd); path = os.path.join(wd, names[0])
        import ifcopenshell, ifcopenshell.geom
        f = ifcopenshell.open(path)
        st = ifcopenshell.geom.settings(); st.set('use-world-coords', True)
        expl, unexpl = 0, []
        for p, s_, r in outs:
            kv = None; err = None
            try:
                prod = f.by_guid(p['gid'])
                kv = mesh_volume_mm3(ifcopenshell.geom.create_shape(st, prod))
            except Exception as e:
                err = f'{type(e).__name__}: {str(e)[:80]}'
            if kv and kv > 0 and abs(s_['volume'] / kv - 1) <= TOL:
                expl += 1
            else:
                unexpl.append({'gid': p['gid'], 'cls': p.get('cls'), 'ratio_vs_stated': round(r, 4),
                               'ratio_vs_kernel': round(s_['volume'] / kv, 4) if kv else None, 'err': err})
        rec.update(status='ok', explained=expl, unexplained=unexpl[:200], n_unexplained=len(unexpl))
    except StopIteration:
        pass
    except TO:
        rec.update(status='timeout')
    except Exception as e:
        rec.update(status='error', error=f'{type(e).__name__}: {str(e)[:200]}')
    finally:
        signal.alarm(0); shutil.rmtree(wd, ignore_errors=True)
    s3.put_object(Bucket=B, Key=key, Body=json.dumps(rec).encode(), ContentType='application/json')
    return mid, rec.get('status'), rec.get('explained', 0), rec.get('outside', 0)
if __name__ == '__main__':
    init(); tasks = {}
    for disk, st in ROOTS.items():
        for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{st}/index.jsonl.gz')['Body'].read()).decode().split('\n'):
            if not l.strip(): continue
            r = json.loads(l)
            if r['pipeline'] == 'ifc' and any(str(i).startswith('parts_outside_volume_tolerance') for i in r.get('issues') or []):
                tasks.setdefault(r['id'], (disk, r))
    tl = sorted(tasks.values(), key=lambda t: (t[1].get('size') or 0))
    print('models', len(tl), flush=True)
    c = collections.Counter(); t0 = time.time()
    with Pool(int(os.environ.get('VC_PROCS', '28')), initializer=init, maxtasksperchild=20) as pool:
        for i, (mid, stt, ex, out) in enumerate(pool.imap_unordered(one, tl), 1):
            c[stt] += 1; c['parts_outside'] += out or 0; c['parts_explained'] += ex or 0
            if i % 100 == 0: print(i, dict(c), round(time.time() - t0), 's', flush=True)
    print('DONE', dict(c), flush=True)
PYEOF
date -u +%FT%TZ > $D/started
systemctl reset-failed z3volcheck 2>/dev/null
systemd-run --unit=z3volcheck --collect --nice=5 --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/conv/env/bin/python $D/run.py > $D/log.txt 2>&1; echo rc=\$? >> $D/log.txt; date -u +%FT%TZ > $D/finished"
sleep 60; echo "started: $(systemctl is-active z3volcheck)"; tail -n 3 $D/log.txt
