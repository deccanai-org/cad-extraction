#!/usr/bin/env python3
"""Reviewer grading: worker acceptance (publish2 with the run's own run_batch.parse_log), worker manifest_summary +
piece_inventory, coordinator classify_sds2 + explain, current and patched build_index / worker.
usage: gradechk.py OUT_JSON TAG:tree_dir[:new] ..."""
import os, sys, re, json, glob, importlib.util, collections, csv, math
os.environ.setdefault('INDEX_WORK', '/tmp/swfr_index')
W = '/work/agentwork/sds2-weights-failures-review'; G = f'{W}/grading'
sys.path.insert(0, G)
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def worker_funcs(path):
    src = open(path).read()
    ns = {'json': json, 'collections': collections, 're': re, 'os': os, 'csv': csv, 'math': math,
          'GRATING': re.compile(r'^(GT|GR|GRTG|GRATING|BAR\s*GRATING)', re.I)}
    for fn in ('_wpart', 'holes_summary', 'manifest_summary', 'parse_extra', 'parse_bbox', 'piece_inventory'):
        m = re.search(rf'^def {fn}\(.*?(?=^def |^[A-Z_]+ = |\Z)', src, re.S | re.M)
        if m: exec(m.group(0), ns)
    return ns
BI = {'cur': load(f'{G}/build_index.cur.py', 'bi_cur'), 'new': load(f'{G}/build_index.new.py', 'bi_new')}
for b in BI.values():
    try:
        rj = json.load(open(f'{G}/rules.json')); b.RULES.update({k: v for k, v in rj.items() if not k.startswith('_') and k != 'doc'})
    except Exception as e:
        print('rules', e)
WK = {'cur': worker_funcs(f'{G}/worker.cur.py'), 'new': worker_funcs(f'{G}/worker.new.py')}
ALL = {}
for nm in ('jobs.json', 'jobs_merged.json', 'jobs_reconvert.json'):
    p = f'{W}/full_{nm}'
    if os.path.exists(p):
        d = json.load(open(p)); d = d.get('jobs', list(d.values())) if isinstance(d, dict) else d
        for j in d:
            if isinstance(j, dict) and j.get('id'): ALL.setdefault(j['id'], j)
def bbox_sane(bb):
    return bb is None or all(abs(v) < 1e8 for v in bb)
def result(d, jid, wk, label, RB):
    log = open(f'{d}/run.log', errors='replace').read() if os.path.exists(f'{d}/run.log') else ''
    s2 = RB.parse_log(log); s2.update(wk['parse_extra'](log))
    bb = wk['parse_bbox'](log); s2['bbox_mm'] = [round(v * 25.4, 1) for v in bb] if bb else None
    rc = 0 if re.search(r'with solids: \d+; BRep valid', log) and 'Traceback' not in log else 1
    s2['rc'] = rc
    mfs = glob.glob(f'{d}/*_stage2_manifest.json'); pcs = glob.glob(f'{d}/*_stage2_pieces.csv'); sks = glob.glob(f'{d}/*_stage2_skipped.csv')
    man = wk['manifest_summary'](mfs[0]) if mfs else None
    inv = wk['piece_inventory'](pcs[0] if pcs else '/nonexist', sks[0] if sks else '/nonexist', s2)
    solids, valid = s2.get('solids'), s2.get('valid')
    readback = solids is not None and valid is not None
    bad = (solids - valid) if readback else None
    r = s2.get('steel_ratio')
    publish2 = bool(rc == 0 and readback and solids > 0 and bad <= max(5, int(0.001 * solids)) and bbox_sane(s2.get('bbox_mm'))
                    and (r is None or 0.5 <= r <= 1.5))
    if rc != 0:
        tb = log[log.rfind('Traceback'):][-400:] if 'Traceback' in log else log[-400:]
        why = 'convert_error: ' + tb.strip().splitlines()[-1][:200] if tb.strip() else 'convert_error'
    elif not readback: why = 'verification_counts_missing'
    elif bad > max(5, int(0.001 * solids)): why = 'invalid_solids'
    elif r is not None and not 0.5 <= r <= 1.5: why = 'steel_weight_mismatch'
    else: why = None
    j = ALL.get(jid, {})
    res = {'id': jid, 'code': f'z3-sds2-{label}', 'version': s2.get('version') or j.get('version'), 'converter': {'label': label},
           'stage2': s2, 'inventory': inv, 'validate': {'read_status': 'ok' if readback else None, 'solids': solids, 'valid': valid,
           'invalid': bad, 'bbox_mm': s2.get('bbox_mm'), 'render_ink': 0.05}, 'step': {'key': f'{label}/{jid}', 'stage': 2}}
    if man: res['manifest'] = man
    if publish2: res['status'] = 'ok'
    else:
        res.update(status='ok_stage1', stage2_reason=why, step={'key': f'{label}/{jid}/stage1', 'stage': 1},
                   stage1={'solids': 1, 'valid': 1}, validate1={'read_status': 'ok', 'render_ink': 0.05})
    return res, publish2, why, mfs
