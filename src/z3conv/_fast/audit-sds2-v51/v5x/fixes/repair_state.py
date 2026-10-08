#!/usr/bin/env python3
"""audit-sds2-v5x repair tool for the data-3 SDS2 fleet state (DRY RUN unless --apply). Run on a Mumbai box (instance role).

  restore   results/<id>.json was overwritten by a fleet-made failure (out_of_memory after 5 kills) although an accepted output
            of an earlier converter label exists: rebuild the result from that output (job.json + manifest sidecar + STEP / preview
            keys, exactly as the worker writes it) and keep the failure under alternatives[<failing label>]
  prefer    best-of kept an older label on weight noise only: rebuild the result from the newer label's output, the older one
            goes to alternatives (VOID 2263534c, 401 CONGRESS 693974d8)
  reopen    false out_of_memory verdict (every kill at < --kill-min-gb RSS, no earlier finished result): delete results/<id>.json
            and deferred/<id>.json so the fleet converts the job again
  reset     deferred/<id>.json of a finished job whose kills were all at < --kill-min-gb RSS: kills -> 0 (the unpatched fleet turns
            the 5th kill into out_of_memory over the finished result)

usage: python repair_state.py --plan out/repair_plan.json [--only reset] [--apply] [--code-from output|current]
  the plan is written by audit5x.py (out/repair_plan.json); every action is re-checked against live S3 before it is applied.
Every record is re-graded with the deployed coordinator rules (build_index.classify_sds2 + rules.json) and printed.
"""
import os, sys, re, json, ast, argparse, collections, copy, time
import boto3
from botocore.config import Config

B = 'bim-proprietary-data'; ROOT = 'cad-disk-extract/zenitude-data-3'; ST = f'{ROOT}/_state/conv/sds2'
OUT = f'{ROOT}/conversions/sds2-step'
CB = 'annotationprod'; CTL = 'cad-disk-extract/_control/z3conv'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 20, 'mode': 'standard'}))
HERE = os.path.dirname(os.path.abspath(__file__))


def lab(code):
    m = re.match(r'z3-sds2-(v[\d.]+?)-20\d\d', str(code or ''))
    return m.group(1) if m else None


def getj(key, bucket=B):
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)['Body'].read())
    except Exception:
        return None


def listing(prefix):
    out = {}
    for p in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        for o in p.get('Contents', []):
            out[o['Key']] = o['Size']
    return out


def deployed(name, bucket, key):
    p = os.path.join(HERE, '_deployed_' + name)
    s3.download_file(bucket, key, p)
    return p


# deployed worker functions (manifest_summary) and coordinator classifier, exactly as running
_w = open(deployed('worker.py', CB, f'{CTL}/sds2/worker.py')).read()
_ns = {'json': json, 'collections': collections, 're': re, 'os': os}
for node in ast.parse(_w).body:     # every top-level def (definitions only): manifest_summary's helpers come along
    if isinstance(node, ast.FunctionDef) or (isinstance(node, ast.Assign) and any(getattr(x, 'id', None) == 'GRATING' for x in node.targets)):
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'worker.py', 'exec'), _ns)
manifest_summary, est_class = _ns['manifest_summary'], _ns['est_class']
deployed('grade_join.py', CB, f'{CTL}/coord/grade_join.py')
_bi = deployed('build_index.py', CB, f'{CTL}/coord/build_index.py')
os.environ.setdefault('INDEX_WORK', os.path.join(HERE, '_idxwork'))
sys.path.insert(0, HERE)
import importlib.util
_spec = importlib.util.spec_from_file_location('build_index', _bi); BI = importlib.util.module_from_spec(_spec)
sys.modules['grade_join'] = importlib.util.module_from_spec(importlib.util.spec_from_file_location('grade_join', os.path.join(HERE, '_deployed_grade_join.py')))
sys.modules['grade_join'].__spec__.loader.exec_module(sys.modules['grade_join'])
_spec.loader.exec_module(BI)
BI.RULES = dict(BI.DEFAULT_RULES); BI.RULES.update(getj(f'{CTL}/coord/rules.json', CB) or {})


