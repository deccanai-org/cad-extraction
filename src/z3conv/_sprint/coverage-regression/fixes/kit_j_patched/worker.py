#!/usr/bin/env python3
"""Zenitude-data-3 Tekla DB1 -> STEP worker (fleet kit; data-4 decoder pipeline + data-3 grading signals).

Job list  _state/conv/db1/jobs.json (bim)   one job per distinct model DB1 sha256 (xslib.db1 libraries excluded)
Output    conversions/db1-step/<sha256>.stp (+ .check.json, .png)
Detail    _state/conv/db1/detail/<sha256>.{decoded_parts.json.gz, census.json, src_parts.jsonl.gz, step_parts.jsonl.gz}
Result    _state/conv/db1/results/<sha256>.json
Grading signals: decoder inventory per part (category member / connection / other, written or skipped + reason, bolt
groups, catalog misses), STEP check (OCC read-back per root, BRepCheck + volume per solid, bbox, render), join of the
decoder's intermediate IFC (expected analytic volume per part) with the STEP by GlobalId.

Same pipeline as the finished Disk-1/2 run (cad-disk-extract/_control/db1-v2, code db1-2026-09-25g + cut-snap + arc2):
decode (db1dec: version layout re-verified per file, variants of every approved engine) -> IFC of Tekla-exact
extrusions (db1step: member axis agreement >= 0.9, COLUMN parts vertical, plausible profiles, cut-frame snapping,
edge-by-edge arcs) -> ifc2step5.py --mode hybrid --prec 2 --threads 4 on ifcopenshell 0.8.4.post1 -> kernel crash /
hang: bisect + exclude the culprit elements (<= max(50, 1%)) -> flavour markers + OCC read-back + bbox check.
A DB1 is self-contained (model database file; no sibling files are read). Engines not in layouts.json are
recorded as unapproved_engine (never guessed).
"""
import os, sys, re, json, time, gzip, zlib, collections, hashlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import convfleet as cf

CODE = 'z3-db1-2026-10-01j'
# z3 j: i + profile overlay v2 (36 of 52 profile reasons cleared; L150*90*9 global, D<d> rounds proven by report weights, zero /
#       denormal origin records dropped) + Tekla 9.21 / 9.50 layouts (9.08 geometry, stride-381 attribute record; approved)
# z3 i: bolt geometry from the model's own assdb/screwdb catalog (bolt_catalog.json, exact), proven washer flags (d4 head, d2 nut, d3 inferred)
# z3 h: profile overlay (global + per-model, models' own profdb / reports) + db1prof fixes (Latin-1 names, ELD/EPD frustums, null records)
#       + STEP stage on ifc2step6 (outward shells, healing, per-part verification, [v6:] tags); versioned outputs + best-of
# z3 g: db1old point table keeps the clean copy of an id over stray denormal copies (axis-guard deep dive: 8/9 affected models recover their dropped parts, 6/6 controls identical)
# z3 f: decoded bolt placement (head +z, underside f6 + f10/2), assembly flags (holes-only groups, washers, nuts), washers as rings
# z3 e: hole tolerance decoded from the old-engine bolt record (holes = stored d + tolerance, as the Tekla model cuts them)
# z3 d: bolt standard decoded (material field) -> ASTM heavy hex / hex and ISO 4014/4032 head+nut tables, ASTM inch-size mapping within 1 mm, AISC / ISO 273 hole clearance
# z3 c: Tekla bolt groups + clearance holes for engines 6.87/7.01/7.24 (db1bolts; positions identical to the owner's Windows pipeline), bolts as exact faceted polyhedra, [approx: ...] tags on derived parts, profile-less 8.x records counted as bolt groups
# z3 b: parsers for older Tekla names ([h*b*tw*tf channels, U<n> -> UPN, TUBE d*t, L a*t, F.B flats); code-a results re-run
# z3 a: data-4 code d + per-part decoder records, plate/stud IFC classes, step_check, census of the decoder IFC, grade_join
# d: runtime v4 (redo entries by failure reason: download_error requeue after the extraction repair)
# c: runtime convfleet-v3 (redo list read from S3 every round instead of a watched file; hand-off without waiting)
# b: STEP writer encodes names safely (two consecutive apostrophes were written as '''' which OpenCASCADE 8.0.1 cannot lex ->
#    read-back crash) and drops zero-area loops; read-back crashes reported as readback_crash; runtime convfleet-v2
OUT = cf.ROOT + '/conversions/db1-step'
W = os.environ.get('CONV_HOME', '/opt/conv')
PY = os.path.join(W, 'env/bin/python')                 # conda env (OCC read-back)
PY84 = os.path.join(W, 'ifc84/bin/python')             # ifcopenshell 0.8.4.post1: decoder IFC writer + STEP stage
CONV = os.path.join(HERE, 'ifc2step6.py') if os.path.exists(os.path.join(HERE, 'ifc2step6.py')) else os.path.join(HERE, 'ifc2step5.py')
CHECK = os.path.join(HERE, 'step_check.py'); CENSUS = os.path.join(HERE, 'ifc_census.py')
DET = cf.ROOT + '/_state/conv/db1/detail'
RB_MAX = int(os.environ.get('RB_MAX_MB', '1024')) << 20
DEC_TIMEOUT = 7200; STEP_TIMEOUT = 21600; STALL = 1800
FILES = ('worker.py', 'convfleet.py', 'ifc2step5.py', 'ifc2step6.py', 'db1prof.py', 'tekla_profiles_overlay.json', 'bolt_catalog.json', 'step_check.py', 'ifc_census.py', 'grade_join.py', 'db1dec.py', 'db1step.py', 'db1bolts.py',
         'db1old.py', 'convert_one.py', 'ifc_crash_bisect.py', 'ifc_exclude.py', 'layouts.json')
