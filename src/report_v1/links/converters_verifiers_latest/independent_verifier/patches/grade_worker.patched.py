#!/usr/bin/env python3
"""Zenitude-data-3 grading of REUSED conversions (Disk-1/2 / data-4 STEP whose source content data-3 holds too, proven by sha256).
The reused STEP is never copied; only grading artifacts are written.

Job list  _state/conv/grade/jobs.json (bim)   one job per reused model: {id: <pipe>-<content id>, pipeline, step_key, result_key, ...}
Result    _state/conv/grade/results/<id>.json  (status ok = graded; signals for the index builder)
Detail    _state/conv/grade/detail/<id>.{census.json, src_parts.jsonl.gz, step_parts.jsonl.gz, check.json}
Render    _state/conv/grade/renders/<id>.png  (SDS2: the existing preview PNG is referenced instead)

IFC   source census (ifc_census on the source IFC) + step_check of the reused STEP + join (by name: older writers put no GlobalId)
DB1   re-decode the source (same decoder; per-part inventory; no STEP written) + census of the decoder IFC + step_check of the reused
      STEP + join by name;  Windows-pipeline outputs: their own counts (parts / solids written / failed / bolts) + step_check
SDS2  converter counts from the earlier result + per-piece builders from its _pieces.csv / _skipped.csv + render ink of its preview
"""
import os, sys, re, json, time, gzip, zipfile, shutil, collections
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import convfleet as cf
import grade_join

CODE = 'z3-grade-2026-10-01d+svb'
W = os.environ.get('CONV_HOME', '/opt/conv')
PY = os.path.join(W, 'env/bin/python'); PY84 = os.path.join(W, 'ifc84/bin/python')
CHECK = os.path.join(HERE, 'step_check.py'); CENSUS = os.path.join(HERE, 'ifc_census.py')
BIG = os.path.join(HERE, 'step_verify_big.py')     # streamed read-back: same signals as step_check, bounded memory
SVB_WORKERS = int(os.environ.get('SVB_WORKERS', '4')); SVB_MEM_GB = float(os.environ.get('SVB_MEM_GB', '8'))
DET = cf.ROOT + '/_state/conv/grade/detail'; REN = cf.ROOT + '/_state/conv/grade/renders'
RB_MAX = int(os.environ.get('RB_MAX_MB', '1024')) << 20
FILES = ('worker.py', 'convfleet.py', 'step_check.py', 'ifc_census.py', 'grade_join.py', 'db1dec.py', 'db1step.py', 'db1old.py', 'db1bolts.py',
         'convert_one.py', 'layouts.json', 'step_verify_big.py', 'ifc_attrib.py')
LAYOUTS = json.load(open(os.path.join(HERE, 'layouts.json')))
GRATING = re.compile(r'^(GT|GR|GRTG|GRATING|BAR\s*GRATING)', re.I)


def tail_of(p, n=1500):
    try:
        return open(p, errors='replace').read()[-n:]
    except Exception:
        return ''


def getj(key):
    try:
        b = cf.s3.get_object(Bucket=cf.B, Key=key)['Body'].read()
        if b[:2] == b'\x1f\x8b':
            b = gzip.decompress(b)
        return json.loads(b)
    except Exception:
        return None


def need_bytes(job):
    sb = job.get('step_bytes') or 0
    return max(4 << 30, (job.get('size') or 0) * 16, sb * 40 if sb < RB_MAX else int((SVB_MEM_GB + 1) * (1 << 30)))


def need_disk(job):
    return max(4 << 30, (job.get('size') or 0) * 8 + (job.get('step_bytes') or 0) * 2)


def step_size(key):
    try:
        return cf.s3.head_object(Bucket=cf.B, Key=key)['ContentLength']
    except Exception:
        return None


FAR_RE = re.compile(r"[(,]\s*-?\d{8,}")      # as step_check: a CARTESIAN_POINT coordinate >= 1e7 mm (10 km) from the origin
CP_RE = re.compile(r"CARTESIAN_POINT\('[^']*',\(([^)]*)\)\)")