def grade(jid, r):
    row = BI.classify_sds2({'id': jid, 'action': 'convert'}, copy.deepcopy(r), None)
    return {'class': row.get('class'), 'corpus': row.get('corpus'), 'status': row.get('status'), 'reasons': row.get('reasons'),
            'issues': row.get('issues')[:6], 'solids': row.get('solids'), 'step_key': row.get('step_key')}


def rebuild(jid, label, cur):
    """result record of an accepted output conversions/sds2-step/<id>/[<label>/], in the worker's result format"""
    pre = f'{OUT}/{jid}/' + ('' if label == 'v4' else f'{label}/')
    files = {k[len(pre):]: v for k, v in listing(pre).items() if '/' not in k[len(pre):]}
    j = getj(pre + 'job.json')
    if not j or lab(j.get('code')) != label:
        raise SystemExit(f'{jid}: no {label} job.json under {pre}')
    pub = j.get('published')
    if pub not in (True, 'stage1'):
        raise SystemExit(f'{jid}: {label} output not published ({pub})')
    stage = 2 if pub is True else 1
    stepf = next((f for f in files if f.endswith(f'_stage{stage}.step')), None)
    if not stepf:
        raise SystemExit(f'{jid}: {label} STEP missing under {pre}')
    r = {k: v for k, v in (cur or {}).items() if k in ('name', 'fpc', 'n_files', 'paths_sample', 'n_paths', 'jsetup_sha256', 'model_files',
                                                      'model_bytes', 'size', 'fetch', 'failed_before')}
    r.update(j)
    r.update(id=jid, pipeline='sds2', status='ok' if stage == 2 else 'ok_stage1', stage2_publishable=stage == 2,
             outputs={'prefix': pre, 'files': sorted(files)})
    manf = next((f for f in files if f.endswith('_stage2_manifest.json')), None)
    if manf:
        p = os.path.join(HERE, '_m.json'); s3.download_file(B, pre + manf, p)
        r['manifest'] = manifest_summary(p)
    v = (j.get('validate') or {}) if stage == 2 else (j.get('validate1') or {'solids': (j.get('stage1') or {}).get('solids'),
                                                                                   'bbox_mm': (j.get('stage1') or {}).get('bbox_mm')})
    r['step'] = {'key': pre + stepf, 'stage': stage, 'bytes': files[stepf], 'solids': v.get('solids'), 'bbox_mm': v.get('bbox_mm'),
                 'version': j.get('version')}
    png = next((f for f in files if f.endswith(f'_stage{stage}_preview.png')), None)
    if png:
        r['render_key'] = pre + png
    r['restored'] = {'by': 'audit-sds2-v5x repair_state.py', 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'from_output': pre}
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--code-from', choices=('output', 'current'), default='output',
                    help="code of a restored record: 'output' = the restored converter's own code (reconvert rules re-target the job "
                         "once the fleet fix is live); 'current' = the failing run's code (counted as attempted)")
    ap.add_argument('--only', default='', help='comma list of actions to run (restore,prefer,reopen,reset); default all')
    ap.add_argument('--kill-min-gb', type=float, default=4.0, help='reset: every kill of the job below this RSS')
    ap.add_argument('--reopen-max-gb', type=float, default=8.0, help='reopen: every one of the 5 kills below this RSS')
    a = ap.parse_args()
    plan = json.load(open(a.plan))
    if a.only:
        plan = [p_ for p_ in plan if p_['action'] in set(a.only.split(','))]
    log = []
    for act in plan:
        jid, kind = act['id'], act['action']
        cur = getj(f'{ST}/results/{jid}.json')
        dfr = getj(f'{ST}/deferred/{jid}.json')
        ent = {'id': jid, 'action': kind, 'name': (cur or {}).get('name'), 'current': {k: (cur or {}).get(k) for k in ('status', 'reason', 'code', 'kills')},
               'current_label': ((cur or {}).get('converter') or {}).get('label')}
        try:
            if kind in ('restore', 'prefer'):
                label = act['label']
                if kind == 'restore' and not (cur and cur.get('status') == 'fail' and cur.get('reason') == 'out_of_memory'):
                    ent['skip'] = 'current result is not an out_of_memory failure any more'; log.append(ent); continue
                if kind == 'prefer' and not (cur and cur.get('status') in ('ok', 'ok_stage1') and ((cur.get('converter') or {}).get('label') == act.get('from'))):
                    ent['skip'] = f"current result is not the {act.get('from')} output any more"; log.append(ent); continue
                new = rebuild(jid, label, cur)
                alts = dict((cur or {}).get('alternatives') or {})
                fl = lab(cur.get('code')) or 'unknown'
                if kind == 'restore':
                    alts[fl] = {k: cur.get(k) for k in ('status', 'reason', 'kills', 'min_mem_gb', 'finished', 'host', 'code', 'peak_rss_gb') if cur.get(k) is not None}
                    new['best_of_note'] = f"{fl} {cur.get('reason')} (memory kills at < {a.kill_min_gb:g} GB RSS, fleet watchdog): {label} result restored"
                else:
                    old_lb = (cur.get('converter') or {}).get('label')
                    alts[old_lb] = {'status': cur.get('status'), 'est': list(est_class(cur)), 'step': cur.get('step'), 'ratio': (cur.get('stage2') or {}).get('steel_ratio'),
                                    'manifest_class': (cur.get('manifest') or {}).get('class')}
                    new['best_of_note'] = f"{old_lb} kept on weight noise only ({list(est_class(cur))} vs {list(est_class(new))}): newer {label} result preferred"
                alts.pop(label, None)
                new['alternatives'] = alts; new['chosen'] = label
                if a.code_from == 'current':
                    new['code'] = cur.get('code')
                ent['rebuilt'] = {'status': new['status'], 'code': new.get('code'), 'label': (new.get('converter') or {}).get('label'),
                                  'step': new['step'], 'est': list(est_class(new))}
                ent['grade_before'] = grade(jid, cur) if cur else None
                ent['grade_after'] = grade(jid, new)
                if a.apply:
                    s3.put_object(Bucket=B, Key=f'{ST}/results/{jid}.json', Body=json.dumps(new, default=str).encode(), ContentType='application/json')
                    ent['applied'] = True
            elif kind == 'reopen':
                kills = act.get('kill_rss_gb') or []
                if not (cur and cur.get('reason') == 'out_of_memory') or not kills or max(kills) >= a.reopen_max_gb:
                    ent['skip'] = 'not a false out_of_memory verdict (or kill RSS unknown / >= reopen_max_gb)'; log.append(ent); continue
                ent['delete'] = [f'{ST}/results/{jid}.json'] + ([f'{ST}/deferred/{jid}.json'] if dfr else [])
                if a.apply:
                    for k in ent['delete']:
                        s3.delete_object(Bucket=B, Key=k)
                    ent['applied'] = True
            elif kind == 'reset':
                kills = act.get('kill_rss_gb') or []
                if not dfr or (cur and cur.get('status') not in ('ok', 'ok_stage1')) or not kills or max(kills) >= a.kill_min_gb \
                        or (dfr.get('kills') or 0) > len(kills):
                    ent['skip'] = 'deferred record gone, result is a failure, a kill at >= kill_min, or kills newer than the plan'; log.append(ent); continue
                d2 = dict(dfr, kills=0, kills_reset={'from': dfr.get('kills'), 'kill_rss_gb': kills, 'by': 'audit-sds2-v5x'})
                d2['min_mem_bytes'] = min(dfr.get('min_mem_bytes') or 0, 8 << 30) or dfr.get('min_mem_bytes'); d2['min_mem_gb'] = (d2['min_mem_bytes'] or 0) >> 30
                ent['deferred_before'] = {k: dfr.get(k) for k in ('kills', 'min_mem_gb')}; ent['deferred_after'] = {k: d2.get(k) for k in ('kills', 'min_mem_gb')}
                if a.apply:
                    s3.put_object(Bucket=B, Key=f'{ST}/deferred/{jid}.json', Body=json.dumps(d2).encode(), ContentType='application/json')
                    ent['applied'] = True
        except SystemExit as e:
            ent['error'] = str(e)
        log.append(ent)
    print(json.dumps(log, indent=1, default=str))
    cnt = collections.Counter(f"{x['action']}|" + ('skip' if x.get('skip') else 'error' if x.get('error') else 'applied' if x.get('applied') else 'dry-run')
                              for x in log)
    print(json.dumps(cnt, indent=1))


if __name__ == '__main__':
    main()