import grade_join
CRASH = (-11, 139, -6, 134, 124, 125)
LAYOUTS = json.load(open(os.path.join(HERE, 'layouts.json')))


def catalog_overlay():
    """Tekla improver's profile overlay (real dimensions incl. angle root radius, harvested from Tekla's own IFC exports / profdb):
    newest *overlay*.json or tekla_profiles*.json under _control/z3conv/db1/v2/ -> (key, etag) or None"""
    try:
        objs = [o for p_ in cf.s3.get_paginator('list_objects_v2').paginate(Bucket=cf.CB, Prefix=f'{cf.CTLROOT}/db1/v2/') for o in p_.get('Contents', [])]
    except Exception:
        return None
    c = [o for o in objs if o['Key'].endswith('.json') and ('overlay' in o['Key'].rsplit('/', 1)[-1].lower() or o['Key'].rsplit('/', 1)[-1].lower().startswith('tekla_profiles'))]
    if not c:
        return None
    o = max(c, key=lambda o: o['LastModified'])
    return o['Key'], o['ETag'].strip('"')


OVERLAY = catalog_overlay()


def catalog_path():
    """base catalog; convert_one.py applies tekla_profiles_overlay.json (global + per-model by DB1 sha256) from the kit"""
    base = os.path.join(HERE, 'tekla_profiles.json')
    ovp = os.path.join(HERE, 'tekla_profiles_overlay.json')
    if os.path.exists(ovp):
        return base, {'file': 'tekla_profiles_overlay.json', 'md5': hashlib.md5(open(ovp, 'rb').read()).hexdigest(), 'applied_by': 'convert_one (global + per_model[sha256])'}
    if True:
        return base, None
    key, et = OVERLAY
    out = os.path.join(W, f'catalog_merged_{et[:12]}.json')
    if not os.path.exists(out):
        cat = json.load(open(base))
        ov = json.loads(cf.s3.get_object(Bucket=cf.CB, Key=key)['Body'].read())
        if isinstance(ov, dict) and isinstance(ov.get('profiles'), dict):
            ov = ov['profiles']
        n = 0
        for k, v in (ov.items() if isinstance(ov, dict) else []):
            if isinstance(v, dict) and v.get('kind') and ('dims' in v or 'pts' in v):
                cat[k] = v; n += 1
        tmp = out + '.tmp'; json.dump(cat, open(tmp, 'w')); os.replace(tmp, out)
        json.dump({'key': key, 'etag': et, 'entries': n}, open(out + '.meta', 'w'))
    try:
        meta = json.load(open(out + '.meta'))
    except Exception:
        meta = {'key': key, 'etag': et}
    return out, meta