def far_translate(stp, d):
    """step_check's far-coordinate read for the streamed path (verifier 06:30Z: step_verify_big read far STEPs in place:
    1,617 vs 1,579 invalid on a 1.17 GB file): when the file has points >= 10 km from the origin (and no MAPPED_ITEM), a copy with
    every 3D CARTESIAN_POINT shifted by the whole km of the first far point (exact decimal, rigid translation) -> (path, OFF, n)"""
    from decimal import Decimal
    import math
    far, first, mapped = 0, None, False
    with open(stp, 'r', encoding='latin-1') as f:
        for line in f:
            if 'MAPPED_ITEM(' in line:
                mapped = True
            if 'CARTESIAN_POINT' in line and FAR_RE.search(line):
                far += 1
                if first is None:
                    for m_ in CP_RE.finditer(line):
                        if m_.group(1).count(',') == 2 and FAR_RE.search('(' + m_.group(1)):
                            first = [float(v_) for v_ in m_.group(1).split(',')]; break
    if not far or first is None or mapped:
        return stp, None, far
    off = [int(math.floor(v_ / 1e6) * 1e6) for v_ in first]; D_ = [Decimal(v_) for v_ in off]

    def _sh(m_):
        vals = m_.group(1).split(',')
        if len(vals) != 3 or all(float(v_) == 0.0 for v_ in vals):
            return m_.group(0)
        res_ = []
        for k_, v_ in enumerate(vals):
            x_ = format(Decimal(v_.strip()) - D_[k_], 'f')
            res_.append(x_ if '.' in x_ else x_ + '.')
        return m_.group(0)[:m_.start(1) - m_.start(0)] + ','.join(res_) + '))'
    out = os.path.join(d, 'farcopy.step')
    with open(stp, 'r', encoding='latin-1') as f, open(out, 'w', encoding='latin-1') as g:
        for line in f:
            g.write(CP_RE.sub(_sh, line) if 'CARTESIAN_POINT' in line else line)
    return out, off, far


def streamed_check(fl, jid, stp, chk, parts, d):
    """OCC read-back of a STEP too large for one read (>= RB_MAX, or memory-killed twice): step_verify_big.py reads it in
    self-contained chunks under SVB_MEM_GB and writes step_check's JSON / parts records (no render).
    Exit codes (verifier 06:30Z): 0 = verified; 2 = assembly STEP, which the streamed reader declines by design (JSON with
    'skipped') -> not verified (class 2 not_read_back_large_file); any other rc (crash, timeout, memory) -> not verified too,
    never a read failure (a reader that did not finish says nothing about the file)"""
    # (verifier 10:10Z) in place first, like step_check: the translated copy only when the in-place streamed read fails
    def _svb(path):
        return fl.run(jid, [PY, BIG, path, chk, '--parts', parts, '--workers', str(SVB_WORKERS), '--mem-gb', str(SVB_MEM_GB),
                            '--workdir', os.path.join(d, 'svb')], os.path.join(d, 'val.log'), 12 * 3600)
    rc = _svb(stp); off = None; far = 0
    if rc not in (0, 2):
        rd, off, far = far_translate(stp, d)
        if rd != stp:
            try:
                shutil.rmtree(os.path.join(d, 'svb'), ignore_errors=True)
                rc = _svb(rd)
            finally:
                try:
                    os.remove(rd)
                except OSError:
                    pass
        else:
            off = None
    v = None
    if rc in (0, 2):
        try:
            v = json.load(open(chk))
        except Exception:
            v = None
    if v is None or (rc != 0 and 'skipped' not in v):
        v = {'read_status': None, 'skipped': f'streamed read-back did not finish (rc {rc})', 'rc': rc, 'streamed': True,
             'log': tail_of(os.path.join(d, 'val.log'), 300)}
    elif rc == 2:
        v['not_verified'] = 'assembly STEP (streamed reader declines assemblies)'
    if off is not None:
        v['translated_for_check_mm'] = off; v['far_points'] = far
        if isinstance(v.get('bbox'), list) and len(v['bbox']) == 6:
            v['bbox'] = [round(x + off[k % 3], 3) for k, x in enumerate(v['bbox'])]
        if os.path.exists(parts):
            try:
                tmp = parts + '.shift'
                with gzip.open(parts, 'rt') as a, gzip.open(tmp, 'wt') as b:
                    for line in a:
                        rec = json.loads(line)
                        if isinstance(rec.get('bbox'), list) and len(rec['bbox']) == 6:
                            rec['bbox'] = [round(x + off[k % 3], 2) for k, x in enumerate(rec['bbox'])]
                        b.write(json.dumps(rec) + '\n')
                os.replace(tmp, parts)
            except Exception:
                pass
    return v


