#!/usr/bin/env python3
"""Zentitude-data-4 Tekla DB1 -> STEP worker (fleet kit, one process per host).

Job list  _control/conv/db1/jobs.json   (one job per distinct new model DB1 sha256; xslib.db1 libraries excluded)
Output    conversions/db1-step/<sha256>.stp (+ .validate.json)
Result    _state/conv/db1/results/<sha256>.json

Same pipeline as the finished Disk-1/2 run (cad-disk-extract/_control/db1-v2, code db1-2026-09-25g + cut-snap + arc2):
decode (db1dec: version layout re-verified per file, variants of every approved engine) -> IFC of Tekla-exact
extrusions (db1step: member axis agreement >= 0.9, COLUMN parts vertical, plausible profiles, cut-frame snapping,
edge-by-edge arcs) -> ifc2step5.py --mode hybrid --prec 2 --threads 4 on ifcopenshell 0.8.4.post1 -> kernel crash /
hang: bisect + exclude the culprit elements (<= max(50, 1%)) -> flavour markers + OCC read-back + bbox check.
A DB1 is self-contained (model database file; no sibling files are read). Engines not in layouts.json are
recorded as unapproved_engine (never guessed).
"""
import os, sys, re, json, time, gzip, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import convfleet as cf

CODE = 'z4-db1-2026-09-30d'
# d: runtime v4 (redo entries by failure reason: download_error requeue after the extraction repair)
# c: runtime convfleet-v3 (redo list read from S3 every round instead of a watched file; hand-off without waiting)
# b: STEP writer encodes names safely (two consecutive apostrophes were written as '''' which OpenCASCADE 8.0.1 cannot lex ->
#    read-back crash) and drops zero-area loops; read-back crashes reported as readback_crash; runtime convfleet-v2
OUT = cf.ROOT + '/conversions/db1-step'
W = os.environ.get('CONV_HOME', '/opt/conv')
PY = os.path.join(W, 'env/bin/python')                 # conda env (OCC read-back)
PY84 = os.path.join(W, 'ifc84/bin/python')             # ifcopenshell 0.8.4.post1: decoder IFC writer + STEP stage
CONV = os.path.join(HERE, 'ifc2step5.py'); VAL = os.path.join(HERE, 'validate_step.py')
RB_MAX = int(os.environ.get('RB_MAX_MB', '256')) << 20
DEC_TIMEOUT = 7200; STEP_TIMEOUT = 21600; STALL = 1800
FILES = ('worker.py', 'convfleet.py', 'ifc2step5.py', 'validate_step.py', 'db1dec.py', 'db1step.py', 'db1old.py', 'convert_one.py',
         'ifc_crash_bisect.py', 'ifc_exclude.py', 'layouts.json')
CRASH = (-11, 139, -6, 134, 124, 125)
LAYOUTS = json.load(open(os.path.join(HERE, 'layouts.json')))
APPROVED = {e for e, v in LAYOUTS.items() if v.get('approved')}


def redo(r):
    """code-a results this code can do better: read-back crashes (recorded as empty_output by code a) and published
    outputs listed in redo_ids.json (not readable by OpenCASCADE because of the old name encoding)"""
    v = r.get('validate') or {}
    return r.get('status') != 'ok' and r.get('reason') in ('empty_output', 'readback_crash', 'bad_flavour') and bool(v.get('error'))


def need_bytes(job):
    return max(2 << 30, (job.get('size') or 0) * 30)      # measured: ~4 GB RSS at 185 MB gz early in decode


def engine_of(path):
    raw = open(path, 'rb').read(1 << 16)
    data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    m = re.search(rb'(\d+\.\d+)', data[:16])
    return m.group(1).decode() if m else None


def tail_of(p, n=2000):
    try:
        return open(p, errors='replace').read()[-n:]
    except Exception:
        return ''


