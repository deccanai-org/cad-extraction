#!/usr/bin/env python3
"""Zenitude-data-3 SDS/2 job folder -> STEP worker (fleet kit; data-4 v4 pipeline wrapper + swappable converter + grading signals).

Job list  _state/conv/sds2/jobs.json (bim)   one job per distinct converter input (fingerprint over main/jsetup, main/job_mtrl,
          mem/mem_idx, mem/<n>, subm/subm_idx, subm/<n>); files_key = model files (main/ mem/ subm/) with resolved keys
Converter converter.json in the kit: {"zip": <file in the kit>, "sha256": ..., "label": "v4" | "v5" ...}; swapping the zip
          changes CODE, and results of another converter label are re-opened by redo() (failures by default, everything with
          {"redo_all": true} in converter.json)
Output    conversions/sds2-step/<job id>/<name>_stage2.step (+ _pieces.csv, _skipped.csv, _preview.png, _stage2.log, job.json)
          stage 2 not publishable -> stage-2 files under conversions/sds2-step/_not_accepted/<job id>/ and a stage-1 run
          (members only) published as conversions/sds2-step/<job id>/<name>_stage1.step when it reads back valid
Result    _state/conv/sds2/results/<job id>.json  (status ok | ok_stage1 | fail)
Grading signals: converter counts (exact / plate / rolled / fastener / bolts SDS2 + nominal / skipped / envelopes / joist envelopes,
holes, steel ratio vs SDS2 weights), OCC read-back by the pipeline's verify (solids, BRep-valid per solid, bbox), per-piece
builders from _pieces.csv (stand-ins with their real type) and _skipped.csv (pieces not built + reason), render ink of the preview.
"""
import os, sys, re, json, time, shutil, hashlib, importlib.util, csv, collections, gzip
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import convfleet as cf

CONVERTER = json.load(open(os.path.join(HERE, 'converter.json')))
LABEL = CONVERTER['label']
CODE = f'z3-sds2-{LABEL}-2026-10-01a'
OUT = cf.ROOT + '/conversions/sds2-step'
SUB = '' if LABEL == 'v4' else f'/{LABEL}'           # v5+ outputs in <id>/<label>/ so the v4 files of the same job stay intact
DET = cf.ROOT + '/_state/conv/sds2/detail'
W = os.environ.get('CONV_HOME', '/opt/conv')
PY = os.path.join(W, 'sds2env/bin/python')
PIPE = os.path.join(W, f'sds2-{LABEL}', 'sds2-step-pipeline')
TIMEOUT = int(os.environ.get('SDS2_TIMEOUT_S', '14400'))
FILES = ('worker.py', 'convfleet.py', 'fetch.py', 'converter.json', CONVERTER['zip'])
GRATING = re.compile(r'^(GT|GR|GRTG|GRATING|BAR\s*GRATING)', re.I)


def ensure_pipeline():
    mark = os.path.join(W, f'sds2-{LABEL}', '.zip_sha256')
    if os.path.exists(os.path.join(PIPE, 'decode', 'sds2_to_step.py')) and os.path.exists(mark) and open(mark).read().strip() == CONVERTER['sha256']:
        return
    z = os.path.join(HERE, CONVERTER['zip'])
    h = cf.sha256_file(z)
    if h != CONVERTER['sha256']:
        raise SystemExit(f'converter zip sha256 {h} != {CONVERTER["sha256"]}')
    import zipfile
    zipfile.ZipFile(z).extractall(os.path.join(W, f'sds2-{LABEL}'))
    open(mark, 'w').write(CONVERTER['sha256'])


ensure_pipeline()
_spec = importlib.util.spec_from_file_location('run_batch', os.path.join(PIPE, 'batch', 'run_batch.py'))
RB = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(RB)


def redo(r):
    """results of another converter label: re-run those of the labels listed in converter.json redo_labels (all of them with redo_all);
    targeted re-runs of other labels come from the coordinator's redo list"""
    code = str(r.get('code', ''))
    if code.startswith(f'z3-sds2-{LABEL}-'):
        return False
    if CONVERTER.get('redo_all'):
        return True
    return any(code.startswith(f'z3-sds2-{lb}-') for lb in CONVERTER.get('redo_labels') or [])