def check_step(fl, jid, key, d, title):
    """download + step_check -> (check dict, parts path or None, png path or None)"""
    n = step_size(key)
    if n is None:
        return {'error': 'reused STEP missing', 'key': key}, None, None
    stp = os.path.join(d, 'reused.step'); chk = os.path.join(d, 'check.json'); parts = os.path.join(d, 'step_parts.jsonl.gz'); png = os.path.join(d, 'render.png')
    cf.s3.download_file(cf.B, key, stp)
    if n < RB_MAX:
        rc = fl.run(jid, [PY, CHECK, stp, chk, '--png', png, '--parts', parts, '--title', title], os.path.join(d, 'val.log'), 4 * 3600)
        if rc == -9:                              # memory kill: once more without the render (read-back only)
            rc = fl.run(jid, [PY, CHECK, stp, chk, '--parts', parts], os.path.join(d, 'val.log'), 4 * 3600)
        if rc == -9:                              # memory kill again: streamed read-back (bounded memory)
            v = streamed_check(fl, jid, stp, chk, parts, d)
        else:
            try:
                v = json.load(open(chk)) if rc == 0 else {'error': f'read-back rc {rc}', 'rc': rc}
            except Exception:
                v = {'error': f'read-back rc {rc}', 'rc': rc, 'log': tail_of(os.path.join(d, 'val.log'), 300)}
    else:
        v = streamed_check(fl, jid, stp, chk, parts, d)
    v['step_bytes'] = n
    os.remove(stp)
    return v, (parts if os.path.exists(parts) else None), (png if os.path.exists(png) else None)


def unpack_ifc(raw, d):
    with open(raw, 'rb') as f:
        head = f.read(4)
    if head == b'PK\x03\x04':
        with zipfile.ZipFile(raw) as z:
            infos = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(('.ifc', '.ifcxml'))] or \
                    [i for i in z.infolist() if not i.is_dir()]
            m = max(infos, key=lambda i: i.file_size)
            out = os.path.join(d, 'src_unz.ifc')
            with z.open(m) as a, open(out, 'wb') as b:
                shutil.copyfileobj(a, b, 1 << 24)
            return out
    if head[:2] == b'\x1f\x8b':
        out = os.path.join(d, 'src_gunz.ifc')
        with gzip.open(raw) as a, open(out, 'wb') as b:
            shutil.copyfileobj(a, b, 1 << 24)
        return out
    return raw


def census(fl, jid, src, d, rec):
    cj = os.path.join(d, 'census.json'); cparts = os.path.join(d, 'src_parts.jsonl.gz')
    for py in (PY, PY84):
        if not os.path.exists(py):
            continue
        rc = fl.run(jid, [py, CENSUS, src, cj, '--parts', cparts], os.path.join(d, 'census.log'), 3 * 3600)
        if rc == 0 and os.path.exists(cj):
            rec['census'] = json.load(open(cj)); rec['census']['kernel'] = os.path.basename(os.path.dirname(os.path.dirname(py)))
            return cj, cparts
        if rc == -9:
            raise MemoryError()
    rec['census'] = {'error': 'census failed on both kernels', 'log': tail_of(os.path.join(d, 'census.log'), 400)}
    return None, None


def upload_detail(fl, jid, d, names):
    for nm in names:
        p = os.path.join(d, nm)
        if os.path.exists(p):
            fl.upload(p, f'{DET}/{jid}.{nm}')