def grade(res, bi):
    c = dict(ALL.get(res['id'], {})); c.update(action='convert', id=res['id'])
    row = bi.classify_sds2(c, res, None)
    miss, need = bi.explain(row)
    return dict(cls=row.get('class'), corpus=row.get('corpus'), status=row.get('status'), issues=row.get('issues'), reasons=row.get('reasons'),
                standins=[(s_.get('type'), s_.get('count')) for s_ in row.get('standins') or []][:16],
                weight_ratio={k: v for k, v in (row.get('weight_ratio') or {}).items() if k not in ('by_family', 'by_source')},
                info=row.get('issues_info'), keys=[n['key'] for n in need])
if __name__ == '__main__':
    out = {}
    for arg in sys.argv[2:]:
        parts = arg.split(':'); tag, pipe = parts[0], parts[1]; new = len(parts) > 2
        RB = load(f'{pipe}/batch/run_batch.py', 'rb_' + tag)
        rl = f'{W}/logs/{tag}.runlog'
        done = set(re.findall(r'done ([0-9a-f]{24}) ', open(rl).read())) if os.path.exists(rl) else set()
        for d in sorted(glob.glob(f'{W}/out/{tag}/*')):
            jid = os.path.basename(d)
            if jid not in done: continue
            if not os.path.isdir(d) or not os.path.exists(f'{d}/run.log'): continue
            if not open(f'{d}/run.log', errors='replace').read().strip() or ('with solids:' not in open(f'{d}/run.log', errors='replace').read() and 'Traceback' not in open(f'{d}/run.log', errors='replace').read() and 'Error' not in open(f'{d}/run.log', errors='replace').read()):
                continue   # still running
            rec = out.setdefault(jid, {'name': ALL.get(jid, {}).get('name')})
            try:
                res, pub, why, mfs = result(d, jid, WK['cur'], tag, RB)
                full = json.load(open(mfs[0])) if mfs else {}
                m = res.get('manifest') or {}
                fw = (full.get('weight_check') or full.get('weight') or {})
                rec[tag] = {'publish2': pub, 'stage2_reason': why, 'solids': res['stage2'].get('solids'), 'valid': res['stage2'].get('valid'),
                            'steel_ratio': res['stage2'].get('steel_ratio'), 'readback_passes': res['stage2'].get('readback_passes'),
                            'manifest_class': [full.get('class'), full.get('corpus'), (full.get('class_reasons') or [])[:6]],
                            'counts': full.get('counts'), 'standins_by_type': (full.get('standins') or {}).get('by_type'),
                            'skipped_by_reason': full.get('skipped_by_reason') or m.get('skipped_by_reason'),
                            'weight': {k: fw.get(k) for k in ('ratio', 'ratio_without_outliers', 'step_steel_t', 'sds2_piece_weight_t', 'by_source', 'turned_brep')},
                            'sds2_weight_outliers': fw.get('sds2_weight_outliers'),
                            'by_family': {f: {k: v.get(k) for k in ('ratio', 'n', 'exact', 'built', 'standin', 'step_lb', 'sds2_lb')} for f, v in (fw.get('by_family') or {}).items()},
                            'readback': full.get('readback'), 'grade_cur': grade(res, BI['cur'])}
                if new:
                    res2, _, _, _ = result(d, jid, WK['new'], tag, RB)
                    rec[tag]['grade_new'] = grade(res2, BI['new'])
            except Exception as e:
                import traceback
                rec[tag] = {'error': f'{type(e).__name__}: {e}', 'tb': traceback.format_exc()[-1500:]}
    json.dump(out, open(sys.argv[1], 'w'), indent=1, default=str)
    print('graded', len(out))