def load_files(job):
    body = cf.s3.get_object(Bucket=cf.B, Key=job['files_key'])['Body'].read()
    try:
        body = gzip.decompress(body)
    except OSError:
        pass
    return json.loads(body)


def need_bytes(job):
    # reservation per model-size bucket = max(the lead's floor, 1.2 x p95 peak RSS) measured on the data-3 fleet at 23:50Z from done
    # jobs, running jobs' peaks so far and first memory kills: 50-100 MB p95 6.8 GB, 100-250 MB 11.2, 250-800 MB 20.6,
    # 0.8-3 GB 36.3 (110 running jobs, max 49.4). The coordinator refreshes it every round (_state/conv/sds2/mem_buckets.json).
    mb = (job.get('model_bytes') or 0) >> 20
    for hi, gb in ((50, 4), (100, 8.2), (250, 16), (800, 24.8), (3000, 43.5)):
        if mb < hi:
            return int(gb * (1 << 30))
    return 45 << 30


def need_disk(job):
    return max(4 << 30, (job.get('model_bytes') or 0) * 12)


def conv_env():
    env = dict(os.environ, PYTHONUNBUFFERED='1', MPLBACKEND='Agg')
    ex = os.path.join(W, 'sds2env', 'lib', 'libexpat.so.1')
    if os.path.exists(ex):
        env['LD_PRELOAD'] = ex
    return env


def tail_of(p, n=2000):
    try:
        return open(p, errors='replace').read()[-n:]
    except Exception:
        return ''


def parse_bbox(txt):
    m = re.findall(r'model bbox \(in\): min \[([^\]]*)\] max \[([^\]]*)\]', txt)
    if not m:
        return None
    try:
        lo = [float(x) for x in m[-1][0].split()]; hi = [float(x) for x in m[-1][1].split()]
        return lo + hi if len(lo) == 3 and len(hi) == 3 else None
    except ValueError:
        return None


def parse_extra(txt):
    """counts the v4 log prints beyond run_batch.parse_log"""
    out = {}
    m = re.search(r"solids: (\{[^}]*\})", txt)
    if m:
        try:
            out['solids_by_kind'] = json.loads(m.group(1).replace("'", '"'))
        except Exception:
            pass
    m = re.search(r'assembly: (\d+) products, (\d+) placed solids', txt)
    if m:
        out['assembly_products'] = int(m.group(1)); out['placed_solids'] = int(m.group(2))
    m = re.search(r"bolt holes \(unique pieces\): \{'pieces with holes': (\d+), 'holes': (\d+)\}", txt)
    if m:
        out['pieces_with_holes'] = int(m.group(1)); out['holes_cut'] = int(m.group(2))
    m = re.search(r'not built \(no usable geometry\): (\{[^}]*\})', txt)
    if m:
        out['not_built_names'] = m.group(1)[:400]
    m = re.search(r'with solids: (\d+); BRep valid: (\d+); non-positive volume: (\d+)', txt)
    if m:
        out['with_solids'] = int(m.group(1)); out['brep_valid'] = int(m.group(2)); out['nonpos_volume'] = int(m.group(3))
    m = re.search(r'steel pieces: solids ([\d.]+) t vs SDS2 piece weights ([\d.]+) t', txt)
    if m:
        out['steel_t'] = float(m.group(1)); out['sds2_t'] = float(m.group(2))
    out['invalid_named'] = re.findall(r'invalid after read-back: (.*)', txt)[:20]
    return out


