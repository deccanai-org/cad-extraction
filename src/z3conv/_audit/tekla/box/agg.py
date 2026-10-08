#!/usr/bin/env python3
"""Tekla audit (read-only): aggregate every DB1 conversion result of Disk-1/2 (db1-v2 + Windows pipeline), data-4 and data-3
per engine.  Reads S3 only; writes one summary JSON (+ per-model compact rows) to agentwork/tekla-audit/."""
import os, sys, json, re, gzip, collections, time
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 20, 'mode': 'standard'}, max_pool_connections=40))
B = 'bim-proprietary-data'
OUTP = 'cad-disk-extract/zenitude-data-3/_state/agentwork/tekla-audit'
SRC = {
    'd12': 'cad-disk-extract/_state/db1-v2/results/',
    'd12_superseded': 'cad-disk-extract/_state/db1-v2/results_superseded/',
    'z4': 'cad-disk-extract/zentitude-data-4/_state/conv/db1/results/',
    'z4_retry': 'cad-disk-extract/zentitude-data-4/_state/conv/db1/retry/',
    'z3': 'cad-disk-extract/zenitude-data-3/_state/conv/db1/results/',
}
def lst(prefix, suffix='.json'):
    out = []
    for p in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        for o in p.get('Contents', []):
            if o['Key'].endswith(suffix):
                out.append(o['Key'])
    return out
def getj(k):
    try:
        return json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception as e:
        return {'_err': f'{type(e).__name__}: {str(e)[:100]}', '_key': k}
def eng_of(d):
    e = d.get('engine')
    if e is None:
        e = ((d.get('layout') or {}).get('engine'))
    return str(e) if e is not None else 'None'

def compact(ds, d):
    c = d.get('convert') or {}
    dec = d.get('decoded') or {}
    v = d.get('validate') or {}
    st = d.get('step_stats') or {}
    row = {'ds': ds, 'id': d.get('id') or d.get('sha') or d.get('sha256'), 'engine': eng_of(d), 'code': d.get('code'), 'status': d.get('status'),
           'reason': d.get('reason'), 'old_status': d.get('old_status'), 'bytes': d.get('db1_bytes') or d.get('size') or d.get('in_bytes'),
           'members_rec': c.get('members'), 'written': c.get('written'), 'sources': c.get('sources'), 'skipped': c.get('skipped'),
           'cuts_applied': c.get('cuts_applied'), 'cut_layout': c.get('cut_layout'), 'axis_drop': c.get('axis_mismatch_dropped'),
           'axis': c.get('axis_agreement') if c.get('axis_agreement') is not None else (d.get('layout') or {}).get('axis_agreement'),
           'null_records': c.get('null_records'), 'bolt_stats': {k: v_ for k, v_ in (c.get('bolt_stats') or {}).items() if isinstance(v_, (int, float))},
           'arc_changed': (c.get('arc_stats') or {}).get('changed'), 'excluded': len(d.get('excluded_elements') or []),
           'unresolved_top': (c.get('unresolved_top') or [])[:8], 'catalog_misses': (dec.get('catalog_misses') or [])[:8],
           'v_solids': v.get('solids'), 'v_invalid': v.get('invalid'), 'v_nonpos': v.get('nonpos_vol'), 'v_read': v.get('read_status'), 'v_grade': v.get('grade'),
           'step_parts': st.get('parts') or (d.get('step') or {}).get('parts'), 'detail': str(d.get('detail') or '')[:300],
           'name_check': c.get('name_check'), 'layout_keys': sorted((d.get('layout') or {}).keys())[:40] if d.get('layout') else None,
           'poly_ch': (d.get('layout') or {}).get('poly_ch'), 'fmt': (d.get('layout') or {}).get('format'),
           'cut_relations': (d.get('layout') or {}).get('cut_relations'), 'salvaged': (d.get('layout') or {}).get('salvaged'),
           'step_rc': d.get('step_rc'), 'truncated_source': c.get('truncated_source'), 'rescue': bool(d.get('rescue'))}
    return row

def windows_rows():
    """old Windows (C#) pipeline results under derived/db1-step/<disk>/by-sha256/<sha>/result.json"""
    rows = []
    keys = lst('cad-disk-extract/derived/db1-step/', 'result.json')
    def one(k):
        d = getj(k)
        m = (d.get('manifest') or {}) if isinstance(d, dict) else {}
        sha = k.split('/by-sha256/')[1].split('/')[0] if '/by-sha256/' in k else k
        return {'ds': 'd12_windows', 'id': sha, 'key': k, 'status': d.get('status'), 'qa': d.get('qa_verdict'),
                'engine': (m.get('engine') or '').replace('Xsteel', '').replace('Tekla Structures', '').strip() or 'None',
                'parts': m.get('parts'), 'straight': m.get('straight'), 'plates': m.get('plates'), 'bolts': m.get('bolts'), 'bolt_groups': m.get('bolt_groups'),
                'failed_solids': m.get('failed_solids'), 'solids_written': m.get('solids_written'), 'cuts_linked': m.get('cuts_linked'),
                'cuts_applied': m.get('cuts_applied'), 'error': (m.get('error') or d.get('error') or '')[:200], 'err': d.get('_err')}
    with ThreadPoolExecutor(16) as ex:
        rows = list(ex.map(one, keys))
    return rows