def grade_ifc(fl, job, d, rec):
    jid = job['id']
    prior = getj(job['result_key']) or {}
    rec['prior_result'] = {k: prior.get(k) for k in ('status', 'reason', 'code', 'converter', 'grade', 'input_fix', 'excluded_elements', 'finished')}
    rec['prior_result']['stats'] = {k: (prior.get('stats') or prior.get('step') or {}).get(k) for k in
                                    ('parts', 'transcode_products', 'tess_products', 'transcode_no_body_rep', 'bbox', 'bbox_mm', 'file_length_unit', 'schema')}
    rec['prior_result']['readback'] = prior.get('readback') or prior.get('validate')
    raw = os.path.join(d, 'src.bin')
    cf.s3.download_file(cf.B, job['input_key'], raw)
    got = cf.sha256_file(raw)
    if got != job['sha256']:
        return dict(rec, status='fail', reason='input_sha_mismatch', transient=True, error=got)
    src = unpack_ifc(raw, d)
    cj, cparts = census(fl, jid, src, d, rec)
    v, sparts, png = check_step(fl, jid, job['step_key'], d, f"reused {job.get('reuse_from')}  {jid[:20]}  {(job.get('paths') or [''])[0][-80:]}")
    rec['validate'] = {k: x for k, x in v.items() if k != 'invalid_examples'}; rec['validate']['invalid_examples'] = (v.get('invalid_examples') or [])[:10]
    if cparts and sparts:
        rec['join'] = grade_join.join(grade_join.load(cparts), grade_join.load(sparts))
        j = rec['join']
        if j.get('mode') == 'gid' and (j.get('surface_parts') or ((j.get('coverage') or {}).get('all') or 1) < 1):
            # [z3v rules 1-3] cause attribution of surface / missing parts (ifc_attrib.py); build_index reads rec['attrib']
            ap_ = os.path.join(d, 'attrib.json')
            rc = fl.run(jid, [PY, os.path.join(HERE, 'ifc_attrib.py'), src, cparts, sparts, ap_, '--unpack-dir', d], os.path.join(d, 'attrib.log'), 2 * 3600)
            try:
                rec['attrib'] = json.load(open(ap_))
            except Exception:
                rec['attrib'] = {'error': f'attrib rc {rc}', 'log': tail_of(os.path.join(d, 'attrib.log'), 300)}
    if png:
        fl.upload(png, f'{REN}/{jid}.png', 'image/png'); rec['render_key'] = f'{REN}/{jid}.png'
    upload_detail(fl, jid, d, ('census.json', 'src_parts.jsonl.gz', 'step_parts.jsonl.gz', 'check.json', 'attrib.json'))
    rec['status'] = 'ok'
    return rec


def grade_db1(fl, job, d, rec):
    jid = job['id']
    prior = getj(job['result_key']) or {}
    db1 = os.path.join(d, 'in.db1')
    cf.s3.download_file(cf.B, job['input_key'], db1)
    got = cf.sha256_file(db1)
    if got != job['sha256']:
        return dict(rec, status='fail', reason='input_sha_mismatch', transient=True, error=got)
    if job.get('reuse_from') == 'disk-1/2-windows':
        pm = prior.get('pipeline_manifest') or {}
        rec['prior_result'] = {'status': prior.get('status'), 'qa_verdict': prior.get('qa_verdict'), 'manifest': pm}
        # the Windows pipeline's STEP sits under the same by-sha256 prefix: find it
        pre = job['result_key'].rsplit('/', 1)[0] + '/'
        keys = [o['Key'] for p in cf.s3.get_paginator('list_objects_v2').paginate(Bucket=cf.B, Prefix=pre) for o in p.get('Contents', [])]
        steps = [k for k in keys if k.lower().endswith(('.step', '.stp'))]
        if not steps:
            return dict(rec, status='fail', reason='reused_step_missing', detail=pre)
        job['step_key'] = rec['step_key'] = steps[0]
    else:
        rec['prior_result'] = {k: prior.get(k) for k in ('status', 'reason', 'code', 'engine', 'convert', 'step', 'excluded_elements', 'finished')}
        rec['prior_result']['validate'] = prior.get('validate')
    # re-decode (same decoder as the reused run for data-4 / Disk-1/2 v2; for Windows outputs the python decoder gives the inventory)
    raw = open(db1, 'rb').read(1 << 16)
    import zlib
    data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    m = re.search(rb'(\d+\.\d+)', data[:16]); eng = m.group(1).decode() if m else None
    rec['engine'] = eng
    ifc = os.path.join(d, 'model.ifc'); stats = os.path.join(d, 'convert.json')
    if eng in LAYOUTS and LAYOUTS[eng].get('approved'):
        lp = os.path.join(d, 'layout.json'); json.dump(LAYOUTS[eng].get('layout'), open(lp, 'w'))
        vp = os.path.join(d, 'variants.json'); json.dump([v['layout'] for v in LAYOUTS.values() if v.get('layout')], open(vp, 'w'))
        rc = fl.run(jid, [PY84 if os.path.exists(PY84) else PY, os.path.join(HERE, 'convert_one.py'), db1, ifc,
                          os.path.join(HERE, 'tekla_profiles.json'), lp, stats, vp], os.path.join(d, 'decode.log'), 7200,
                    env=dict(os.environ, DB1_FULL_DISCOVERY='1'))
        if rc == -9:
            raise MemoryError()
        cs = json.load(open(stats)) if os.path.exists(stats) else {}
        rec['redecode'] = {k: v for k, v in cs.items() if k not in ('layout', 'trace')}
        plp = stats + '.parts.json.gz'
        if os.path.exists(plp):
            sys.path.insert(0, HERE)
            pl = json.load(gzip.open(plp, 'rt'))
            rec['decoded'] = decoded_summary(pl)
            fl.upload(plp, f'{DET}/{jid}.decoded_parts.json.gz')
    cparts = None
    if os.path.exists(ifc):
        cj, cparts = census(fl, jid, ifc, d, rec)
    v, sparts, png = check_step(fl, jid, job['step_key'], d, f"reused {job.get('reuse_from')}  {jid[:20]}  {(job.get('paths') or [''])[0][-80:]}")
    rec['validate'] = {k: x for k, x in v.items() if k != 'invalid_examples'}; rec['validate']['invalid_examples'] = (v.get('invalid_examples') or [])[:10]
    if cparts and sparts:
        rec['join'] = grade_join.join(grade_join.load(cparts), grade_join.load(sparts))
    if png:
        fl.upload(png, f'{REN}/{jid}.png', 'image/png'); rec['render_key'] = f'{REN}/{jid}.png'
    upload_detail(fl, jid, d, ('census.json', 'src_parts.jsonl.gz', 'step_parts.jsonl.gz', 'check.json'))
    rec['status'] = 'ok'
    return rec