def piece_inventory(pieces_csv, skipped_csv, s2):
    """per-piece builders -> members / connection coverage and stand-ins with their real type"""
    inv = {'members': set(), 'members_exact': set(), 'members_envelope': set(), 'pieces': collections.Counter(),
           'builders': collections.Counter(), 'skipped': collections.Counter(), 'skipped_kind': collections.Counter()}
    standins = collections.Counter()
    try:
        for r in csv.DictReader(open(pieces_csv, newline='', encoding='utf-8', errors='replace')):
            mem = r.get('member'); kind = r.get('kind') or ''; b = r.get('builder') or ''; nm = (r.get('name') or '').strip()
            mt = (r.get('member_type') or '').upper()
            inv['members'].add(mem); inv['pieces'][kind] += 1; inv['builders'][b] += 1
            if kind == 'member':
                inv['members_envelope'].add(mem)
                if 'joist' in b:
                    standins[('joist_as_envelope_box', 'joist ' + (nm or mt))] += 1
                else:
                    standins[('member_as_envelope', f'{mt or "member"} without piece data')] += 1
            elif b in ('plate_fallback', 'profile_fallback'):
                standins[(f'{b}_approximate_no_holes', f'{kind} {nm.split()[0] if nm else ""}'.strip())] += 1
            elif kind == 'concrete':
                standins[('concrete_as_prism', 'concrete footing/slab')] += 1
            if kind in ('plate', 'rolled') and GRATING.match(nm):
                standins[('grating_as_solid_panel', 'bar grating ' + nm[:20])] += 1
            if kind in ('rolled',) and b == 'exact_brep':
                inv['members_exact'].add(mem)
    except FileNotFoundError:
        pass
    try:
        for r in csv.DictReader(open(skipped_csv, newline='', encoding='utf-8', errors='replace')):
            inv['skipped'][r.get('reason') or '?'] += 1; inv['skipped_kind'][r.get('kind') or '?'] += 1
            inv['members'].add(r.get('member'))
    except FileNotFoundError:
        pass
    if s2.get('bolts_nominal'):
        standins[('nominal_bolt_from_hole_stack', 'bolt (head side/length guessed)')] += s2['bolts_nominal']
    # 7.0-7.6 joists are depth x width envelopes; nominal bolts guessed from hole stacks; welds never modelled
    conn_built = inv['pieces'].get('plate', 0) + inv['pieces'].get('fastener', 0)
    conn_skipped = inv['skipped_kind'].get('plate', 0) + inv['skipped_kind'].get('fastener', 0)
    rolled_built = inv['pieces'].get('rolled', 0); rolled_skipped = inv['skipped_kind'].get('rolled', 0)
    n_mem = len(inv['members'] - {None, ''})
    out = {'members_in_job': n_mem, 'members_with_pieces': len(inv['members_exact']), 'members_envelope_only': len(inv['members_envelope']),
           'pieces_by_kind': dict(inv['pieces']), 'builders': dict(inv['builders']), 'skipped_by_reason': dict(inv['skipped']),
           'skipped_by_kind': dict(inv['skipped_kind']),
           'coverage_connections': round(conn_built / (conn_built + conn_skipped), 4) if conn_built + conn_skipped else None,
           'coverage_rolled': round(rolled_built / (rolled_built + rolled_skipped), 4) if rolled_built + rolled_skipped else None,
           'standins': [{'type': k[0], 'real_type': k[1], 'count': n} for k, n in standins.most_common(40)],
           'standins_total': sum(standins.values())}
    return out


def png_ink(path):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.image as mpimg
        im = mpimg.imread(path)
        if im.dtype != 'uint8':
            im = (im[:, :, :3] * 255).astype('uint8')
        h = im.shape[0]
        body = im[int(h * 0.08):, :, :3]
        return round(float(((body < 245).any(axis=2)).mean()), 4)
    except Exception:
        return None


