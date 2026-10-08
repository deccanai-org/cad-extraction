#!/usr/bin/env python3
"""Grade full-pipeline regression outputs with the coordinator's own classifier (current and patched build_index) after
building the fleet result record the way worker._process does (log parse + manifest_summary of the current / patched
worker). usage: gradecheck.py OUT_JSON TAG_DIR[:label] ...   (TAG_DIR = /work/agentwork/sds2-weights-failures/out/<tag>)"""
import os, sys, re, json, types, importlib.util, glob, collections
os.environ.setdefault('INDEX_WORK', '/tmp/swf_index')
W = '/work/agentwork/sds2-weights-failures'
G = f'{W}/grading'
sys.path.insert(0, G)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def worker_funcs(path):
    """manifest_summary / parse_extra / helpers from a worker.py without importing it (its import unpacks the kit)"""
    src = open(path).read()
    ns = {'json': json, 'collections': collections, 're': re, 'os': os}
    for fn in ('_wpart', 'holes_summary', 'manifest_summary', 'parse_extra', 'parse_bbox'):
        m = re.search(rf'^def {fn}\(.*?(?=^def |\Z)', src, re.S | re.M)
        if m:
            exec(m.group(0), ns)
    return ns


BI = {'current': load(f'{G}/build_index.latest.py', 'bi_cur'), 'patched': load(f'{G}/build_index.py', 'bi_new')}
WK = {'current': worker_funcs(f'{G}/worker.latest.py'), 'patched': worker_funcs(f'{G}/worker.py')}
RB = load(f'{W}/v54/sds2-step-pipeline/batch/run_batch.py', 'run_batch')
ALL = {j['id']: j for j in json.load(open(f'{W}/jobs_all.json'))}


def result(d, jid, wk, label):
    log = open(f'{d}/run.log', errors='replace').read() if os.path.exists(f'{d}/run.log') else ''
    s2 = RB.parse_log(log); s2.update(wk['parse_extra'](log))
    rc = 0 if re.search(r'with solids: \d+; BRep valid', log) and 'Traceback' not in log else 1
    s2['rc'] = rc
    mfs = glob.glob(f'{d}/*_stage2_manifest.json')
    man = wk['manifest_summary'](mfs[0]) if mfs else None
    solids, valid = s2.get('solids'), s2.get('valid')
    j = ALL[jid]
    res = {'id': jid, 'code': f'z3-sds2-{label}', 'version': s2.get('version') or j.get('version'), 'converter': {'label': label},
           'stage2': s2, 'validate': {'read_status': 'ok' if solids is not None else None, 'solids': solids, 'valid': valid,
                                      'bbox_mm': s2.get('bbox_mm'), 'render_ink': 0.05},
           'step': {'key': f'{label}/{jid}', 'stage': 2}}
    if man:
        res['manifest'] = man
    if rc == 0 and solids:
        res['status'] = 'ok'
    else:
        res['status'] = 'fail'
        res['reason'] = 'missing_job_file' if 'subm_idx' in log and 'FileNotFoundError' in log else \
            ('valueerror' if 'ValueError' in log else 'convert_error')
        res['error'] = log[-400:]
    return res


def grade(res, bi):
    c = dict(ALL[res['id']]); c.update(action='convert', id=res['id'])
    row = bi.classify_sds2(c, res, None)
    miss, need = bi.explain(row)
    return dict(cls=row.get('class'), corpus=row.get('corpus'), status=row.get('status'), issues=row.get('issues'),
                reasons=row.get('reasons'), standins=[(s_.get('type'), s_.get('count')) for s_ in row.get('standins') or []][:12],
                weight_ratio={k: v for k, v in (row.get('weight_ratio') or {}).items() if k != 'by_family'},
                info=row.get('issues_info'), keys=[n['key'] for n in need])


out = {}
for arg in sys.argv[2:]:
    d0, label = (arg.split(':') + [None])[:2]
    label = label or os.path.basename(d0)
    for d in sorted(glob.glob(f'{d0}/*')):
        jid = os.path.basename(d)
        if jid not in ALL or not os.path.isdir(d):
            continue
        rec = out.setdefault(jid, {'name': ALL[jid].get('name'), 'version': ALL[jid].get('version')})
        side = 'patch' if 'p9' in label else 'base'
        try:
            res = result(d, jid, WK['patched' if side == 'patch' else 'current'], label)
            rec[side] = {'status': res['status'], 'reason': res.get('reason'),
                         'manifest': {k: (res.get('manifest') or {}).get(k) for k in ('class', 'corpus', 'class_reasons')},
                         'counts': {k: ((res.get('manifest') or {}).get('counts') or {}).get(k) for k in
                                    ('members', 'placed_pieces', 'pieces_written', 'pieces_exact', 'pieces_approx', 'skipped',
                                     'member_envelopes', 'solids_written', 'piece_table_absent', 'subm_piece_files')},
                         'readback': (res.get('manifest') or {}).get('readback'),
                         'weight': {k: ((res.get('manifest') or {}).get('weight') or {}).get(k) for k in
                                    ('ratio', 'ratio_without_outliers', 'by_source', 'turned_brep')},
                         'n_outliers': ((res.get('manifest') or {}).get('weight') or {}).get('sds2_weight_outliers'),
                         'grade_current_rule': grade(res, BI['current']) if res['status'] == 'ok' else None}
            if side == 'patch' and res['status'] == 'ok':
                rec[side]['grade_patched_rule'] = grade(res, BI['patched'])
        except Exception as e:
            import traceback
            rec[side] = {'error': f'{type(e).__name__}: {e}', 'tb': traceback.format_exc()[-1500:]}
json.dump(out, open(sys.argv[1], 'w'), indent=1, default=str)
print('graded', len(out))