def decoded_summary(pl):
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


def piece_inventory_text(pieces_txt, skipped_txt, s2):
    import csv, io
    mem = set(); mem_env = set(); mem_exact = set(); pieces = collections.Counter(); builders = collections.Counter()
    skipped = collections.Counter(); skipped_kind = collections.Counter(); st = collections.Counter()
    if pieces_txt:
        for r in csv.DictReader(io.StringIO(pieces_txt)):
            m = r.get('member'); kind = r.get('kind') or ''; b = r.get('builder') or ''; nm = (r.get('name') or '').strip(); mt = (r.get('member_type') or '').upper()
            mem.add(m); pieces[kind] += 1; builders[b] += 1
            if kind == 'member':
                mem_env.add(m)
                st[('joist_as_envelope_box', 'joist ' + (nm or mt)) if 'joist' in b else ('member_as_envelope', f'{mt or "member"} without piece data')] += 1
            elif b in ('plate_fallback', 'profile_fallback'):
                st[(f'{b}_approximate_no_holes', f'{kind} {nm.split()[0] if nm else ""}'.strip())] += 1
            elif kind == 'concrete':
                st[('concrete_as_prism', 'concrete footing/slab')] += 1
            if kind in ('plate', 'rolled') and GRATING.match(nm):
                st[('grating_as_solid_panel', 'bar grating ' + nm[:20])] += 1
            if kind == 'rolled' and b == 'exact_brep':
                mem_exact.add(m)
    if skipped_txt:
        for r in csv.DictReader(io.StringIO(skipped_txt)):
            skipped[r.get('reason') or '?'] += 1; skipped_kind[r.get('kind') or '?'] += 1; mem.add(r.get('member'))
    if s2.get('bolts_nominal'):
        st[('nominal_bolt_from_hole_stack', 'bolt (head side/length guessed)')] += s2['bolts_nominal']
    cb = pieces.get('plate', 0) + pieces.get('fastener', 0); cs_ = skipped_kind.get('plate', 0) + skipped_kind.get('fastener', 0)
    rb = pieces.get('rolled', 0); rs = skipped_kind.get('rolled', 0)
    return {'members_in_job': len(mem - {None, ''}), 'members_with_pieces': len(mem_exact), 'members_envelope_only': len(mem_env),
            'pieces_by_kind': dict(pieces), 'builders': dict(builders), 'skipped_by_reason': dict(skipped), 'skipped_by_kind': dict(skipped_kind),
            'coverage_connections': round(cb / (cb + cs_), 4) if cb + cs_ else None,
            'coverage_rolled': round(rb / (rb + rs), 4) if rb + rs else None,
            'standins': [{'type': k[0], 'real_type': k[1], 'count': n} for k, n in st.most_common(40)], 'standins_total': sum(st.values()),
            'pieces_csv': bool(pieces_txt)}