def process(fl, job, d):
    jid = job['id']; logf = os.path.join(d, 'log.txt')
    db1 = os.path.join(d, 'in.db1'); ifc = os.path.join(d, 'model.ifc'); stp = os.path.join(d, 'model.stp'); stats = os.path.join(d, 'convert.json')
    rec = {'sha256': job['sha256'], 'input_key': job['input_key'], 'in_bytes': job.get('size'), 'n_paths': job.get('n_paths'),
           'paths_sample': job.get('paths', [])[:3], 'out_key': f'{OUT}/{jid}.stp', 'writer': 'cut-snap', 'arc_writer': None,
           'pipeline': 'db1dec+db1step -> ifc2step5.py --mode hybrid --prec 2 (ifcopenshell 0.8.4.post1)'}
    try:
        cf.s3.download_file(cf.B, job['input_key'], db1)
    except Exception as e:
        return dict(rec, status='fail', reason='download_error', transient=True, error=str(e)[:300])
    got = cf.sha256_file(db1)
    if got != job['sha256']:
        return dict(rec, status='fail', reason='input_sha_mismatch', transient=True, error=got)
    eng = job.get('engine') or engine_of(db1)
    rec['engine'] = eng
    if eng not in APPROVED:
        return dict(rec, status='fail', reason='unapproved_engine' if eng else 'no_engine_banner',
                    detail=f'Tekla engine {eng} has no verified record layout (approved: {sorted(APPROVED)})')
    lay = LAYOUTS[eng].get('layout')
    lp = os.path.join(d, 'layout.json'); json.dump(lay, open(lp, 'w'))
    vp = os.path.join(d, 'variants.json'); json.dump([v['layout'] for v in LAYOUTS.values() if v.get('layout')], open(vp, 'w'))
    dpy = PY84 if os.path.exists(PY84) else PY
    t = time.time()
    rc = fl.run(jid, [dpy, os.path.join(HERE, 'convert_one.py'), db1, ifc, os.path.join(HERE, 'tekla_profiles.json'), lp, stats, vp],
                logf, DEC_TIMEOUT)
    if rc == -9: raise MemoryError()
    cs = json.load(open(stats)) if os.path.exists(stats) else {}
    if rc == 0 and cs.get('status') == 'deferred_layout':
        # large file whose layout did not verify on the fast paths: full record-layout discovery (Disk-1/2 left these)
        rec['full_discovery'] = True
        rc = fl.run(jid, [dpy, os.path.join(HERE, 'convert_one.py'), db1, ifc, os.path.join(HERE, 'tekla_profiles.json'), lp, stats, vp],
                    logf, DEC_TIMEOUT, env=dict(os.environ, DB1_FULL_DISCOVERY='1'))
        if rc == -9: raise MemoryError()
        cs = json.load(open(stats)) if os.path.exists(stats) else {}
    rec['convert_rc'] = rc; rec['convert_sec'] = round(time.time() - t, 1)
    rec['convert'] = {k: v for k, v in cs.items() if k not in ('layout', 'trace')}; rec['layout'] = cs.get('layout')
    rec['arc_writer'] = cs.get('arc_writer'); rec['arc_stats'] = cs.get('arc_stats')
    if rc != 0 or cs.get('status') != 'ok':
        reason = cs.get('status') or ('convert_timeout' if rc == 124 else 'convert_fail')
        return dict(rec, status='fail', reason=reason, trace=cs.get('trace'), log_tail=tail_of(logf))
    t = time.time()
    rc = fl.run(jid, [dpy, CONV, ifc, stp, '--mode', 'hybrid', '--prec', '2', '--threads', '4'], logf, STEP_TIMEOUT, stall=STALL)
    if rc == -9: raise MemoryError()
    rec['step_rc'] = rc; rec['step_ifcopenshell'] = '0.8.4.post1' if dpy == PY84 else 'env'
    if rc in CRASH and os.path.exists(ifc):
        info = {'at': cf.now()}
        try:
            fl.run(jid, [dpy, os.path.join(HERE, 'ifc_crash_bisect.py'), ifc, CONV, '8', '120'], os.path.join(d, 'bisect.log'), 4 * 3600)
            lines = [l for l in tail_of(os.path.join(d, 'bisect.log'), 200000).splitlines() if l.startswith('{')]
            res = json.loads(lines[-1]) if lines else None
            if res is None:
                info['result'] = 'bisect produced no result'
            else:
                culprits = res['culprits']; cap = max(50, res['tessellate_set'] // 100)
                info.update(tessellate_set=res['tessellate_set'], culprits=len(culprits), bisect_sec=res['secs'])
                if not culprits:
                    info['result'] = 'no crashing element isolated'
                elif len(culprits) > cap:
                    info['result'] = f'too many crashing elements ({len(culprits)} > {cap})'
                else:
                    fixed = os.path.join(d, 'fixed.ifc')
                    r2, out, err = fl.sh([dpy, os.path.join(HERE, 'ifc_exclude.py'), ifc, fixed] + [c['guid'] for c in culprits if c.get('guid')], timeout=3600)
                    rec['excluded_elements'] = json.loads(out.strip().splitlines()[-1])
                    for f in (stp, stp + '.stats.json'):
                        if os.path.exists(f): os.remove(f)
                    rc = fl.run(jid, [dpy, CONV, fixed, stp, '--mode', 'hybrid', '--prec', '2', '--threads', '4'], logf, STEP_TIMEOUT, stall=STALL)
                    if rc == -9: raise MemoryError()
                    info['rc'] = rc
                    info['result'] = f'converted without {len(culprits)} crashing element(s)' if rc == 0 else f'still fails (rc {rc})'
        except MemoryError:
            raise
        except Exception as e:
            info['result'] = f'rescue error: {type(e).__name__}: {str(e)[:200]}'
        rec['rescue'] = info; rec['step_rc'] = rc
    rec['step_sec'] = round(time.time() - t, 1)
    st = {}
    try:
        st = json.load(open(stp + '.stats.json'))
    except Exception:
        pass
    rec['step_stats'] = {k: st.get(k) for k in ('parts', 'faces', 'points', 'bbox', 'transcode_products', 'tess_products', 'total_sec', 'peak_rss_mb', 'out_bytes')}
    if rc != 0 or not os.path.exists(stp) or os.path.getsize(stp) == 0:
        reason = {124: 'step_timeout', 125: 'step_kernel_hang'}.get(rc, 'step_kernel_crash' if rc in CRASH else 'step_fail')
        return dict(rec, status='fail', reason=reason, log_tail=tail_of(logf))
    if not cf.bbox_sane(st.get('bbox')):
        return dict(rec, status='fail', reason='absurd_bbox', bbox=st.get('bbox'))
    nb = os.path.getsize(stp); rec['out_bytes'] = nb
    mk = cf.count_markers(stp, cf.STEP_MARKERS)
    head = open(stp, errors='replace').read(3000)
    flavour = mk['ADVANCED_FACE'] == 0 and mk['TESSELLATED'] == 0 and mk['TRIANGULATED_FACE_SET'] == 0 and 'AUTOMOTIVE_DESIGN' in head
    v = {}
    if nb < RB_MAX:
        rcv = fl.run(jid, [PY, VAL, stp], os.path.join(d, 'val.log'), 3 * 3600)
        lines = [l for l in tail_of(os.path.join(d, 'val.log'), 20000).splitlines() if l.startswith('{')]
        try:
            v = json.loads(lines[-1])
        except Exception:
            v = {'error': f'read-back rc {rcv}', 'rc': rcv}
    else:
        v = {'skipped': f'STEP >= {RB_MAX >> 20} MB (marker count used)'}
    v.pop('file', None); v['markers'] = mk; v['flavour_ok'] = flavour
    solids = v.get('solids') if v.get('read_status') == 'ok' else (mk['FACETED_BREP'] if 'skipped' in v else 0)
    grade = 'ok_solid' if (solids or 0) > 0 else 'empty'
    if v.get('bbox') and not cf.bbox_sane(v['bbox']):
        grade = 'bad_bbox'
    v['grade'] = grade; v['validated'] = v.get('read_status') == 'ok'
    rec['validate'] = v
    rec['step'] = {'key': rec['out_key'], 'bytes': nb, 'parts': st.get('parts'), 'faces': st.get('faces'), 'bbox_mm': st.get('bbox'),
                   'members': cs.get('members'), 'written': cs.get('written')}
    if v.get('rc') in (-11, 139, -6, 134):
        key = f'{OUT}/_readback_crash/{jid}.stp'
        try:
            fl.upload(stp, key, 'application/step'); rec['unverified_key'] = key
        except Exception:
            pass
        return dict(rec, status='fail', reason='readback_crash')
    if grade != 'ok_solid' or not flavour:
        return dict(rec, status='fail', reason={'empty': 'empty_output', 'bad_bbox': 'absurd_bbox'}.get(grade, 'bad_flavour'))
    json.dump(v, open(stp + '.validate.json', 'w'))
    fl.upload(stp, rec['out_key'], 'application/step')
    fl.upload(stp + '.validate.json', rec['out_key'] + '.validate.json', 'application/json')
    rec['status'] = 'ok'
    return rec


if __name__ == '__main__':
    # decode is one single-threaded process per job and the STEP stage uses 4 threads: 3/4 of the cores as slots,
    # memory-gated per job (30x the DB1 size) with the watchdog as backstop (Disk-1/2 ran nproc-2 slots on r7i.16xlarge)
    os.environ.setdefault('CONV_SLOTS', str(max(1, (os.cpu_count() or 4) * 3 // 4)))
    fl = cf.Fleet('db1', CODE, process, need_bytes, FILES, need_disk=lambda j: max(2 << 30, (j.get('size') or 0) * 12), redo=redo, redo_ids_key=f'{cf.ROOT}/_control/conv/db1/redo_ids.json')
    sys.exit(fl.main())