def main():
    t0 = time.time(); allrows = []
    for ds, pre in SRC.items():
        keys = lst(pre)
        print(ds, len(keys), flush=True)
        with ThreadPoolExecutor(16) as ex:
            docs = list(ex.map(getj, keys))
        for d in docs:
            if '_err' in d:
                allrows.append({'ds': ds, 'id': d['_key'], 'err': d['_err']}); continue
            allrows.append(compact(ds, d))
    w = windows_rows(); print('windows', len(w), flush=True)
    allrows += w
    body = gzip.compress('\n'.join(json.dumps(r, default=str) for r in allrows).encode())
    s3.put_object(Bucket=B, Key=f'{OUTP}/rows.jsonl.gz', Body=body)
    # summary per ds x engine
    S = {}
    for r in allrows:
        k = f"{r['ds']}|{r.get('engine')}"
        s = S.setdefault(k, {'n': 0, 'status': collections.Counter(), 'reason': collections.Counter(), 'code': collections.Counter(),
                             'sources': collections.Counter(), 'skipped': collections.Counter(), 'models_with_skip': collections.Counter(),
                             'cuts_applied': 0, 'cut_parts': 0, 'models_cuts_none': 0, 'models_with_cut_parts': 0, 'axis_drop': 0,
                             'models_axis_drop': 0, 'excluded': 0, 'bolt': collections.Counter(), 'v_invalid': 0, 'v_nonpos': 0, 'v_read': collections.Counter(),
                             'old_status': collections.Counter(), 'members_rec': 0, 'written': 0, 'poly_ch': collections.Counter(), 'fmt': collections.Counter(),
                             'examples': collections.defaultdict(list), 'unresolved_top': collections.Counter(), 'win': collections.Counter()})
        s['n'] += 1
        s['status'][str(r.get('status'))] += 1
        if r.get('reason'): s['reason'][str(r['reason'])] += 1
        s['code'][str(r.get('code'))] += 1
        if r['ds'] == 'd12_windows':
            for f in ('parts', 'straight', 'plates', 'bolts', 'failed_solids', 'solids_written', 'cuts_linked', 'cuts_applied'):
                try: s['win'][f] += int(r.get(f) or 0)
                except Exception: pass
            s['win']['qa_' + str(r.get('qa'))] += 1
            if len(s['examples'][str(r.get('status'))]) < 3: s['examples'][str(r.get('status'))].append(r['id'][:12])
            continue
        if r.get('old_status'): s['old_status'][str(r['old_status'])] += 1
        for kk, vv in (r.get('sources') or {}).items(): s['sources'][kk] += vv
        sk = r.get('skipped') or {}
        for kk, vv in sk.items():
            s['skipped'][kk] += vv
            if vv: s['models_with_skip'][kk] += 1
        cp = sk.get('cut_part_excluded') or 0
        s['cut_parts'] += cp; s['cuts_applied'] += r.get('cuts_applied') or 0
        if cp: s['models_with_cut_parts'] += 1
        if cp and not (r.get('cuts_applied') or 0): s['models_cuts_none'] += 1
        s['axis_drop'] += r.get('axis_drop') or 0
        if r.get('axis_drop'): s['models_axis_drop'] += 1
        s['excluded'] += r.get('excluded') or 0
        for kk, vv in (r.get('bolt_stats') or {}).items(): s['bolt'][kk] += vv
        s['v_invalid'] += r.get('v_invalid') or 0; s['v_nonpos'] += r.get('v_nonpos') or 0
        s['v_read'][str(r.get('v_read'))] += 1
        s['members_rec'] += r.get('members_rec') or 0; s['written'] += r.get('written') or 0
        s['poly_ch'][str(r.get('poly_ch'))] += 1; s['fmt'][str(r.get('fmt'))] += 1
        for nm, cnt in (r.get('unresolved_top') or []):
            s['unresolved_top'][nm] += cnt
        key_ex = f"{r.get('status')}:{r.get('reason')}"
        if len(s['examples'][key_ex]) < 4: s['examples'][key_ex].append(str(r['id'])[:12])
    out = {}
    for k, s in S.items():
        o = {kk: (dict(vv.most_common(40)) if isinstance(vv, collections.Counter) else vv) for kk, vv in s.items() if kk != 'examples'}
        o['unresolved_top'] = dict(s['unresolved_top'].most_common(25))
        o['examples'] = {kk: vv for kk, vv in s['examples'].items()}
        out[k] = o
    s3.put_object(Bucket=B, Key=f'{OUTP}/summary.json', Body=json.dumps({'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'sec': round(time.time() - t0),
                                                                         'counts': collections.Counter(r['ds'] for r in allrows), 'by_ds_engine': out}, indent=1, default=str).encode())
    print('done', round(time.time() - t0), flush=True)

if __name__ == '__main__':
    main()
