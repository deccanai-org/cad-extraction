#!/usr/bin/env python3
"""IFC audit (read-only): harvest every IFC conversion result and every IFC grade result of zenitude-data-3 into one
compact jsonl.gz (one row per result file). Runs on the agent box; uploads to _state/agentwork/audit-ifc/."""
import json, gzip, sys, time, os
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
OUT = 'cad-disk-extract/zenitude-data-3/_state/agentwork/audit-ifc'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 10, 'mode': 'standard'}, max_pool_connections=40))


def lst(prefix):
    out = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        for o in page.get('Contents', []):
            out.append((o['Key'], o['LastModified'].isoformat(), o['Size']))
    return out


def pick(d, keys):
    return {k: d.get(k) for k in keys if isinstance(d, dict) and d.get(k) is not None}


CEN = ('schema', 'census_version', 'length_unit_m', 'volume_unit_m3', 'products_total', 'expected_parts', 'by_category',
       'rep_types', 'standins_bounding_box', 'products_without_body', 'skipped_nonphysical', 'with_analytic_volume',
       'with_quantity_volume', 'external_refs', 'applications', 'error', 'kernel', 'sec')
VAL = ('read_status', 'roots', 'transferred', 'empty_roots', 'solids', 'shells', 'faces', 'checked', 'valid', 'invalid',
       'nonpos_vol', 'nonfinite', 'invalid_solids_est', 'sampled', 'check_fraction', 'bbox', 'render_ink', 'render_blank',
       'skipped', 'error', 'rc', 'approx_products', 'v6_tags', 'occ_sec', 'products', 'roots_mapped_to_products', 'grade',
       'validated', 'flavour_ok', 'roots_match_parts', 'step_bytes', 'bytes', 'render_error')
STEP = ('bytes', 'parts', 'faces', 'transcode_products', 'tess_products', 'transcode_no_body_rep', 'kernel', 'converter',
        'sec', 'peak_rss_mb', 'degenerate_faces_dropped', 'v6', 'file_length_unit', 'schema_in', 'bbox_mm')
STATS = ('converter', 'schema', 'schema_declared', 'input_kind', 'input_fix', 'm_per_ifc_unit', 'file_length_unit',
         'transcode_products', 'transcode_skipped', 'transcode_no_body_rep', 'transcode_unsupported',
         'transcode_corrupt_coords_tessellated', 'transcode_coverage_pct', 'tess_products', 'parts_without_geometry',
         'verify_L0', 'kernel_L2a', 'dropped_reader_crash_total', 'verify', 'parts', 'faces', 'solids_written',
         'surface_models_written', 'out_bytes', 'peak_rss_mb', 'total_sec', 'levels', 'tags', 'repair', 'exact_parts',
         'approx_parts', 'surface_fallback_parts', 'bbox', 'stats_error', 'tess_failed', 'tess_missing')


def join_c(j):
    if not isinstance(j, dict):
        return None
    o = pick(j, ('mode', 'coverage', 'expected', 'matched', 'step_parts', 'step_parts_present', 'step_parts_unmatched',
                 'surface_parts', 'standins', 'error'))
    v = j.get('volume') or {}
    o['volume'] = pick(v, ('checked', 'outside_5pct', 'outside_curved', 'outside_curved_gross', 'within_5pct', 'median', 'p5', 'p95'))
    o['volume']['worst'] = (v.get('worst') or [])[:8]
    o['missing_examples'] = (j.get('missing_examples') or [])[:5]
    return o


def compact(key, lm, size, d):
    src = 'grade' if '/grade/results/' in key else 'ifc'
    o = {'_src': src, '_key': key, '_lm': lm, '_size': size}
    o.update(pick(d, ('id', 'code', 'status', 'reason', 'detail', 'schema_in', 'kind', 'input_from', 'in_bytes', 'input_fix',
                      'unzipped', 'gunzipped', 'spf_headers', 'concat', 'terminated', 'tail', 'rescue', 'format', 'host',
                      'started', 'finished', 'sec', 'peak_rss_gb', 'alternatives', 'best_of_note', 'unverified_key',
                      'reused', 'reuse_from', 'step_key', 'result_key', 'error', 'transient', 'retry_of', 'zip_members')))
    if isinstance(o.get('detail'), str):
        o['detail'] = o['detail'][:300]
    if isinstance(o.get('error'), str):
        o['error'] = o['error'][:300]
    ex = d.get('excluded_elements')
    if ex is not None:
        o['excluded_elements_n'] = len(ex) if isinstance(ex, list) else ex
    at = []
    for a in d.get('attempts') or []:
        if isinstance(a, dict):
            st = a.get('stats') or {}
            at.append({'rc': a.get('rc'), 'ok': a.get('ok'), 'kernel': a.get('kernel'), 'mode': a.get('mode'),
                       'converter': a.get('converter'), 'parts': a.get('parts'), 'sec': a.get('sec'),
                       'stats': pick(st, STATS)})
    o['attempts'] = at
    o['step'] = pick(d.get('step') or {}, STEP)
    o['validate'] = pick(d.get('validate') or {}, VAL)
    mk = (d.get('validate') or {}).get('markers_kit') or (d.get('validate') or {}).get('markers')
    if mk:
        o['validate']['markers'] = mk
    o['census'] = pick(d.get('census') or {}, CEN)
    if isinstance((d.get('census') or {}).get('by_class'), dict):
        o['census']['by_class'] = dict(sorted(d['census']['by_class'].items(), key=lambda kv: -kv[1])[:25])
    o['join'] = join_c(d.get('join'))
    pr = d.get('prior_result')
    if isinstance(pr, dict):
        o['prior'] = pick(pr, ('status', 'reason', 'code', 'converter', 'grade', 'input_fix', 'finished'))
        o['prior']['stats'] = pick(pr.get('stats') or {}, ('parts', 'transcode_products', 'tess_products', 'transcode_no_body_rep',
                                                           'bbox', 'file_length_unit', 'schema'))
        o['prior']['readback'] = pick(pr.get('readback') or {}, ('skipped', 'read_status', 'roots', 'transferred', 'solids', 'faces'))
        ex = pr.get('excluded_elements')
        if ex is not None:
            o['prior']['excluded_elements_n'] = len(ex) if isinstance(ex, list) else ex
    o['log_tail'] = (d.get('log_tail') or '')[-600:] or None
    return o


def main():
    t0 = time.time()
    keys = lst(ST + '/ifc/results/') + lst(ST + '/grade/results/ifc-')
    print('keys', len(keys), flush=True)

    def one(k):
        try:
            d = json.loads(s3.get_object(Bucket=B, Key=k[0])['Body'].read())
            return compact(k[0], k[1], k[2], d)
        except Exception as e:
            return {'_key': k[0], '_err': f'{type(e).__name__}: {str(e)[:200]}'}
    with ThreadPoolExecutor(24) as ex:
        rows = list(ex.map(one, keys))
    p = '/work/agentwork/audit-ifc/harvest.jsonl.gz'
    with gzip.open(p, 'wt') as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + '\n')
    s3.upload_file(p, B, OUT + '/harvest.jsonl.gz')
    print('harvest rows', len(rows), 'errors', sum(1 for r in rows if '_err' in r), 'sec', round(time.time() - t0, 1), flush=True)


if __name__ == '__main__':
    main()