def manifest_summary(path):
    """v5 sidecar -> compact grading record (labels of every stand-in stay in the uploaded manifest file)"""
    try:
        m = json.load(open(path))
    except Exception as e:
        return {'error': f'{type(e).__name__}: {str(e)[:120]}'}
    st = m.get('standins') or {}
    sk = m.get('skipped')
    skc = collections.Counter(); skd = {}
    if isinstance(sk, list):
        for x in sk:
            skc[(x.get('reason') if isinstance(x, dict) else str(x))[:80]] += 1
    elif isinstance(sk, dict):
        if isinstance(sk.get('by_reason'), dict):
            skc.update({str(k)[:80]: (v if isinstance(v, int) else len(v) if isinstance(v, list) else 1) for k, v in sk['by_reason'].items()})
            skd = {'total': sk.get('total'), 'by_reason': dict(skc)}
        else:
            skc.update({k: (v if isinstance(v, int) else len(v) if isinstance(v, list) else 1) for k, v in sk.items() if k not in ('total', 'parts')})
    wc = m.get('weight_check') or {}
    return {'schema': m.get('schema'), 'converter': m.get('converter'), 'version': m.get('version'), 'counts': m.get('counts'),
            'empty_job_proof': m.get('empty_job_proof'),
            'standins_by_type': st.get('by_type'), 'standins_total': st.get('total'),
            'standin_groups': [{k: g.get(k) for k in ('type', 'real_type', 'reason', 'count', 'needed')} for g in (st.get('groups') or [])][:60],
            'skipped_by_reason': dict(skc), 'skipped_detail': skd, 'converter_duplicates': len(m.get('converter_duplicates') or []) if isinstance(m.get('converter_duplicates'), list) else m.get('converter_duplicates'),
            'weight': {'ratio': wc.get('ratio'), 'ratio_without_outliers': wc.get('ratio_without_outliers'),
                       'dominant_outliers': (wc.get('dominant_outliers') or [])[:10] if isinstance(wc.get('dominant_outliers'), list) else wc.get('dominant_outliers'),
                       'step_steel_t': wc.get('step_steel_t'), 'sds2_piece_weight_t': wc.get('sds2_piece_weight_t'),
                       'joist_standin_t': wc.get('joist_standin_t'),
                       'by_family': {k: {'ratio': v.get('ratio'), 'n': v.get('n')} for k, v in (wc.get('by_family') or {}).items()}},
            'readback': m.get('readback'), 'class': m.get('class'), 'corpus': m.get('corpus'), 'class_reasons': m.get('class_reasons')}


def est_class(r):
    """same intent as the index rules, for the best-of choice between converter versions: (class, invalid, skipped, |ratio-1|)"""
    if not r or r.get('status') not in ('ok', 'ok_stage1'):
        return (4, 0, 0, 0)
    if r.get('status') == 'ok_stage1':
        return (2.5, 0, 0, 0)
    v = r.get('validate') or {}; s2 = r.get('stage2') or {}; inv = r.get('inventory') or {}; man = r.get('manifest') or {}
    bad = v.get('invalid') or 0
    skipped = sum((man.get('skipped_by_reason') or {}).values()) if man else sum((inv.get('skipped_by_reason') or {}).values())
    st = (man.get('standins_total') if man else inv.get('standins_total')) or 0
    w_ = (man.get('weight') or {}) if man else {}
    ratio = (w_.get('ratio_without_outliers') or w_.get('ratio')) if man else s2.get('steel_ratio')
    if ratio is not None and not 0.5 <= ratio <= 1.5:
        c = 3
    elif bad or skipped or st or (ratio is not None and not 0.95 <= ratio <= 1.05):
        c = 2
    else:
        c = 1
    return (c, bad, skipped, abs((ratio or 1) - 1))


def run_stage(fl, jid, jobdir, outdir, name, stage, d):
    step = os.path.join(outdir, f'{name}_stage{stage}.step'); logf = os.path.join(d, f'convert{stage}.log')
    t = time.time()
    rc = fl.run(jid, [PY, '-u', os.path.join(PIPE, 'decode', 'sds2_to_step.py'), jobdir, '-o', step, '--stage', str(stage), '--verify'],
                logf, TIMEOUT, env=conv_env(), cwd=outdir)
    if rc == -9:
        raise MemoryError()
    txt = open(logf, errors='replace').read()
    keep = '\n'.join(l for l in txt.splitlines() if not l.startswith('*') and 'Transferr' not in l and l.strip() and not l.startswith('$ ')
                     and not re.match(r'^\x1b\[[0-9;]*m\s*$', l))
    open(os.path.join(outdir, f'{name}_stage{stage}.log'), 'w', encoding='utf-8').write(keep)
    s = RB.parse_log(txt)
    s.update(rc='timeout' if rc in (124, 125) else rc, wall_s=round(time.time() - t),
             step_mb=round(os.path.getsize(step) / 2 ** 20, 1) if os.path.exists(step) else None)
    s.update(parse_extra(txt))
    if rc != 0:
        s['error'] = keep[-600:]
    bb = parse_bbox(txt)
    s['bbox_in'] = bb; s['bbox_mm'] = [round(v * 25.4, 1) for v in bb] if bb else None
    return step, s, txt, keep