VSUF = '.j'                                           # versioned output: a re-run never overwrites the earlier STEP (best-of)
APPROVED = {e for e, v in LAYOUTS.items() if v.get('approved')}


def redo(r):
    """code h: every model of older code re-runs (best-of keeps the earlier STEP when the new one grades worse)"""
    if r.get('code') == CODE:
        return False
    if True:
        return True
    return r.get('code') in ('z3-db1-2026-10-01a',) or str(r.get('engine')) in ('6.87', '7.01', '7.24')


def decoded_summary(pl):
    """per-part decoder records [seq, profile, category, status, how/reason, guid, n_cuts] -> counts"""
    exp = collections.Counter(); wr = collections.Counter(); sk = collections.defaultdict(collections.Counter)
    how = collections.Counter(); miss_prof = collections.Counter(); nosize = collections.Counter(); noprof = 0
    for seq, prof, cat, stt, hw, guid, nc in pl:
        exp[cat] += 1
        if stt == 'written':
            wr[cat] += 1; how[hw] += 1
        else:
            sk[cat][hw] += 1
            if hw in ('unresolved', 'implausible_profile', 'no_profile', 'writer_skip'):
                miss_prof[prof or '<none>'] += 1
            elif hw == 'profile_without_size':
                nosize[prof or '<none>'] += 1
            elif hw == 'no_profile':
                noprof += 1
    return {'expected': dict(exp), 'written': dict(wr), 'skipped': {k: dict(v) for k, v in sk.items()}, 'written_by_source': dict(how),
            'bolt_groups': sum(v.get('bolt_group_excluded', 0) for v in sk.values()),
            'grating_solid': how.get('parametric_grating', 0), 'stud_shank_only': how.get('parametric_stud_shank', 0),
            'catalog_misses': miss_prof.most_common(30), 'profiles_without_size': nosize.most_common(10), 'records_without_profile': noprof}


