#!/usr/bin/env python3
"""Grade stage-2 run outputs the way the fleet + coordinator would: worker acceptance (publish2, with the pipeline's own
run_batch.parse_log), worker manifest_summary, coordinator classify_sds2 + explain (current and patched build_index /
worker). usage: gradecheck2.py OUT_JSON RUN_DIR:label:pipeline_dir:side ...   side = cur | new"""
import os, sys, re, json, importlib.util, glob, collections
os.environ.setdefault('INDEX_WORK', '/tmp/swf_index2')
W = '/work/agentwork/sds2-weights-failures'; J = f'{W}/j2'; G = f'{J}/grading'
sys.path.insert(0, G)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def worker_funcs(path):
    src = open(path).read()
    ns = {'json': json, 'collections': collections, 're': re, 'os': os}
    for fn in ('_wpart', 'holes_summary', 'manifest_summary', 'parse_extra', 'parse_bbox'):
        m = re.search(rf'^def {fn}\(.*?(?=^def |\Z)', src, re.S | re.M)
        if m:
            exec(m.group(0), ns)
    return ns


BI = {'cur': load(f'{G}/build_index.cur.py', 'bi_cur'), 'new': load(f'{G}/build_index.new.py', 'bi_new')}
WK = {'cur': worker_funcs(f'{G}/worker.cur.py'), 'new': worker_funcs(f'{G}/worker.new.py')}
ALL = {}
for nm in ('jobs.json', 'jobs_merged.json', 'jobs_reconvert.json'):
    p = f'{J}/full_{nm}'
    if os.path.exists(p):
        d = json.load(open(p)); d = d.get('jobs', list(d.values())) if isinstance(d, dict) else d
        for j in d:
            if isinstance(j, dict) and j.get('id'):
                ALL.setdefault(j['id'], j)


def bbox_sane(bb):
    return bb is None or all(abs(v) < 1e8 for v in bb)


def result(d, jid, wk, label, RB):
    log = open(f'{d}/run.log', errors='replace').read() if os.path.exists(f'{d}/run.log') else ''
    s2 = RB.parse_log(log); s2.update(wk['parse_extra'](log))
    bb = wk['parse_bbox'](log); s2['bbox_mm'] = [round(v * 25.4, 1) for v in bb] if bb else None
    rc = 0 if re.search(r'with solids: \d+; BRep valid', log) and 'Traceback' not in log else 1
    s2['rc'] = rc
    mfs = glob.glob(f'{d}/*_stage2_manifest.json')
    man = wk['manifest_summary'](mfs[0]) if mfs else None
    solids, valid = s2.get('solids'), s2.get('valid')
    readback = solids is not None and valid is not None
    bad = (solids - valid) if readback else None
    r = s2.get('steel_ratio')
    publish2 = bool(rc == 0 and readback and solids > 0 and bad <= max(5, int(0.001 * solids)) and bbox_sane(s2.get('bbox_mm'))
                    and (r is None or 0.5 <= r <= 1.5))
    if rc != 0:
        why = 'missing_job_file' if 'FileNotFoundError' in log else ('valueerror' if 'ValueError' in log else 'convert_error')
    elif not readback:
        why = 'verification_counts_missing'
    elif bad > max(5, int(0.001 * solids)):
        why = 'invalid_solids'
    elif r is not None and not 0.5 <= r <= 1.5:
        why = 'steel_weight_mismatch'
    else:
        why = None
    j = ALL.get(jid, {})
    res = {'id': jid, 'code': f'z3-sds2-{label}', 'version': s2.get('version') or j.get('version'), 'converter': {'label': label},
           'stage2': s2, 'validate': {'read_status': 'ok' if readback else None, 'solids': solids, 'valid': valid,
                                      'bbox_mm': s2.get('bbox_mm'), 'render_ink': 0.05},
           'step': {'key': f'{label}/{jid}', 'stage': 2}}
    if man:
        res['manifest'] = man
    if publish2:
        res['status'] = 'ok'
    else:
        # the fleet would run stage 1 (members only) and publish that
        res.update(status='ok_stage1', stage2_reason=why, step={'key': f'{label}/{jid}/stage1', 'stage': 1},
                   stage1={'solids': 1, 'valid': 1}, validate1={'read_status': 'ok', 'render_ink': 0.05})
    return res, publish2, why


def grade(res, bi):
    c = dict(ALL.get(res['id'], {})); c.update(action='convert', id=res['id'])
    row = bi.classify_sds2(c, res, None)
    miss, need = bi.explain(row)
    return dict(cls=row.get('class'), corpus=row.get('corpus'), status=row.get('status'), issues=row.get('issues'),
                reasons=row.get('reasons'), standins=[(s_.get('type'), s_.get('count')) for s_ in row.get('standins') or []][:14],
                weight_ratio={k: v for k, v in (row.get('weight_ratio') or {}).items() if k != 'by_family'},
                info=row.get('issues_info'), keys=[n['key'] for n in need])


if __name__ == '__main__':
  out = {}
  for arg in sys.argv[2:]:
      d0, label, pipe, side = arg.split(':')
      RB = load(f'{pipe}/batch/run_batch.py', 'rb_' + label)
      rl = f'{J}/{label}.runlog'
      done = set(re.findall(r'done ([0-9a-f]{24}) ', open(rl).read())) if os.path.exists(rl) else None
      for d in sorted(glob.glob(f'{d0}/*')):
          jid = os.path.basename(d)
          if not os.path.isdir(d) or not os.path.exists(f'{d}/run.log'):
              continue
          if done is not None and jid not in done:
              continue                                # still running
          rec = out.setdefault(jid, {'name': ALL.get(jid, {}).get('name')})
          try:
              res, pub, why = result(d, jid, WK[side], label, RB)
              m = res.get('manifest') or {}
              rec[label] = {'publish2': pub, 'stage2_reason': why, 'solids': res['stage2'].get('solids'), 'valid': res['stage2'].get('valid'),
                            'steel_ratio': res['stage2'].get('steel_ratio'),
                            'manifest': {k: m.get(k) for k in ('class', 'corpus', 'class_reasons')},
                            'counts': {k: (m.get('counts') or {}).get(k) for k in
                                       ('members', 'placed_pieces', 'pieces_written', 'pieces_exact', 'pieces_approx', 'skipped',
                                        'member_envelopes', 'solids_written', 'bolts_sds2', 'piece_table_absent', 'subm_piece_files')},
                            'readback': m.get('readback'),
                            'weight': {k: (m.get('weight') or {}).get(k) for k in ('ratio', 'ratio_without_outliers', 'by_source', 'turned_brep', 'sds2_weight_outliers')},
                            'skipped_by_reason': m.get('skipped_by_reason'),
                            'grade_cur_rule': grade(res, BI['cur'])}
              if side == 'new':
                  rec[label]['grade_new_rule'] = grade(res, BI['new'])
          except Exception as e:
              import traceback
              rec[label] = {'error': f'{type(e).__name__}: {e}', 'tb': traceback.format_exc()[-1500:]}
  json.dump(out, open(sys.argv[1], 'w'), indent=1, default=str)
  print('graded', len(out))