def _process(fl, job, d):
    jid = job['id']
    rec = {'name': job.get('name'), 'fpc': job.get('fpc'), 'n_files': job.get('n_files'), 'paths_sample': job.get('paths', [])[:3],
           'n_paths': job.get('n_paths'), 'jsetup_sha256': job.get('jsetup_sha256'), 'failed_before': job.get('failed_before'),
           'converter': {'label': LABEL, 'zip': CONVERTER['zip'], 'sha256': CONVERTER['sha256']},
           'pipeline': f'sds2-step-pipeline {LABEL}: sds2_to_step.py --stage 2 --verify; stage 1 --verify as members-only fallback'}
    if not job.get('complete_layout', True):
        return dict(rec, status='fail', reason='job_folder_incomplete', detail='main/job_mtrl or mem/mem_idx missing in the job folder')
    mf = load_files(job)
    miss = [f for f in mf if f.get('key') is None and f['size'] > 0]
    rec['model_files'] = len(mf); rec['model_bytes'] = sum(f['size'] for f in mf)
    if miss:
        return dict(rec, status='fail', reason='model_files_unavailable', detail=f'{len(miss)} model files have no stored copy',
                    sample=[f['p'] for f in miss[:10]], needs=['re-extraction of the source archive for these job files'])
    name = RB.safe(job.get('name') or 'job') + '_' + jid[:6]
    jobdir = os.path.join(d, 'job', name)
    items = []
    for f in mf:
        parts = [p.lower() if p.lower() in RB.CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
        items.append([f.get('key') or '', os.path.join(jobdir, *parts), f['size']])
    lst = os.path.join(d, 'fetch.json'); json.dump(items, open(lst, 'w'))
    rc, out, err = fl.sh([PY, os.path.join(HERE, 'fetch.py'), lst, '48'], timeout=7200)
    try:
        fr = json.loads(out.strip().splitlines()[-1])
    except Exception:
        return dict(rec, status='fail', reason='download_error', transient=True, error=(err or out)[-400:])
    rec['fetch'] = {k: fr.get(k) for k in ('n', 'bytes', 'n_errors', 'sec')}
    if fr.get('n_errors'):
        return dict(rec, status='fail', reason='download_error', transient=True, error=fr.get('errors'))
    if not RB.is_job(jobdir):
        return dict(rec, status='fail', reason='job_folder_incomplete', detail='main/job_mtrl or mem/mem_idx missing')
    ver = RB.read_version(jobdir); rec['version'] = ver
    outdir = os.path.join(d, 'out'); os.makedirs(outdir, exist_ok=True)
    step, s2, txt, keep = run_stage(fl, jid, jobdir, outdir, name, 2, d)
    r2 = {'status': 'ok' if s2['rc'] == 0 else 'failed', 'stage2': s2, 'version': ver}
    q, why = RB.qa(r2)
    rec.update(stage2=s2, qa=q, qa_reasons=why)
    solids, valid = s2.get('solids'), s2.get('valid')
    readback = solids is not None and valid is not None
    inv = piece_inventory(os.path.join(outdir, f'{name}_stage2_pieces.csv'), os.path.join(outdir, f'{name}_stage2_skipped.csv'), s2)
    rec['inventory'] = inv
    mfp = os.path.join(outdir, f'{name}_stage2_manifest.json')
    if os.path.exists(mfp):
        rec['manifest'] = manifest_summary(mfp)
    prev = os.path.join(outdir, f'{name}_stage2_preview.png')
    rec['validate'] = {'read_status': 'ok' if readback else None, 'solids': solids, 'valid': valid, 'invalid': (solids - valid) if readback else None,
                       'bbox_mm': s2.get('bbox_mm'), 'steel_ratio': s2.get('steel_ratio'), 'render_ink': png_ink(prev) if os.path.exists(prev) else None,
                       'validated': bool(readback and solids and valid == solids), 'by': 'pipeline decode/verify_step.py (OCP read-back: BRepCheck_Analyzer per placed solid, volume, bbox)'}
    has_step = os.path.exists(step) and os.path.getsize(step) > 0
    bad = (solids - valid) if readback else None
    bbox_ok = (not s2.get('bbox_mm')) or cf.bbox_sane(s2['bbox_mm'])
    r = s2.get('steel_ratio')
    publish2 = (s2['rc'] == 0 and has_step and readback and solids > 0 and bad <= max(5, int(0.001 * solids)) and bbox_ok
                and (r is None or 0.5 <= r <= 1.5))
    rec['stage2_publishable'] = publish2
    meta = {'id': jid, 'name': job.get('name'), 'version': ver, 'paths': job.get('paths'), 'qa': q, 'qa_reasons': why, 'stage2': s2,
            'validate': rec['validate'], 'inventory': inv, 'code': CODE, 'converter': rec['converter'], 'converted': cf.now()}
    if has_step:
        prefix = f'{OUT}/{jid}{SUB}' if publish2 else f'{OUT}/_not_accepted/{jid}{SUB}'
        json.dump(dict(meta, published=publish2), open(os.path.join(outdir, 'job.json'), 'w'), default=str)
        for f in sorted(os.listdir(outdir)):
            if 'stage2' in f or f == 'job.json':
                fl.upload(os.path.join(outdir, f), f'{prefix}/{f}', 'application/step' if f.endswith('.step') else None)
        rec['outputs'] = {'prefix': prefix + '/', 'files': sorted(f for f in os.listdir(outdir) if 'stage2' in f)}
        if os.path.exists(prev):
            rec['render_key'] = f'{prefix}/{name}_stage2_preview.png'
    for nm in ('pieces.csv', 'skipped.csv'):
        p = os.path.join(outdir, f'{name}_stage2_{nm}')
        if os.path.exists(p):
            fl.upload(p, f'{DET}/{jid}.stage2_{nm}')
    if publish2:
        rec['step'] = {'key': f'{OUT}/{jid}{SUB}/{name}_stage2.step', 'stage': 2, 'bytes': os.path.getsize(step), 'solids': solids,
                       'bbox_mm': s2.get('bbox_mm'), 'version': ver}
        rec['status'] = 'ok'
        return rec
    # stage 2 not publishable: reason, then a members-only stage-1 run
    if s2['rc'] != 0:
        reason = RB.error_class(r2)
        reason = {'timeout': 'timeout', 'STEP write failed': 'step_write_failed', 'missing job file': 'missing_job_file',
                  'out of memory': 'out_of_memory'}.get(reason, re.sub(r'[^a-z0-9]+', '_', str(reason).lower()).strip('_') or 'convert_error')
        if 'too few members to calibrate' in txt:
            reason = 'no_members_to_calibrate'
        elif 'unsupported job_mtrl layout' in txt:
            reason = 'unsupported_job_mtrl_layout'
    elif not readback:
        reason = 'verification_counts_missing'
    elif bad > max(5, int(0.001 * solids)):
        reason = 'invalid_solids'
    elif not bbox_ok:
        reason = 'absurd_bbox'
    elif r is not None and not 0.5 <= r <= 1.5:
        reason = 'steel_weight_mismatch'
    else:
        reason = 'not_publishable'
    rec['stage2_reason'] = reason
    if reason in ('no_members_to_calibrate', 'unsupported_job_mtrl_layout', 'timeout', 'out_of_memory'):
        return dict(rec, status='fail', reason=reason, log_tail=keep[-1500:])
    try:
        step1, s1, txt1, keep1 = run_stage(fl, jid, jobdir, outdir, name, 1, d)
    except MemoryError:
        raise
    rec['stage1'] = s1
    ok1 = s1['rc'] == 0 and os.path.exists(step1) and s1.get('solids') and s1.get('valid') == s1.get('solids') \
        and ((not s1.get('bbox_mm')) or cf.bbox_sane(s1['bbox_mm']))
    if ok1:
        prefix = f'{OUT}/{jid}{SUB}'
        json.dump(dict(meta, stage1=s1, published='stage1'), open(os.path.join(outdir, 'job.json'), 'w'), default=str)
        for f in sorted(os.listdir(outdir)):
            if 'stage1' in f or f == 'job.json':
                fl.upload(os.path.join(outdir, f), f'{prefix}/{f}', 'application/step' if f.endswith('.step') else None)
        p1 = os.path.join(outdir, f'{name}_stage1_preview.png')
        rec['validate1'] = {'read_status': 'ok', 'solids': s1.get('solids'), 'valid': s1.get('valid'), 'bbox_mm': s1.get('bbox_mm'),
                            'render_ink': png_ink(p1) if os.path.exists(p1) else None}
        if os.path.exists(p1):
            rec['render_key'] = f'{prefix}/{name}_stage1_preview.png'
        rec['step'] = {'key': f'{OUT}/{jid}{SUB}/{name}_stage1.step', 'stage': 1, 'bytes': os.path.getsize(step1), 'solids': s1.get('solids'),
                       'bbox_mm': s1.get('bbox_mm'), 'version': ver}
        return dict(rec, status='ok_stage1', reason=f'stage2_{reason}')
    return dict(rec, status='fail', reason=reason, log_tail=keep[-1500:])


def process(fl, job, d):
    """best-of policy across converter versions: when this job already has a result of another converter, keep the better
    of the two (failure < stage-1 members only < stage 2; then class estimate, invalid solids, skipped pieces, weight ratio);
    both are recorded (alternatives) and the history keeps the per-version counts"""
    prev = fl.getj(f'{fl.ST}/results/{job["id"]}.json')
    new = _process(fl, job, d)
    if not prev or str(prev.get('code', '')).startswith(f'z3-sds2-{LABEL}-') or prev.get('status') not in ('ok', 'ok_stage1'):
        if prev and prev.get('status') not in ('ok', 'ok_stage1') and not str(prev.get('code', '')).startswith(f'z3-sds2-{LABEL}-'):
            new['alternatives'] = {(prev.get('converter') or {}).get('label', 'v4'): {'status': prev.get('status'), 'reason': prev.get('reason')}}
        return new
    pl = (prev.get('converter') or {}).get('label', 'v4')
    a, b = est_class(new), est_class(prev)
    summ = lambda r: {'status': r.get('status'), 'reason': r.get('reason'), 'est': list(est_class(r)), 'step': r.get('step'),
                      'qa': r.get('qa'), 'ratio': (r.get('stage2') or {}).get('steel_ratio'), 'manifest_class': (r.get('manifest') or {}).get('class')}
    if a <= b:
        new['alternatives'] = {pl: summ(prev)}; new['chosen'] = LABEL
        return new
    keep = {k: v for k, v in prev.items() if k not in ('id', 'pipeline', 'code', 'runtime', 'host', 'started', 'sec', 'finished', 'size')}
    keep['alternatives'] = {LABEL: summ(new)}; keep['chosen'] = pl
    keep['best_of_note'] = f'{LABEL} graded worse than {pl} ({list(a)} vs {list(b)}): {pl} STEP kept'
    return keep


if __name__ == '__main__':
    os.environ.setdefault('CONV_SLOTS', str(max(1, min((os.cpu_count() or 4) - 2, (cf.mem()[0] >> 30) // 6))))
    fl = cf.Fleet('sds2', CODE, process, need_bytes, FILES, need_disk=need_disk, redo=redo, redo_ids_key=f'{cf.CTLROOT}/sds2/redo_ids.json')
    sys.exit(fl.main())