def png_ink_bytes(b):
    try:
        import io
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.image as mpimg
        im = mpimg.imread(io.BytesIO(b), format='png')
        if im.dtype != 'uint8':
            im = (im[:, :, :3] * 255).astype('uint8')
        h = im.shape[0]
        return round(float(((im[int(h * 0.08):, :, :3] < 245).any(axis=2)).mean()), 4)
    except Exception:
        return None


def get_text(key):
    try:
        return cf.s3.get_object(Bucket=cf.B, Key=key)['Body'].read().decode('utf-8', 'replace')
    except Exception:
        return None


def grade_sds2(fl, job, d, rec):
    jid = job['id']
    if job.get('reuse_from') == 'data-4':
        prior = getj(job['result_key']) or {}
        s2 = prior.get('stage2') or {}
        rec['prior_result'] = {k: prior.get(k) for k in ('status', 'reason', 'code', 'qa', 'qa_reasons', 'version', 'validate', 'accepted')}
    else:
        prior = job.get('run2_row') or {}
        s2 = prior.get('stage2') or {}
        rec['prior_result'] = {k: prior.get(k) for k in ('status', 'qa', 'qa_reasons', 'version', 'archive', 'job_root', 'name', 's3')}
    rec['stage2'] = s2
    pre = (job.get('prefix') or job['step_key'].rsplit('/', 1)[0] + '/').rstrip('/') + '/'
    keys = [o for p in cf.s3.get_paginator('list_objects_v2').paginate(Bucket=cf.B, Prefix=pre) for o in p.get('Contents', [])]
    by = {o['Key'].rsplit('/', 1)[-1]: o for o in keys}
    stepk = [k for k in by if k.endswith('_stage2.step')]
    if not stepk:
        return dict(rec, status='fail', reason='reused_step_missing', detail=pre)
    rec['step_key'] = pre + stepk[0]; rec['step_bytes'] = by[stepk[0]]['Size']
    pcsv = next((pre + k for k in by if k.endswith('_stage2_pieces.csv')), None)
    scsv = next((pre + k for k in by if k.endswith('_stage2_skipped.csv')), None)
    prev = next((pre + k for k in by if k.endswith('_stage2_preview.png')), None)
    logk = next((pre + k for k in by if k.endswith('_stage2.log')), None)
    rec['inventory'] = piece_inventory_text(get_text(pcsv) if pcsv else None, get_text(scsv) if scsv else None, s2)
    if logk:
        txt = get_text(logk) or ''
        m = re.search(r'assembly: (\d+) products, (\d+) placed solids', txt)
        if m:
            rec['inventory']['assembly_products'] = int(m.group(1)); rec['inventory']['placed_solids'] = int(m.group(2))
        m = re.findall(r'model bbox \(in\): min \[([^\]]*)\] max \[([^\]]*)\]', txt)
        if m:
            try:
                lo = [float(x) for x in m[-1][0].split()]; hi = [float(x) for x in m[-1][1].split()]
                rec['bbox_mm'] = [round(v * 25.4, 1) for v in lo + hi]
            except ValueError:
                pass
    ink = None
    if prev:
        try:
            ink = png_ink_bytes(cf.s3.get_object(Bucket=cf.B, Key=prev)['Body'].read())
        except Exception:
            pass
        rec['render_key'] = prev
    solids, valid = s2.get('solids'), s2.get('valid')
    rec['validate'] = {'read_status': 'ok' if solids is not None and valid is not None else None, 'solids': solids, 'valid': valid,
                       'invalid': (solids - valid) if solids is not None and valid is not None else None, 'steel_ratio': s2.get('steel_ratio'),
                       'render_ink': ink, 'bbox_mm': rec.get('bbox_mm'), 'by': 'converter verify (OCP read-back, BRepCheck per placed solid) of the reused run'}
    rec['status'] = 'ok'
    return rec