def need_bytes(job):
    # decode + ifc2step6, measured on the data-3 fleet (1.2 x p95 peak RSS per size bucket): < 1 MB p95 3.4 GB, 1-5 MB 12.0,
    # 5-20 MB 13.3 (max 15.7), 20-50 MB 18.1; refreshed by the coordinator (mem_buckets.json)
    mb = (job.get('size') or 0) >> 20
    for hi, gb in ((1, 4), (5, 14.4), (20, 19), (50, 24)):
        if mb < hi:
            return int(gb * (1 << 30))
    return 40 << 30


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
    rec = {'sha256': job['sha256'], 'input_key': job['input_key'], 'input_from': job.get('input_from'), 'in_bytes': job.get('size'),
           'n_paths': job.get('n_paths'), 'paths_sample': job.get('paths', [])[:3], 'siblings_sample': (job.get('siblings') or [])[:30],
           'out_key': f'{OUT}/{jid}{VSUF}.stp', 'writer': 'cut-snap', 'arc_writer': None,
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
    catp, ovmeta = catalog_path()
    rec['catalog_overlay'] = ovmeta
    rc = fl.run(jid, [dpy, os.path.join(HERE, 'convert_one.py'), db1, ifc, catp, lp, stats, vp],
                logf, DEC_TIMEOUT)
    if rc == -9: raise MemoryError()
    cs = json.load(open(stats)) if os.path.exists(stats) else {}
    if rc == 0 and cs.get('status') == 'deferred_layout':
        # large file whose layout did not verify on the fast paths: full record-layout discovery (Disk-1/2 left these)
        rec['full_discovery'] = True
        rc = fl.run(jid, [dpy, os.path.join(HERE, 'convert_one.py'), db1, ifc, catp, lp, stats, vp],
                    logf, DEC_TIMEOUT, env=dict(os.environ, DB1_FULL_DISCOVERY='1'))
        if rc == -9: raise MemoryError()
        cs = json.load(open(stats)) if os.path.exists(stats) else {}
    rec['convert_rc'] = rc; rec['convert_sec'] = round(time.time() - t, 1)
    plp = stats + '.parts.json.gz'
    if os.path.exists(plp):
        try:
            pl = json.load(gzip.open(plp, 'rt'))
            rec['decoded'] = decoded_summary(pl)
            fl.upload(plp, f'{DET}/{jid}.decoded_parts.json.gz')
        except Exception as e:
            rec['decoded'] = {'error': f'{type(e).__name__}: {str(e)[:200]}'}
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
    png = stp + '.png'; chk = stp + '.check.json'; sparts = os.path.join(d, 'step_parts.jsonl.gz')
    v = {}
    if nb < RB_MAX:
        rcv = fl.run(jid, [PY, CHECK, stp, chk, '--png', png, '--parts', sparts, '--title', f"{jid[:16]}  {(job.get('paths') or [''])[0][-90:]}"],
                     os.path.join(d, 'val.log'), 4 * 3600)
        if rcv == -9:                             # memory kill: once more without the render (read-back only)
            rcv = fl.run(jid, [PY, CHECK, stp, chk, '--parts', sparts], os.path.join(d, 'val.log'), 4 * 3600)
        try:
            v = json.load(open(chk)) if rcv == 0 else {'error': f'read-back rc {rcv}', 'rc': rcv}
        except Exception:
            v = {'error': f'read-back rc {rcv}', 'rc': rcv, 'log': tail_of(os.path.join(d, 'val.log'), 300)}
    else:
        fl.run(jid, [PY, CHECK, stp, chk, '--no-occ'], os.path.join(d, 'val.log'), 3600)
        try:
            v = json.load(open(chk))
        except Exception:
            v = {}
        v['skipped'] = f'STEP >= {RB_MAX >> 20} MB: text checks only (markers, products), no OCC read-back'
    v['flavour_ok'] = flavour; v['markers_kit'] = mk
    solids = v.get('solids') if v.get('read_status') == 'ok' else (mk['FACETED_BREP'] if 'skipped' in v else 0)
    grade = 'ok_solid' if (solids or 0) > 0 else 'empty'
    if v.get('bbox') and not cf.bbox_sane(v['bbox']):
        grade = 'bad_bbox'
    v['grade'] = grade; v['validated'] = v.get('read_status') == 'ok'
    rec['validate'] = v
    rec['step'] = {'key': rec['out_key'], 'bytes': nb, 'parts': st.get('parts'), 'faces': st.get('faces'), 'bbox_mm': st.get('bbox'),
                   'members': cs.get('members'), 'written': cs.get('written'), 'converter': os.path.basename(CONV),
                   'v6': {k: st.get(k) for k in ('levels', 'tags', 'repair', 'exact_parts', 'approx_parts', 'surface_fallback_parts') if st.get(k) is not None} or None}
    if v.get('rc') in (-11, 139, -6, 134):
        key = f'{OUT}/_readback_crash/{jid}.stp'
        try:
            fl.upload(stp, key, 'application/step'); rec['unverified_key'] = key
        except Exception:
            pass
        return dict(rec, status='fail', reason='readback_crash')
    if grade != 'ok_solid' or not flavour:
        return dict(rec, status='fail', reason={'empty': 'empty_output', 'bad_bbox': 'absurd_bbox'}.get(grade, 'bad_flavour'))
    # expected per-part volumes from the decoder's own IFC (analytic profile area x length; cut parts unchecked)
    cj = os.path.join(d, 'census.json'); cparts = os.path.join(d, 'src_parts.jsonl.gz')
    rcc = fl.run(jid, [PY, CENSUS, ifc, cj, '--parts', cparts], os.path.join(d, 'census.log'), 2 * 3600)
    try:
        rec['census'] = json.load(open(cj))
    except Exception:
        rec['census'] = {'error': f'census rc {rcc}', 'log': tail_of(os.path.join(d, 'census.log'), 400)}
    if os.path.exists(cparts) and os.path.exists(sparts):
        try:
            rec['join'] = grade_join.join(grade_join.load(cparts), grade_join.load(sparts))
        except Exception as e:
            rec['join'] = {'error': f'{type(e).__name__}: {str(e)[:200]}'}
    fl.upload(stp, rec['out_key'], 'application/step')
    if os.path.exists(chk):
        fl.upload(chk, rec['out_key'] + '.check.json', 'application/json')
    if os.path.exists(png):
        fl.upload(png, f'{OUT}/{jid}{VSUF}.png', 'image/png'); rec['render_key'] = f'{OUT}/{jid}{VSUF}.png'
    for fpath, nm in ((cj, 'census.json'), (cparts, 'src_parts.jsonl.gz'), (sparts, 'step_parts.jsonl.gz')):
        if os.path.exists(fpath):
            fl.upload(fpath, f'{DET}/{jid}{VSUF}.{nm}')
    rec['detail_prefix'] = f'{DET}/{jid}{VSUF}'
    if os.path.exists(stp + '.parts.json'):
        fl.upload(stp + '.parts.json', rec['out_key'] + '.parts.json', 'application/json')
    rec['status'] = 'ok'
    return rec


def est(r):
    """best-of key (lower is better): failure, written / decoded share, invalid + non-positive solids, stand-ins"""
    if not r or r.get('status') != 'ok':
        return (1, 0, 0, 0)
    v = r.get('validate') or {}; dec = r.get('decoded') or {}
    exp = sum((dec.get('expected') or {}).values()) or 1; wr = sum((dec.get('written') or {}).values())
    return (0, -round(wr / exp, 4), (v.get('invalid') or 0) + (v.get('nonpos_vol') or 0), (v.get('approx_products') or 0))


_process_inner = process


def process(fl, job, d):
    prev = fl.getj(f'{fl.ST}/results/{job["id"]}.json')
    new = _process_inner(fl, job, d)
    # [coverage-regression fix] compare with every ok stored result, also one already stamped with this CODE (a kept earlier
    # STEP carries the running code; a duplicate same-code run must not overwrite it with its own failure)
    if not prev or prev.get('status') != 'ok':
        return new
    if est(new) <= est(prev):
        new['alternatives'] = {prev.get('code'): {'status': prev.get('status'), 'step_key': (prev.get('step') or {}).get('key'), 'est': list(est(prev))}}
        return new
    keep = {k: v for k, v in prev.items() if k not in ('id', 'pipeline', 'code', 'runtime', 'host', 'started', 'sec', 'finished', 'size')}
    keep['alternatives'] = {CODE: {'status': new.get('status'), 'reason': new.get('reason'), 'step_key': (new.get('step') or {}).get('key'), 'est': list(est(new))}}
    keep['best_of_note'] = f'{CODE} graded worse than {prev.get("code")}: earlier STEP kept'
    return keep


if __name__ == '__main__':
    # decode is one single-threaded process per job and the STEP stage uses 4 threads: 3/4 of the cores as slots,
    # memory-gated per job (30x the DB1 size) with the watchdog as backstop (Disk-1/2 ran nproc-2 slots on r7i.16xlarge)
    os.environ.setdefault('CONV_SLOTS', str(max(1, (os.cpu_count() or 4) * 3 // 4)))
    fl = cf.Fleet('db1', CODE, process, need_bytes, FILES, need_disk=lambda j: max(2 << 30, (j.get('size') or 0) * 12), redo=redo, redo_ids_key=f'{cf.CTLROOT}/db1/redo_ids.json')
    sys.exit(fl.main())