def final_job(fl, job, d):
    """final grading pass: census v2 refresh + re-join (IFC), or OCC read-back + render on a quiet box (any pipeline)"""
    jid = job['id']
    rec = {'pipeline': job['pipeline'], 'model_id': job['model_id'], 'final_kind': job['kind'], 'step_key': job.get('step_key')}
    sp_key = job.get('step_parts_key')
    if job['kind'] == 'readback':
        v, sparts, png = check_step(fl, jid, job['step_key'], d, f"final  {job['pipeline']}  {job['model_id'][:20]}")
        rec['validate'] = {k: x for k, x in v.items() if k != 'invalid_examples'}; rec['validate']['invalid_examples'] = (v.get('invalid_examples') or [])[:10]
        if png:
            fl.upload(png, f'{cf.ROOT}/_state/conv/final/renders/{jid}.png', 'image/png'); rec['render_key'] = f'{cf.ROOT}/_state/conv/final/renders/{jid}.png'
        if sparts:
            fl.upload(sparts, f'{cf.ROOT}/_state/conv/final/detail/{jid}.step_parts.jsonl.gz'); sp_key = f'{cf.ROOT}/_state/conv/final/detail/{jid}.step_parts.jsonl.gz'
            rec['step_parts_key'] = sp_key
        src_key = job.get('src_parts_key')
        if sparts and src_key:
            try:
                src = grade_join.load_bytes(cf.s3.get_object(Bucket=cf.B, Key=src_key)['Body'].read())
                rec['join'] = grade_join.join(src, grade_join.load(sparts))
            except Exception as e:
                rec['join_error'] = f'{type(e).__name__}: {str(e)[:160]}'
        rec['status'] = 'ok'
        return rec
    if job['kind'] == 'census':
        raw = os.path.join(d, 'src.bin')
        cf.s3.download_file(cf.B, job['input_key'], raw)
        if job.get('sha256') and cf.sha256_file(raw) != job['sha256']:
            return dict(rec, status='fail', reason='input_sha_mismatch', transient=True)
        src = unpack_ifc(raw, d)
        cj, cparts = census(fl, jid, src, d, rec)
        if cparts:
            fl.upload(cparts, f'{cf.ROOT}/_state/conv/final/detail/{jid}.src_parts.jsonl.gz'); rec['src_parts_key'] = f'{cf.ROOT}/_state/conv/final/detail/{jid}.src_parts.jsonl.gz'
        if cparts and sp_key:
            try:
                stp = grade_join.load_bytes(cf.s3.get_object(Bucket=cf.B, Key=sp_key)['Body'].read())
                rec['join'] = grade_join.join(grade_join.load(cparts), stp)
            except Exception as e:
                rec['join_error'] = f'{type(e).__name__}: {str(e)[:160]}'
        rec['status'] = 'ok'
        return rec
    return dict(rec, status='fail', reason='unknown_final_kind')


def process(fl, job, d):
    if job.get('final'):
        return final_job(fl, job, d)
    rec = {'pipeline': job['pipeline'], 'reused': True, 'reuse_from': job.get('reuse_from'), 'step_key': job.get('step_key'),
           'result_key': job.get('result_key'), 'sha256': job.get('sha256'), 'fpc': job.get('fpc'), 'n_paths': job.get('n_paths'),
           'paths_sample': (job.get('paths') or [])[:3]}
    p = job['pipeline']
    if p == 'ifc':
        return grade_ifc(fl, job, d, rec)
    if p == 'db1':
        return grade_db1(fl, job, d, rec)
    if p == 'sds2':
        return grade_sds2(fl, job, d, rec)
    return dict(rec, status='fail', reason='unknown_pipeline')


if __name__ == '__main__':
    PIPE_NAME = 'final' if os.path.basename(HERE) == 'final' else 'grade'
    os.environ.setdefault('CONV_SLOTS', str(max(2, (os.cpu_count() or 4) // 2)))
    if PIPE_NAME == 'final':
        # (verifier 06:30Z) the grade fleet's reservation (40x STEP bytes for a full read, the streamed reader's budget above
        # RB_MAX) instead of 60x STEP bytes (a median 128 GB per >= 1 GiB STEP throttled the final pass)
        fl = cf.Fleet('final', CODE, process, lambda j: max(8 << 30, need_bytes(j)), FILES,
                      need_disk=lambda j: max(8 << 30, (j.get('step_bytes') or 0) * 2 + (j.get('size') or 0) * 8), redo=lambda r: False)
    else:
        fl = cf.Fleet('grade', CODE, process, need_bytes, FILES, need_disk=need_disk, redo=lambda r: str(r.get('id', '')).startswith('db1-') and r.get('code') in ('z3-grade-2026-10-01a', 'z3-grade-2026-10-01b'))
    sys.exit(fl.main())
