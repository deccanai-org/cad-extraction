#!/usr/bin/env python3
"""Zenitude-data-3 conversion index + classifier + status (runs on the coordinator; instance role).

Inputs (bim, zenitude-data-3/_state/conv/): scan/contents_{ifc,db1,sds2}.jsonl.gz (every distinct model + action),
  {ifc,db1,sds2}/results/*.json (new conversions), grade/results/*.json (reused conversions re-graded), {pipe}/jobs.json,
  claims/, hosts/ (progress). Rules: s3://annotationprod/cad-disk-extract/_control/z3conv/coord/rules.json (defaults below).
Outputs: _state/conv/index.jsonl.gz, class_1_complete.jsonl.gz, class_2_partial.jsonl.gz, class_3_broken.jsonl.gz,
  index_summary.json; _state/conv_status.json (counts only).
usage: build_index.py [--loop SECONDS] [--final]

Two axes per model:
  class  = conversion fidelity relative to the source (1 complete, 2 partial / stand-ins / needs, 3 broken)
  corpus = content richness of the STEP: A = class 1 with connection parts; B = connection parts present but with stand-ins
           (each listed with its real type) and/or listed missing pieces; C = members only (no connection pieces in the STEP;
           `source_connections` says whether the source had them); null for class 3 and for non-steel models (domain).
"""
import os, sys, json, gzip, time, math, argparse, collections, traceback, re
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hashlib
import grade_join
GJV = hashlib.sha256(open(grade_join.__file__, 'rb').read()).hexdigest()[:12]
B = 'bim-proprietary-data'; ROOT = 'cad-disk-extract/zenitude-data-3'; ST = f'{ROOT}/_state/conv'
CB = 'annotationprod'; CTL = 'cad-disk-extract/_control/z3conv'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 40, 'mode': 'standard'}, max_pool_connections=96))
W = os.environ.get('INDEX_WORK', '/work/index'); os.makedirs(W, exist_ok=True)
DEFAULT_RULES = {
    'version': 'z3-rules-1',
    'class3_member_coverage_below': 0.5,
    'class3_all_coverage_below': 0.5,
    'volume_tolerance': 0.05,
    'volume_outside_parts_allowed': 0,
    'curved_volume_counts': False,
    'invalid_solids_allowed_class1': 0,
    'sds2_weight_band_class1': [0.95, 1.05],
    'sds2_weight_band_class3': [0.75, 1.3],
    'sds2_family_weight_tolerance': 0.05,
    'sds2_family_min_pieces': 5,
    'tolerated_standin_types': [],
    'v6_blocking_tags': ['L2-alt-source', 'L3-partial-surface', 'L4-surface', 'open-surface', 'unverified'],
    'v6_info_tags': ['approx-curved', 'L1-triangulated'],          # e.g. ["joist_openweb_standin"]: listed, but do not block class 1 (owner decision pending)
    'render_blank_ink': 0.00002,
    'render_near_empty_ink': 0.002,
    'bbox_abs_limit_mm': 1e10,
    'bbox_extent_suspicious_mm': 5e6,
    'steel_domain_min_share': 0.5,
    'text_only_max_class': 2,
}
DEFAULT_RULES['bolt_standard_geometry_exact'] = True
RULES = dict(DEFAULT_RULES)
CACHE = {}


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def lst(prefix, bucket=B):
    out = []
    for p in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        out += p.get('Contents', [])
    return out


def getj(key, bucket=B):
    try:
        b = s3.get_object(Bucket=bucket, Key=key)['Body'].read()
    except ClientError:
        return None
    if b[:2] == b'\x1f\x8b':
        b = gzip.decompress(b)
    return json.loads(b)


def load_results(prefix):
    objs = [o for o in lst(prefix) if o['Key'].endswith('.json')]

    def one(o):
        c = CACHE.get(o['Key'])
        if c and c[0] == o['ETag']:
            return o['Key'], c[1]
        r = getj(o['Key'])
        CACHE[o['Key']] = (o['ETag'], r)
        return o['Key'], r
    out = {}
    with ThreadPoolExecutor(64) as ex:
        for k, r in ex.map(one, objs):
            if r:
                out[k.rsplit('/', 1)[-1][:-5]] = r
    return out


def contents(pipe):
    key = f'{ST}/scan/{pipe}'
    h = s3.head_object(Bucket=B, Key=f'{ST}/scan/contents_{pipe}.jsonl.gz')
    c = CACHE.get(key)
    if c and c[0] == h['ETag']:
        return c[1]
    rows = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{ST}/scan/contents_{pipe}.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]
    CACHE[key] = (h['ETag'], rows)
    return rows


def bbox_ok(bb):
    if not bb or len(bb) != 6:
        return None
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) >= RULES['bbox_abs_limit_mm'] for v in bb):
        return False
    return all(bb[i] <= bb[i + 3] for i in range(3))


def extent(bb):
    try:
        return max(bb[i + 3] - bb[i] for i in range(3))
    except Exception:
        return None


# ------------------------------------------------------------------ classifiers
GRADING_ERRORS = []


def base_row(c, pipe):
    return {'pipeline': pipe, 'id': c['id'], 'sha256': c.get('sha256'), 'fpc': c.get('fpc'), 'jsetup_sha256': c.get('jsetup_sha256'),
            'size': c.get('size') or c.get('model_bytes'), 'n_paths': c.get('n_paths'), 'paths': (c.get('paths') or [])[:5],
            'reused': False, 'reuse_from': None, 'step_key': None, 'render_key': None, 'class': None, 'corpus': None, 'domain': None,
            'coverage_members': None, 'coverage_connections': None, 'coverage_other': None, 'parts_source': None, 'parts_step': None,
            'solids': None, 'invalid_solids': None, 'standins': [], 'needs': [], 'issues': [], 'reasons': [], 'weight_ratio': None,
            'graded_by': None, 'status': None}


V6RT = {'L2-alt-source': 'part rebuilt from an alternative source representation', 'L3-partial-surface': 'part with some faces kept as open shells (solid repair failed)', 'L4-surface': 'part written as a surface model (no valid solid)', 'open-surface': 'zero-thickness double-sided source surface (not a solid)', 'unverified': 'part not verified by the per-part read-back'}


V6_ALIAS = {'L1': 'L1-triangulated', 'L2': 'L2-alt-source', 'L3': 'L3-partial-surface', 'L4': 'L4-surface'}


def v6_tags(row, tags):
    """ifc2step6 per-part tags ([v6:...] in PRODUCT.description / stats.json): blocking ones are stand-ins, the rest info"""
    if not isinstance(tags, dict) or row.get('_v6_done'):
        return
    row['_v6_done'] = True
    norm = collections.Counter()
    for t, n in tags.items():                   # ifc2step6 builds write the level tags short (L2) or long (L2-alt-source)
        norm[V6_ALIAS.get(t, t)] += n or 0
    tags = dict(norm)
    row['v6_tags'] = tags
    for t, n in tags.items():
        if not n:
            continue
        if t in (RULES.get('v6_blocking_tags') or []):
            row['standins'].append({'type': f'v6_{t}', 'real_type': V6RT.get(t, t), 'count': n})
        elif t in (RULES.get('v6_info_tags') or []):
            row['issues_info'] = (row.get('issues_info') or []) + [f'{n} parts tagged {t} (faceted / triangulated representation of exact geometry)']


def step_checks(row, v, have_occ_keys=True):
    """common STEP signals from a step_check / validate dict"""
    rs = v.get('read_status')
    if v.get('v6_tags'):
        v6_tags(row, v['v6_tags'])
    if v.get('approx_products'):
        row['approx_products_in_step'] = v['approx_products']
    if rs == 'ok':
        row['graded_by'] = 'occ_readback' + ('_sampled' if v.get('sampled') else '')
        row['solids'] = v.get('solids')
        inv = v.get('invalid_solids_est', v.get('invalid'))
        row['invalid_solids'] = inv
        if (v.get('solids') or 0) == 0 and (v.get('faces') or 0) == 0:
            row['reasons'].append('step_no_geometry')
        if inv and inv > RULES['invalid_solids_allowed_class1']:
            row['issues'].append(f'invalid_solids:{inv}')
        if v.get('nonpos_vol'):
            row['issues'].append(f'non_positive_volume_solids:{v["nonpos_vol"]}')
        if v.get('nonfinite'):
            row['issues'].append(f'parts_with_nonfinite_coords:{v["nonfinite"]}')
        if v.get('empty_roots'):
            row['issues'].append(f'roots_not_transferred:{v["empty_roots"]}')
    elif 'skipped' in v:
        row['graded_by'] = 'text_only (STEP too large for OCC read-back)'
        row['issues'].append('not_read_back_large_file')
    elif str(v.get('error', '')).startswith('read-back rc -9') or v.get('rc') == -9:
        row['graded_by'] = 'not verified (read-back ran out of memory on a shared box)'
        row['issues'].append('not_read_back_out_of_memory')
    else:
        row['reasons'].append('step_read_failed')
    bb = v.get('bbox') or v.get('bbox_mm')
    ok = bbox_ok(bb)
    if ok is False:
        row['reasons'].append('bbox_absurd')
    elif ok and extent(bb) and extent(bb) > RULES['bbox_extent_suspicious_mm']:
        row['issues'].append(f'bbox_extent_{extent(bb) / 1e6:.1f}km')
    row['bbox_mm'] = bb
    ink = v.get('render_ink')
    if ink is not None and ink < RULES['render_blank_ink']:
        row['reasons'].append('blank_render')
    elif ink is not None and ink < RULES['render_near_empty_ink']:
        row['render_near_empty'] = True
    if v.get('render_error'):
        row['issues'].append('render_error')


def vol_issues(row, j):
    vol = (j or {}).get('volume') or {}
    # round sections: tessellation loses up to ~4 %, so +-5 % is not applied to them, but a curved part outside the
    # tessellation band (grade_join CURVED_BAND 0.90..1.05: wrong length / section) counts like any other part
    n = (vol.get('outside_5pct') or 0) + ((vol.get('outside_curved') or 0) if RULES['curved_volume_counts'] else (vol.get('outside_curved_gross') or 0))
    row['weight_ratio'] = {k: vol.get(k) for k in ('checked', 'within_5pct', 'outside_5pct', 'outside_curved', 'outside_curved_gross', 'median', 'p5', 'p95')} if vol else None
    if n > RULES['volume_outside_parts_allowed']:
        row['issues'].append(f'parts_outside_volume_tolerance:{n}/{vol.get("checked")}')


def grading_failed(row, r):
    """reused STEP whose re-grading failed: no verdict from absent signals (before: fell through to class 3 'step_read_failed')"""
    row['status'] = 'grading_failed'; row['issues'].append(f'grading:{r.get("reason")}')
    if r.get('reason') == 'reused_step_missing':
        row['class'] = 3; row['reasons'].append('reused_step_missing')
    return row                 # otherwise class None (ungraded): re-graded by the grade fleet, listed under by_status


def finish_class(row, has_conn, src_conn, steel=True):
    cm = row['coverage_members']; ca = row.get('coverage_all')
    if row['reasons']:
        row['class'] = 3
    elif cm is not None and cm < RULES['class3_member_coverage_below']:
        row['class'] = 3; row['reasons'].append(f'member_coverage_{cm:.2f}')
    elif cm is None and ca is not None and ca < RULES['class3_all_coverage_below']:
        row['class'] = 3; row['reasons'].append(f'part_coverage_{ca:.2f}')
    else:
        partial = any(x is not None and x < 1.0 for x in (row['coverage_members'], row['coverage_connections'], row['coverage_other'], ca))
        tol = set(RULES.get('tolerated_standin_types') or [])
        for s_ in row['standins']:
            if s_['type'] in tol:
                s_['tolerated'] = True
        blocking = [s_ for s_ in row['standins'] if not s_.get('tolerated')]
        if row.get('approx_products_in_step') and not blocking:
            row['standins'].append({'type': 'approx_tagged_products', 'real_type': 'parts named [approx: ...] in the STEP', 'count': row['approx_products_in_step']})
            blocking = row['standins'][-1:]
        if partial or blocking or row['needs'] or row['issues']:
            row['class'] = 2
        else:
            row['class'] = 1
    if row['class'] == 3:
        row['corpus'] = None
    elif not steel:
        row['corpus'] = None
    elif not has_conn:
        row['corpus'] = 'C'; row['source_connections'] = src_conn
    elif row['class'] == 1:
        row['corpus'] = 'A'
    else:
        row['corpus'] = 'B'
    return row


IFC_FAIL = {'no_geometry_grid_or_annotation_only': 'source_geometry_free (grids/annotations only)', 'not_step21': 'source_not_ifc',
            'not_ifc_ole2_document': 'source_not_ifc', 'not_ifc_cis2': 'source_cis2_not_ifc', 'empty_or_stub_file': 'source_empty_or_stub',
            'all_zero_file': 'source_corrupt_all_zero', 'truncated_source': 'source_truncated', 'ifcxml_unsupported': 'ifcxml_reader_unavailable',
            'empty_output': 'no_geometry_written', 'corrupt_coordinates': 'bbox_absurd (corrupt source coordinates)', 'readback_fail': 'step_read_failed',
            'readback_crash': 'step_read_crash', 'kernel_crash': 'converter_kernel_crash', 'kernel_hang': 'converter_kernel_hang',
            'timeout': 'converter_timeout', 'parse_error': 'source_parse_error', 'convert_error': 'converter_error', 'zip_encrypted': 'source_encrypted',
            'zip_unreadable': 'source_corrupt_zip', 'empty_zip': 'source_empty_zip', 'out_of_memory': 'converter_out_of_memory'}


def classify_ifc(c, res, grade):
    row = base_row(c, 'ifc')
    act = c['action']
    if act == 'unresolved_input':
        row.update(status='no_source_copy', **{'class': 3}); row['reasons'].append('source_copy_not_found'); row['needs'].append('a stored copy of the source IFC')
        return row
    if act == 'failed_before_same_converter':
        row.update(status='failed_before', reused=True, reuse_from='data-4', **{'class': 3})
        row['reasons'].append(IFC_FAIL.get(c.get('prior_reason'), c.get('prior_reason') or 'failed'))
        return row
    if act == 'reuse' and res is not None and res.get('status') == 'ok':
        row['supersedes'] = {'from': (c.get('reuse') or {}).get('from'), 'step_key': (c.get('reuse') or {}).get('step_key')}
        act = 'convert'
    if act == 'reuse':
        r = grade; row.update(reused=True, reuse_from=(c.get('reuse') or {}).get('from'), step_key=(c.get('reuse') or {}).get('step_key'))
        if r is None:
            row['status'] = 'grading_pending'; return row
        if r.get('status') != 'ok':
            return grading_failed(row, r)
    else:
        r = res
        if r is None:
            row['status'] = 'pending'; return row
        row['converter_code'] = r.get('code')
        row['schema'] = r.get('schema_in')
        if r.get('status') != 'ok':
            row.update(status='failed', **{'class': 3}); row['reasons'].append(IFC_FAIL.get(r.get('reason'), r.get('reason') or 'failed'))
            if r.get('reason') == 'ifcxml_unsupported':
                row['needs'].append('an ifcXML reader (both ifcopenshell builds ship without one)')
            return row
        row['step_key'] = (r.get('step') or {}).get('key') or r.get('out_key')
    row['status'] = row['status'] or 'converted'
    row['render_key'] = r.get('render_key')
    row['step_bytes'] = (r.get('step') or {}).get('bytes') or (r.get('validate') or {}).get('step_bytes') or r.get('step_bytes') or r.get('out_bytes')
    if r.get('detail_prefix'):
        row['detail_prefix'] = r['detail_prefix']
    if ((r.get('step') or {}).get('v6') or {}).get('tags') and not (r.get('validate') or {}).get('v6_tags'):
        v6_tags(row, r['step']['v6']['tags'])
    v = r.get('validate') or {}
    step_checks(row, v)
    cen = r.get('census') or {}; j = r.get('join') or {}
    row['schema'] = row.get('schema') or cen.get('schema')
    exp = cen.get('by_category') or {}
    row['parts_source'] = cen.get('expected_parts')
    row['parts_step'] = v.get('transferred') or (r.get('step') or {}).get('parts') or ((r.get('prior_result') or {}).get('stats') or {}).get('parts')
    if not cen.get('error') and cen.get('expected_parts') is not None and (not j or j.get('error')):
        # source inventory present, but no per-part STEP data (STEP too large / read-back memory-killed): coverage from the
        # converter's own part count until the final pass (per-part read-back / streamed verification) fills it in
        stc = (r.get('step') or {}).get('parts') or ((r.get('prior_result') or {}).get('stats') or {}).get('parts')
        ep = cen.get('expected_parts') or 0
        row['issues'].append('per_part_verification_pending')
        if stc is not None and ep:
            row['coverage_all'] = min(1.0, math.floor(stc / ep * 1e4) / 1e4)
            row['coverage_basis'] = 'converter part count vs source inventory'
        j = {}
    elif cen.get('error') or not j or j.get('error'):
        row['issues'].append('source_inventory_unavailable')
        st = (r.get('step') or {}) if not row['reused'] else ((r.get('prior_result') or {}).get('stats') or {})
        tp, tess, sk = st.get('transcode_products'), st.get('tess_products'), None
        row['coverage_all'] = None
    else:
        cov = j.get('coverage') or {}
        row['coverage_members'] = cov.get('member'); row['coverage_connections'] = cov.get('connection'); row['coverage_other'] = cov.get('other')
        row['coverage_all'] = cov.get('all'); row['join_mode'] = j.get('mode')
        if j.get('mode') == 'name':
            row['issues_info'] = ['coverage matched by part name (older writer without source ids)']
        elif j.get('mode') == 'count':
            row['issues_info'] = ['coverage by part count: names of the older writer do not match the source (no source ids in that STEP)']
            row['issues'].append('coverage_by_part_count_only')     # no part identity and no per-part volume check: not provable 100 %
        for s_ in j.get('standins') or []:
            row['standins'].append({'type': s_['type'], 'real_type': s_['real_type'], 'count': s_['count']})
        if j.get('missing_examples') and (cov.get('all') or 1) < 1:
            row['missing_examples'] = j['missing_examples'][:10]
        vol_issues(row, j)
        if j.get('surface_parts'):
            # a part that reads back with faces but no solid: SHELL_BASED_SURFACE_MODEL / OPEN_SHELL (the transcode of
            # IfcShellBasedSurfaceModel, also when its shells are IfcClosedShell) or a FACETED_BREP whose shell is not closed.
            # No validity / volume check is possible on it, so 'all solids valid' is unproven -> class 2
            row['issues'].append(f'parts_without_solid:{j["surface_parts"]}')
    exc = r.get('excluded_elements') or (r.get('prior_result') or {}).get('excluded_elements')
    if exc:
        row['issues'].append(f'kernel_crash_elements_excluded:{len(exc) if isinstance(exc, list) else exc}')
    fixes = r.get('input_fix') or (r.get('prior_result') or {}).get('input_fix') or []
    if isinstance(fixes, str):
        fixes = [fixes]
    if 'truncated_tail_repaired' in fixes:
        row['issues'].append('source_truncated_tail_dropped')
    row['input_fixes'] = fixes or None
    nm = (exp.get('member') or 0); nc = (exp.get('connection') or 0); tot = sum(exp.values()) if exp else 0
    steel = tot > 0 and (nm + nc) >= RULES['steel_domain_min_share'] * tot
    row['domain'] = 'steel' if steel else ('non_steel' if tot else None)
    matched_conn = ((j.get('matched') or {}).get('connection') or 0) if j else 0
    if not j and row.get('coverage_basis') and (row.get('coverage_all') or 0) >= 0.999:
        matched_conn = nc                      # all source parts written (by count): the connection parts are among them
    return finish_class(row, has_conn=matched_conn > 0, src_conn=nc, steel=steel)


DB1_APPROX = {
    'parametric_angle': 'angle: root radius assumed = t', 'parametric_angle_equal': 'equal-leg angle from L a*t: root radius assumed = t',
    'parametric_rhs': 'RHS: corner radii from the EN 10219 rule', 'parametric_hss': 'HSS: corner radii assumed 2t',
    'catalog_upn_alias': 'U<n> read as UPN<n>', 'parametric_grating': 'bar grating written as a solid plate',
    'parametric_stud_shank': 'headed stud written as its shank only', 'parametric_panel': 'panel from an AxB name (orientation assumed)'}
DB1_FAIL = {'no_member_layout': 'decoder_limit: no verifiable member table for this Tekla record variant',
            'unapproved_engine': 'decoder_limit: Tekla engine version without a verified layout', 'no_engine_banner': 'source_not_tekla_db1',
            'empty_model': 'source_geometry_free (blank/template model)', 'suspect_attr_link': 'decoder_guard: attribute link check failed',
            'suspect_orientation': 'decoder_guard: member orientation check failed', 'deferred_layout': 'decoder_timeout (layout discovery)',
            'convert_error': 'source_corrupt_or_decoder_error', 'no_resolvable_members': 'no member resolvable to a profile',
            'step_kernel_crash': 'converter_kernel_crash', 'step_kernel_hang': 'converter_kernel_hang', 'step_timeout': 'converter_timeout',
            'step_fail': 'converter_error', 'absurd_bbox': 'bbox_absurd', 'empty_output': 'no_geometry_written', 'readback_crash': 'step_read_crash',
            'convert_timeout': 'decoder_timeout', 'convert_fail': 'decoder_error', 'bad_flavour': 'step_format_error'}


def classify_db1(c, res, grade):
    row = base_row(c, 'db1')
    act = c['action']
    if act == 'excluded_xslib':
        return None
    if act == 'empty_file':
        row.update(status='empty_source', **{'class': 3}); row['reasons'].append('source_empty_file'); return row
    if act == 'unresolved_input':
        row.update(status='no_source_copy', **{'class': 3}); row['reasons'].append('source_copy_not_found'); return row
    if act == 'failed_before_same_converter':
        row.update(status='failed_before', reused=True, **{'class': 3})
        row['reasons'].append(DB1_FAIL.get(c.get('prior_reason'), c.get('prior_reason') or 'failed'))
        if c.get('prior_reason') in ('no_member_layout', 'unapproved_engine'):
            row['needs'].append('reverse-engineered record layout for this Tekla version/variant')
        return row
    if act == 'reuse' and res is not None and res.get('status') == 'ok':
        row['supersedes'] = {'from': (c.get('reuse') or {}).get('from'), 'step_key': (c.get('reuse') or {}).get('step_key')}
        act = 'convert'
    if act == 'reuse':
        r = grade; row.update(reused=True, reuse_from=(c.get('reuse') or {}).get('from'), step_key=(c.get('reuse') or {}).get('step_key'))
        if r is None:
            row['status'] = 'grading_pending'; return row
        if r.get('step_key'):
            row['step_key'] = r['step_key']
        if r.get('status') != 'ok':
            return grading_failed(row, r)
    else:
        r = res
        if r is None:
            row['status'] = 'pending'; return row
        row['engine'] = r.get('engine'); row['converter_code'] = r.get('code')
        if r.get('status') != 'ok':
            row.update(status='failed', **{'class': 3}); row['reasons'].append(DB1_FAIL.get(r.get('reason'), r.get('reason') or 'failed'))
            if r.get('reason') in ('no_member_layout', 'unapproved_engine'):
                row['needs'].append(f'reverse-engineered record layout for Tekla {r.get("engine")}')
            return row
        row['step_key'] = (r.get('step') or {}).get('key') or r.get('out_key')
    row['status'] = row['status'] or 'converted'
    row['engine'] = row.get('engine') or r.get('engine')
    row['render_key'] = r.get('render_key')
    row['step_bytes'] = (r.get('step') or {}).get('bytes') or (r.get('validate') or {}).get('step_bytes') or r.get('step_bytes') or r.get('out_bytes')
    if r.get('detail_prefix'):
        row['detail_prefix'] = r['detail_prefix']
    if ((r.get('step') or {}).get('v6') or {}).get('tags') and not (r.get('validate') or {}).get('v6_tags'):
        v6_tags(row, r['step']['v6']['tags'])
    v = r.get('validate') or {}
    step_checks(row, v)
    dec = r.get('decoded') or {}
    j = r.get('join') or {}
    if row.get('reuse_from') == 'disk-1/2-windows':
        # the Windows (C#) pipeline writes the whole model as ONE STEP product: no per-part join is possible -> its own counts
        pm = (r.get('prior_result') or {}).get('manifest') or {}
        try:
            parts = int(pm.get('parts') or 0); written = int(pm.get('solids_written') or 0); bolts = int(pm.get('bolts') or 0)
        except ValueError:
            parts = written = bolts = 0
        row['parts_source'] = parts; row['parts_step'] = v.get('transferred') or written
        row['coverage_all'] = round(written / parts, 4) if parts else None
        row['issues'].append('inventory from the Windows pipeline manifest (parts vs solids written)')
        if bolts:
            row['standins'].append({'type': 'bolt_solid_no_hole', 'real_type': 'bolt (holes not cut)', 'count': bolts})
        has_conn = int(pm.get('plates') or 0) + bolts > 0
        return finish_class(row, has_conn=has_conn, src_conn=None, steel=True)
    exp = dec.get('expected') or {}; wr = dec.get('written') or {}
    rd = r.get('redecode') or (r.get('convert') or {})
    axis_drop = rd.get('axis_mismatch_dropped') or 0
    jall = ((j.get('coverage') or {}).get('all')) if j and not j.get('error') else None
    if jall is None:
        row['issues'].append('step_vs_decoder_join_unavailable')
        jall = 1.0 if j == {} and v.get('transferred') == (r.get('step') or {}).get('written') else jall
    f = jall if jall is not None else 1.0
    em = (exp.get('member') or 0) + axis_drop
    row['coverage_members'] = round((wr.get('member') or 0) * f / em, 4) if em else None
    ec = exp.get('connection') or 0
    row['coverage_connections'] = round((wr.get('connection') or 0) * f / ec, 4) if ec else None
    eo = exp.get('other') or 0
    row['coverage_other'] = round((wr.get('other') or 0) * f / eo, 4) if eo else None
    tot = em + ec + eo
    row['coverage_all'] = round((sum(wr.values()) * f) / tot, 4) if tot else None
    row['parts_source'] = tot; row['parts_step'] = v.get('transferred')
    if axis_drop:
        row['issues'].append(f'parts_dropped_by_axis_guard:{axis_drop}')
    bg = dec.get('bolt_groups') or 0
    if bg:
        row['needs'].append(f'bolt decoding: {bg} Tekla bolt group(s) not written (decoder limit)')
        row['standins'].append({'type': 'pieces_without_bolt_holes', 'real_type': f'parts joined by {bg} bolt group(s)', 'count': bg})
    for src_, n_ in (dec.get('written_by_source') or {}).items():
        if src_ in DB1_APPROX and n_:
            row['standins'].append({'type': f'section_{src_}', 'real_type': DB1_APPROX[src_], 'count': n_})
    bs = (r.get('convert') or {}).get('bolt_stats') or (r.get('redecode') or {}).get('bolt_stats')
    if bs and bs.get('bolts'):
        row['bolt_stats'] = bs
        n_tab = bs.get('standard_table_geometry') if isinstance(bs.get('standard_table_geometry'), int) else 0
        n_nom = bs['bolts'] - n_tab if RULES.get('bolt_standard_geometry_exact') else bs['bolts']
        if n_nom > 0:
            row['standins'].append({'type': 'bolt_nominal_head_nut', 'real_type': 'bolt (position, diameter, length from the Tekla record; head/nut nominal: '
                                    'standard unknown or no table for its diameter)', 'count': n_nom})
        n_hn = bs.get('holes_nominal_clearance', bs.get('holes_cut') or 0)
        if n_hn:
            row['standins'].append({'type': 'hole_clearance_nominal', 'real_type': 'bolt hole (d + standard clearance; tolerance not decoded)', 'count': n_hn})
        if bs.get('washers_nominal'):
            row['standins'].append({'type': 'washer_nominal', 'real_type': 'washer (count from the assembly flags; thickness nominal)', 'count': bs['washers_nominal']})
        if bs.get('washer_side_inferred'):
            row['standins'].append({'type': 'washer_side_inferred', 'real_type': 'bolt with head-side / multiple washers (side inferred from the flags)', 'count': bs['washer_side_inferred']})
        if bs.get('bolts_shifted_to_plies'):
            row['standins'].append({'type': 'bolt_axial_position_fitted', 'real_type': 'bolt (axial position fitted to the connected plies)', 'count': bs['bolts_shifted_to_plies']})
        if bs.get('bolts_without_holed_part'):
            row['issues_info'] = (row.get('issues_info') or []) + [f'{bs["bolts_without_holed_part"]} bolts pass through no written part (holes not cut there)']
    if dec.get('records_without_profile'):
        row['needs'].append(f'records without profile: {dec["records_without_profile"]} part records without a profile name (Tekla 8.x bolt groups) not written')
    if dec.get('profiles_without_size'):
        row['needs'].append('profile sizes missing in the model: ' + ', '.join(f'{p!r} x{n}' for p, n in dec['profiles_without_size'][:5]))
    if dec.get('catalog_misses'):
        row['needs'].append('profile catalog entries: ' + ', '.join(f'{p} x{n}' for p, n in dec['catalog_misses'][:8]))
    if rd.get('skipped', {}).get('cut_body_unbuilt'):
        row['issues'].append(f'cuts_not_applied:{rd["skipped"]["cut_body_unbuilt"]}')
    if r.get('excluded_elements'):
        row['issues'].append(f'kernel_crash_elements_excluded:{len(r["excluded_elements"])}')
    uh = (r.get('unholed_elements') or {}).get('unholed') if isinstance(r.get('unholed_elements'), dict) else None
    if uh:
        # kit_v2 crash fallback: the part is kept, only its bolt holes are left uncut
        row['issues'].append(f'bolt_holes_uncut_kernel_crash:{sum(v for v in uh.values() if isinstance(v, (int, float)))}')
    vol_issues(row, j)
    if j.get('surface_parts'):
        row['issues'].append(f'parts_without_solid:{j["surface_parts"]}')
    has_conn = (wr.get('connection') or 0) > 0
    return finish_class(row, has_conn=has_conn, src_conn=ec, steel=True)


SDS2_FAIL = {'no_members_to_calibrate': 'no_member_records_read (source emptiness NOT proven: most such data-3 jobs hold one DWF Import / '
                                       'REFERENCE MODEL member with thousands of placed pieces; re-run on v5.1 for corpus R or empty_job_proof)',
             'job_folder_incomplete': 'source_job_files_missing',
             'missing_job_file': 'source_job_files_missing', 'invalid_solids': 'step_invalid_solids',
             'step_write_failed': 'converter_wrote_nothing (source NOT proven empty: e.g. a DWF-imported reference model the v4/v5 '
                                  'builders skip; re-run on v5.1)',
             'timeout': 'converter_timeout', 'out_of_memory': 'converter_out_of_memory', 'unsupported_job_mtrl_layout': 'decoder_limit: job_mtrl layout',
             'verification_counts_missing': 'step_read_failed', 'absurd_bbox': 'bbox_absurd', 'steel_weight_mismatch': 'steel_weight_mismatch',
             'model_files_unavailable': 'source_copy_not_found'}


def classify_sds2(c, res, grade):
    row = base_row(c, 'sds2')
    act = c['action']
    if act == 'reuse' and res is not None and res.get('status') in ('ok', 'ok_stage1'):
        row['supersedes'] = {'from': (c.get('reuse') or {}).get('from'), 'step_key': (c.get('reuse') or {}).get('step_key')}
        act = 'convert'
    if act == 'reuse':
        r = grade; row.update(reused=True, reuse_from=(c.get('reuse') or {}).get('from'), step_key=(c.get('reuse') or {}).get('step_key'))
        if r is None:
            row['status'] = 'grading_pending'; return row
        if r.get('step_key'):
            row['step_key'] = r['step_key']
        if r.get('status') != 'ok':
            return grading_failed(row, r)
        s2 = r.get('stage2') or {}; stage = 2
        row['version'] = (r.get('prior_result') or {}).get('version') or s2.get('version')
    else:
        r = res
        if r is None:
            row['status'] = 'pending'; return row
        row['converter_code'] = r.get('code'); row['version'] = r.get('version')
        if r.get('status') == 'fail':
            row.update(status='failed', **{'class': 3})
            ep = (r.get('manifest') or {}).get('empty_job_proof')
            if ep:
                row['reasons'].append('source_no_members (empty job, proven: ' + json.dumps(ep, default=str)[:160] + ')')
            else:
                row['reasons'].append(SDS2_FAIL.get(r.get('reason'), r.get('reason') or 'failed'))
            if r.get('reason') in ('job_folder_incomplete', 'missing_job_file', 'model_files_unavailable'):
                row['needs'].append('the complete SDS/2 job folder (main/ mem/ subm/)')
            return row
        row['step_key'] = (r.get('step') or {}).get('key')
        stage = (r.get('step') or {}).get('stage') or 2
        s2 = r.get('stage2') or {}
    row['status'] = row['status'] or ('converted' if stage == 2 else 'converted_stage1_members_only')
    row['version'] = r.get('version') or s2.get('version')
    row['converter'] = (r.get('converter') or {}).get('label') or 'v4'
    row['render_key'] = r.get('render_key')
    row['step_bytes'] = (r.get('step') or {}).get('bytes') or (r.get('validate') or {}).get('step_bytes') or r.get('step_bytes') or r.get('out_bytes')
    if r.get('detail_prefix'):
        row['detail_prefix'] = r['detail_prefix']
    if ((r.get('step') or {}).get('v6') or {}).get('tags') and not (r.get('validate') or {}).get('v6_tags'):
        v6_tags(row, r['step']['v6']['tags'])
    if stage == 1:
        s1 = r.get('stage1') or {}
        v = dict(r.get('validate1') or {}); v.setdefault('read_status', 'ok')
        row['graded_by'] = 'converter_verify'
        row['solids'] = s1.get('solids'); row['invalid_solids'] = (s1.get('solids') or 0) - (s1.get('valid') or 0)
        if v.get('render_ink') is not None and v['render_ink'] < RULES['render_blank_ink']:
            row['reasons'].append('blank_render')
        if bbox_ok(s1.get('bbox_mm')) is False:
            row['reasons'].append('bbox_absurd')
        row['issues'].append(f'members_only_stage1_fallback (stage 2: {r.get("stage2_reason")})')
        row['coverage_members'] = 1.0
        return finish_class(row, has_conn=False, src_conn=None, steel=True)
    man = r.get('manifest') or {}
    if man and man.get('counts'):
        return classify_sds2_manifest(row, r, man, s2)
    v = r.get('validate') or {}
    row['graded_by'] = 'converter_verify (OCP read-back, BRepCheck per placed solid)'
    sol, val = v.get('solids'), v.get('valid')
    row['solids'] = sol; row['invalid_solids'] = (sol - val) if sol is not None and val is not None else None
    if sol is None or val is None:
        row['reasons'].append('step_read_failed')
    elif sol == 0:
        row['reasons'].append('step_no_geometry')
    elif row['invalid_solids']:
        row['issues'].append(f'invalid_solids:{row["invalid_solids"]}')
    ink = v.get('render_ink')
    if ink is not None and ink < RULES['render_blank_ink']:
        row['reasons'].append('blank_render')
    bb = v.get('bbox_mm') or r.get('bbox_mm') or (r.get('step') or {}).get('bbox_mm')
    if bbox_ok(bb) is False:
        row['reasons'].append('bbox_absurd')
    row['bbox_mm'] = bb
    inv = r.get('inventory') or {}
    pk = inv.get('pieces_by_kind') or {}; sk = inv.get('skipped_by_kind') or {}
    env = pk.get('member', 0)
    rolled = pk.get('rolled', 0); rolled_s = sk.get('rolled', 0)
    den = rolled + rolled_s + env
    row['coverage_members'] = round((rolled + env) / den, 4) if den else (None if inv else None)
    conn = pk.get('plate', 0) + pk.get('fastener', 0); conn_s = sk.get('plate', 0) + sk.get('fastener', 0)
    bolts = (s2.get('bolts') or 0)
    row['coverage_connections'] = round(conn / (conn + conn_s), 4) if conn + conn_s else None
    row['parts_source'] = (sum(pk.values()) + sum(sk.values()) + bolts) if inv else None
    row['parts_step'] = (sum(pk.values()) + bolts) if inv else s2.get('solids')
    row['coverage_all'] = round(row['parts_step'] / row['parts_source'], 4) if row['parts_source'] else None
    if not inv or not inv.get('pieces_by_kind'):
        row['issues'].append('piece_inventory_unavailable')
    for s_ in inv.get('standins') or []:
        row['standins'].append({'type': s_['type'], 'real_type': s_['real_type'], 'count': s_['count']})
    if inv.get('skipped_by_reason'):
        row['issues'].append('pieces_not_built:' + ','.join(f'{k}:{n}' for k, n in inv['skipped_by_reason'].items()))
    sr = s2.get('steel_ratio')
    row['weight_ratio'] = {'steel_ratio_vs_sds2': sr}
    lo1, hi1 = RULES['sds2_weight_band_class1']; lo3, hi3 = RULES['sds2_weight_band_class3']
    if sr is not None and not lo3 <= sr <= hi3:
        row['reasons'].append(f'steel_weight_ratio_{sr}')
    elif sr is not None and not lo1 <= sr <= hi1:
        row['issues'].append(f'steel_weight_ratio_{sr}_outside_5pct')
    elif sr is None and (rolled + conn):
        row['issues'].append('no_sds2_weights_for_check')
    row['issues_info'] = ['welds are not modelled (no readable weld geometry in SDS/2 files)']
    has_conn = conn + bolts > 0
    return finish_class(row, has_conn=has_conn, src_conn=None, steel=True)


# ------------------------------------------------------------------ versions, re-conversion, history
SDS2_VERS = {}


def version_key(r):
    p = r['pipeline']
    if p == 'ifc':
        k = (r.get('paths') or [''])[0].lower()
        kind = 'ifcZIP' if '.ifczip' in k else ('ifcXML' if '.ifcxml' in k else None)
        sch = (r.get('schema') or '').upper() or 'unknown'
        return f'{sch} ({kind})' if kind else sch
    if p == 'db1':
        return r.get('engine') or 'unknown'
    v = str(r.get('version') or SDS2_VERS.get(r['id']) or 'unknown')
    try:
        f = float(v)
        return f'{int(f)}.{int(round((f - int(f)) * 1000)) // 100}xx'
    except ValueError:
        return v


def versions_matrix(rows):
    out = {}
    for p in ('ifc', 'db1', 'sds2'):
        d = {}
        for r in rows:
            if r['pipeline'] != p:
                continue
            k = version_key(r)
            e = d.setdefault(k, {'distinct': 0, 'done': 0, 'class1': 0, 'class2': 0, 'class3': 0, '_reasons': collections.Counter()})
            e['distinct'] += 1
            if r['class'] in (1, 2, 3):
                e['done'] += 1; e[f'class{r["class"]}'] += 1
                for x in (r['reasons'] if r['class'] == 3 else r['issues'] + [s_['type'] for s_ in r['standins']]):
                    e['_reasons'][f"{r['class']}:{x.split(':')[0].split(' (')[0]}"] += 1
        for k, e in d.items():
            rr = e.pop('_reasons')
            e['top_reason'] = rr.most_common(1)[0][0] if rr else None
        out[p] = dict(sorted(d.items(), key=lambda kv: -kv[1]['distinct']))
    return out


def tags_of(r):
    import re as _r
    t = {x.split(':')[0].split(' (')[0] for x in r['reasons'] + r['issues']} | {s_['type'] for s_ in r['standins']} | \
        {n_.split(':')[0] for n_ in r['needs']} | set(r.get('tags_extra') or [])
    return {_r.sub(r'_-?[\d.]+(?=_|$)', '', x) for x in t}


def job_from_content(pipe, c):
    if pipe == 'ifc':
        k = (c.get('paths') or [''])[0]
        return {'id': c['id'], 'sha256': c['sha256'], 'size': c.get('size'), 'kind': c.get('kind') or ('ifczip' if '.ifczip' in k.lower() else 'ifc'),
                'input_key': c.get('input_key'), 'input_from': c.get('input_from'), 'n_paths': c.get('n_paths'), 'paths': c.get('paths'),
                'reconvert_of_reused': (c.get('reuse') or {}).get('step_key')}
    if pipe == 'db1':
        return {'id': c['id'], 'sha256': c['sha256'], 'size': c.get('size'), 'input_key': c.get('input_key'), 'input_from': c.get('input_from'),
                'n_paths': c.get('n_paths'), 'paths': c.get('paths'), 'siblings': (c.get('siblings') or [])[:100],
                'reconvert_of_reused': (c.get('reuse') or {}).get('step_key')}
    p0 = (c.get('paths') or [' :: job'])[0]
    root = p0.split(' :: ', 1)[-1].rstrip('/')
    return {'id': c['id'], 'fpc': c.get('fpc'), 'name': root.rsplit('/', 1)[-1] or 'job', 'model_bytes': c.get('model_bytes'), 'size': c.get('model_bytes'),
            'n_files': c.get('n_model_files'), 'files_key': c.get('files_key'), 'jsetup_sha256': c.get('jsetup_sha256'),
            'complete_layout': c.get('complete_layout', True), 'n_paths': c.get('n_paths'), 'paths': c.get('paths'),
            'reconvert_of_reused': (c.get('reuse') or {}).get('step_key')}


def code_key(c):
    m = re.match(r'z3-sds2-v([\d.]+)-(.*)$', c or '')
    return (tuple(int(x) for x in m.group(1).split('.') if x.isdigit()), m.group(2)) if m else None


def code_ge(a, b):
    """result converter code `a` satisfies a rule whose converter code is `b`: the same code (or a suffix variant), or for SDS2 a later
    converter version (a job re-run on v5.3 needs no v5.2 re-run)"""
    if not a or not b:
        return False
    if a == b or a.startswith(b):
        return True
    ka, kb = code_key(a), code_key(b)
    return bool(ka and kb and ka[0] >= kb[0])


def reconvert(rows, contents_by_pipe):
    """rules s3://annotationprod/.../coord/reconvert.json: {pipe: rule | [rule, ...]}, rule = {"code": <worker CODE that fixes it>,
    "match": [tags] | "*", "classes": [2, 3], "include_reused": true, "engines": [...], "versions": [...]}. Every rule carries its own
    code: a model is re-run when a rule hits it and its current result does not come from that code or a later version of it ->
    _state/conv/<pipe>/redo.json (ids of data-3 results to re-run) and jobs_reconvert.json (reused models converted fresh into data-3;
    they supersede the reused STEP only when better). One history entry per (pipeline, rule code)."""
    rules = getj(f'{CTL}/coord/reconvert.json', CB) or {}
    hist = getj(f'{ST}/history.json') or []
    out = {}
    for pipe, rule_ in rules.items():
        if pipe not in ('ifc', 'db1', 'sds2'):
            continue
        rl = [dict(x) for x in (rule_ if isinstance(rule_, list) else [rule_])]
        for r_ in rl:
            r_.setdefault('code', rl[0].get('code'))
        cmap = {c['id']: c for c in contents_by_pipe[pipe]}
        redo_ids, jobs = [], []
        targeted = collections.defaultdict(list)       # rule code -> ids

        def hits(r):
            hs = []
            for r_ in rl:
                if r['class'] not in set(r_.get('classes') or [2, 3]):
                    continue
                eng = set(r_.get('engines') or [])
                if eng and r.get('engine') not in eng and not (r.get('engine') is None and r_.get('include_unknown_engine')):
                    continue
                vs = r_.get('versions')
                if vs and not str(r.get('version') or SDS2_VERS.get(r['id']) or '').startswith(tuple(vs)):
                    continue
                m_ = r_.get('match', '*')
                if m_ != '*' and not (tags_of(r) & set(m_)):
                    continue
                hs.append(r_)
            return hs
        for r in rows:
            if r['pipeline'] != pipe:
                continue
            open_ = [r_ for r_ in hits(r) if not code_ge(r.get('converter_code'), r_['code'])]
            if not open_:
                continue
            for cd in {r_['code'] for r_ in open_}:
                targeted[cd].append(r['id'])
            if r['reused']:
                if any(r_.get('include_reused', True) for r_ in open_) and cmap.get(r['id']) and cmap[r['id']].get('input_key', True) is not None:
                    jobs.append(job_from_content(pipe, cmap[r['id']]))
            else:
                redo_ids.append(r['id'])
        # keep earlier targets in the list until their result comes from one of the current rule codes (the list must not shrink
        # mid-run because a class changed while the job was waiting)
        prev = getj(f'{ST}/{pipe}/redo.json') or []
        prevj = getj(f'{ST}/{pipe}/jobs_reconvert.json') or []
        byid = {r['id']: r for r in rows if r['pipeline'] == pipe}
        def rerun(i):
            cc = (byid.get(i) or {}).get('converter_code')
            return any(code_ge(cc, r_['code']) for r_ in rl)
        if (rules.get('_options') or {}).get(pipe, {}).get('keep_previous', True):
            redo_ids = sorted(set(redo_ids) | {i for i in prev if not rerun(i)})
            have = {j['id'] for j in jobs}
            jobs += [j for j in prevj if j['id'] not in have and not rerun(j['id'])]
        else:                                     # operator pause of some rules: the lists shrink to the current targets at once
            redo_ids = sorted(set(redo_ids))
        def missing_parts(r):
            ps, pt = r.get('parts_source') or 0, r.get('parts_step')
            miss = max(0, ps - pt) if (ps and pt is not None) else (round((1 - r['coverage_all']) * ps) if ps and r.get('coverage_all') is not None else 0)
            return miss + sum((x.get('count') or 0) for x in r['standins'] if isinstance(x.get('count'), (int, float)))
        pr = sorted(set(redo_ids) | {j['id'] for j in jobs}, key=lambda i: (0 if (byid.get(i) or {}).get('class') == 3 else 1,
                                                                            -missing_parts(byid.get(i) or {'standins': []})))
        s3.put_object(Bucket=B, Key=f'{ST}/{pipe}/priority.json', Body=json.dumps({i: n for n, i in enumerate(pr)}).encode(), ContentType='application/json')
        s3.put_object(Bucket=B, Key=f'{ST}/{pipe}/redo.json', Body=json.dumps(redo_ids).encode(), ContentType='application/json')
        s3.put_object(Bucket=B, Key=f'{ST}/{pipe}/jobs_reconvert.json', Body=json.dumps(jobs).encode(), ContentType='application/json')
        out[pipe] = {'codes': sorted({r_['code'] for r_ in rl}), 'redo': len(redo_ids), 'reconvert_reused': len(jobs),
                     'targeted_by_code': {k: len(v) for k, v in targeted.items()}}
        # history: before/after class counts of the models each converter version targets
        for code in sorted({r_['code'] for r_ in rl}):
            ent = next((h for h in hist if h['pipeline'] == pipe and h['converter'] == code), None)
            ids_now = sorted(set(targeted.get(code, [])))
            if ent is None and ids_now:
                ent = {'pipeline': pipe, 'converter': code, 'started': now(),
                       'match': [m for r_ in rl if r_['code'] == code for m in (r_.get('match') if isinstance(r_.get('match'), list) else ['*'])],
                       'targeted': len(ids_now), 'ids_key': f'{ST}/history/{pipe}_{code}.json',
                       'before': dict(collections.Counter(str(byid[i]['class']) for i in ids_now if i in byid))}
                s3.put_object(Bucket=B, Key=ent['ids_key'], Body=json.dumps(ids_now).encode(), ContentType='application/json')
                hist.append(ent)
            if ent is not None:
                ids = getj(ent['ids_key']) or []
                reached = [i for i in ids if code_ge(byid.get(i, {}).get('converter_code'), code)]
                ent['after'] = dict(collections.Counter(str(byid[i]['class']) for i in reached))
                ent['reconverted'] = len(reached); ent['done'] = len(reached) >= len(ids); ent['updated'] = now()
    s3.put_object(Bucket=B, Key=f'{ST}/history.json', Body=json.dumps(hist, indent=1).encode(), ContentType='application/json')
    return out, hist


def num(x):
    """manifest count of any shape across converter versions: number -> itself; dict -> its 'total' (or the sum of its numeric
    values); list -> its length; anything else -> 0"""
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, (int, float)):
        return x
    if isinstance(x, dict):
        t = x.get('total')
        if isinstance(t, (int, float)) and not isinstance(t, bool):
            return t
        return sum(v for v in x.values() if isinstance(v, (int, float)) and not isinstance(v, bool))
    if isinstance(x, (list, tuple)):
        return len(x)
    return 0


def classify_sds2_manifest(row, r, man, s2):
    """v5 sidecar: counts, stand-in groups with real types, skipped pieces, weight check total and by family, read-back"""
    cnt = man.get('counts') if isinstance(man.get('counts'), dict) else {}
    rb = man.get('readback') if isinstance(man.get('readback'), dict) else {}; v = r.get('validate') or {}
    cn = lambda k: num(cnt.get(k))
    row['graded_by'] = 'converter_verify + v5 manifest (OCP read-back, BRepCheck per placed instance)'
    sol = rb.get('solids', v.get('solids')); val = rb.get('valid', v.get('valid'))
    sol = None if sol is None else num(sol); val = None if val is None else num(val)
    row['solids'] = sol; row['invalid_solids'] = (sol - val) if sol is not None and val is not None else None
    if sol is None or val is None:
        row['reasons'].append('step_read_failed')
    elif sol == 0:
        row['reasons'].append('step_no_geometry')
    elif row['invalid_solids']:
        row['issues'].append(f'invalid_solids:{row["invalid_solids"]}')
    if num(rb.get('load_errors')):
        row['issues'].append(f'step_load_errors:{num(rb.get("load_errors"))}')
    ink = v.get('render_ink')
    if ink is not None and ink < RULES['render_blank_ink']:
        row['reasons'].append('blank_render')
    bb = v.get('bbox_mm') or (r.get('step') or {}).get('bbox_mm')
    if bbox_ok(bb) is False:
        row['reasons'].append('bbox_absurd')
    row['bbox_mm'] = bb
    m_ = cn('members')
    row['coverage_members'] = round((m_ - cn('members_without_geometry')) / m_, 4) if m_ else None
    placed = cn('placed_pieces')
    row['coverage_connections'] = round(cn('pieces_written') / placed, 4) if placed else None
    bolts = cn('bolts_sds2') + cn('bolts_nominal')
    row['parts_source'] = m_ and (placed + bolts + cn('member_envelopes') + cn('joist_standins')) or None
    row['parts_step'] = cn('solids_written') if cnt.get('solids_written') is not None else None
    row['coverage_all'] = row['coverage_connections']
    for g in [g for g in (man.get('standin_groups') or []) if isinstance(g, dict)]:
        row['standins'].append({'type': g.get('type'), 'real_type': g.get('real_type'), 'count': g.get('count'), 'why': (g.get('reason') or '')[:160]})
    hl = man.get('holes') if isinstance(man.get('holes'), dict) else {}
    hder = num((hl.get('derived') or {}).get('total') if isinstance(hl.get('derived'), dict) else hl.get('derived'))
    if hder and not any(s_.get('type') == 'holes_derived_from_bolts' for s_ in row['standins']):
        # v5.4: holes cut from an SDS2 bolt record + a coaxial decoded hole (not stored as holes; NC1 could not validate them)
        row['standins'].append({'type': 'holes_derived_from_bolts', 'real_type': 'bolt hole derived from an SDS2 bolt record and a coaxial decoded hole (not a stored hole)', 'count': hder})
    ros = cn('reference_open_shells')
    if ros and not any('open' in str(s_.get('type')) for s_ in row['standins']):
        row['standins'].append({'type': 'reference_open_surface', 'real_type': 'imported reference geometry stored as open DWF meshes (not solids)', 'count': ros})
    sbr = {k: v for k, v in (man.get('skipped_by_reason') if isinstance(man.get('skipped_by_reason'), dict) else {}).items() if k not in ('total', 'by_reason', 'parts') and isinstance(v, int)}
    sd_ = man.get('skipped_detail') if isinstance(man.get('skipped_detail'), dict) else {}
    sk_by = sd_.get('by_reason') if isinstance(sd_.get('by_reason'), dict) else sbr
    sk_by = {k: num(v) for k, v in sk_by.items()}
    skipped = cn('skipped') if cnt.get('skipped') is not None else sum(sk_by.values())
    if skipped:
        row['issues'].append(f'pieces_not_built:{skipped} (' + ','.join(f'{k}:{n}' for k, n in list(sk_by.items())[:6]) + ')')
    w = man.get('weight') if isinstance(man.get('weight'), dict) else {}
    sr = w.get('ratio_without_outliers') or w.get('ratio')
    if w.get('dominant_outliers'):
        row['issues_info'] = (row.get('issues_info') or []) + ['dominant weight outliers in the SDS/2 piece table (excluded from the ratio)']
    row['weight_ratio'] = {'steel_ratio_vs_sds2': sr, 'by_family': w.get('by_family')}
    lo3, hi3 = RULES['sds2_weight_band_class3']; lo1, hi1 = RULES['sds2_weight_band_class1']
    if sr is not None and not lo3 <= sr <= hi3:
        row['reasons'].append(f'steel_weight_ratio_{sr}')
    elif sr is not None and not lo1 <= sr <= hi1:
        row['issues'].append(f'steel_weight_ratio_{sr}_outside_5pct')
    tol = RULES['sds2_family_weight_tolerance']; nmin = RULES['sds2_family_min_pieces']
    off = [f for f, x in (w.get('by_family') if isinstance(w.get('by_family'), dict) else {}).items() if isinstance(x, dict) and x.get('ratio') is not None and (x.get('n') or 0) >= nmin and abs(x['ratio'] - 1) > tol]
    if off:
        row['issues'].append('family_weight_outside_5pct:' + ','.join(off[:6]))
    row['manifest_class'] = {'class': man.get('class'), 'corpus': man.get('corpus'), 'reasons': man.get('class_reasons')}
    cdup = max(num(man.get('converter_duplicates')), cn('converter_duplicates_skipped'))
    row['converter_duplicates'] = cdup
    if cdup > 0:
        row['tags_extra'] = (row.get('tags_extra') or []) + ['converter_duplicates']
    row['issues_info'] = ['welds are not modelled (no readable weld geometry in SDS/2 files)']
    pk = (r.get('inventory') or {}).get('pieces_by_kind') or {}
    has_conn = (pk.get('plate', 0) + pk.get('fastener', 0) + bolts) > 0 if pk else bolts > 0
    for g in [g for g in (man.get('standin_groups') or []) if isinstance(g, dict)]:
        if g.get('needed'):
            row.setdefault('group_needs', []).append({'type': g.get('type'), 'needed': str(g['needed'])[:200], 'count': g.get('count')})
    finish_class(row, has_conn=has_conn, src_conn=None, steel=True)
    refp = cn('reference_parts')
    if row['class'] in (1, 2) and (man.get('corpus') == 'R' or (refp and refp >= 0.5 * max(1, cn('solids_written')))):
        row['corpus'] = 'R'; row['reference_parts'] = refp
        row['issues_info'] = (row.get('issues_info') or []) + ['reference / imported model geometry (not SDS/2-modelled steel)']
    return row


# ------------------------------------------------------------------ plain-language missing / needed_to_fix
CF, SFM, SDA, PCM, SDM = 'converter_feature', 'source_file_missing', 'source_data_absent', 'profile_or_catalog_missing', 'source_damaged'


def _n(x):
    try:
        return int(str(x).split(':', 1)[1].split('/')[0].split(',')[0])
    except Exception:
        return None


def explain(r):
    """-> (missing [{what, count, category}], needed_to_fix [{fix, category, key}]) from the row's signals"""
    miss, need = [], []
    p = r['pipeline']; eng = r.get('engine'); ver = r.get('version')

    def add(what, count, fix, cat, key):
        miss.append({'what': what, 'count': count, 'category': cat})
        need.append({'fix': fix, 'category': cat, 'key': f'{cat} | {key}'})
    for x in r['reasons']:
        t = x.split(' (')[0].split(':')[0]
        if t.startswith('source_geometry_free'):
            add('no 3D element geometry in the source (grids / annotations / blank model)', None, 'a model export or model file with element geometry', SDA, 'source has no element geometry')
        elif t in ('source_not_ifc', 'source_not_tekla_db1'):
            add('file is not a model of this type (wrong content behind the extension)', None, 'the real model file', SFM, 'wrong file content')
        elif t == 'source_cis2_not_ifc':
            add('file is a CIS/2 model, not IFC', None, 'a CIS/2 -> STEP converter', CF, 'CIS/2 reader')
        elif t in ('source_empty_or_stub', 'source_corrupt_all_zero', 'source_truncated', 'source_corrupt_zip', 'source_encrypted', 'source_parse_error',
                   'source_empty_file', 'source_corrupt_or_decoder_error', 'source_empty_zip'):
            add(f'source file damaged ({t.replace("source_", "").replace("_", " ")})', None, 'an intact copy of the source file', SDM, 'damaged source file')
        elif t == 'ifcxml_reader_unavailable':
            add('ifcXML file: no reader in the IFC toolchain', None, 'an ifcXML reader in the IFC converter', CF, 'ifcXML reader')
        elif t in ('source_copy_not_found',):
            add('no stored copy of the source content was found', None, 'the source file from the drive', SFM, 'source copy')
        elif t.startswith('decoder_limit'):
            add(f'Tekla {eng or ""} record layout not decoded' if p == 'db1' else 'source format variant not decoded', None,
                f'decoder support for Tekla {eng} ({x.split(": ", 1)[-1]})' if p == 'db1' else f'decoder support for SDS/2 {ver} ({x.split(": ", 1)[-1]})', CF,
                f'decoder layout Tekla {eng}' if p == 'db1' else f'decoder layout SDS/2 {ver}')
        elif t.startswith('decoder_guard'):
            add('decoded model held back by a geometry sanity guard', None, f'decoder fix for Tekla {eng} attribute/orientation links', CF, f'decoder guard Tekla {eng}')
        elif t.startswith('source_no_members'):
            add('SDS/2 job has no members (seed / training / empty job)', None, 'a job with modelled members (nothing to convert here)', SDA, 'empty SDS/2 job')
        elif t.startswith(('no_member_records_read', 'converter_wrote_nothing')):
            add('SDS/2 job: converter read no buildable member (imported reference model or empty job, not yet told apart)', None,
                'v5.1 re-run: reference-model pieces from the stored B-rep (corpus R) or empty_job_proof', CF, 'sds2 reference model / empty proof')
        elif t.startswith('source_no_buildable_pieces'):
            add('SDS/2 job holds no buildable steel (e.g. only DWF-imported objects)', None, 'nothing to convert: the job has no steel members', SDA, 'job without steel')
        elif t.startswith('source_job_files_missing'):
            add('SDS/2 job files missing (main/job_mtrl or mem/mem_idx)', None, 'those files from the original job folder', SFM, 'SDS/2 job files')
        elif t.startswith('bbox_absurd'):
            add('coordinates absurd (corrupt numbers in the source)', None, 'an intact source / corrected coordinates', SDM, 'corrupt coordinates')
        elif t.startswith(('member_coverage', 'part_coverage')):
            add(f'only {x.rsplit("_", 1)[-1]} of the members converted', None, 'converter support for the missing members (see missing examples)', CF, f'{p} members not converted')
        elif t.startswith('steel_weight_ratio'):
            add(f'steel weight {x.rsplit("_", 1)[-1]} x the source weights', None, 'converter fix for the pieces that change the weight', CF, 'sds2 weight mismatch')
        elif t in ('blank_render',):
            add('STEP renders blank', None, 'converter fix (geometry not drawable)', CF, 'blank render')
        else:
            add(t.replace('_', ' '), None, 'converter fix', CF, t)
    for x in r['issues']:
        t = x.split(':')[0].split(' (')[0]; n = _n(x)
        if t == 'invalid_solids':
            add(f'{n} solids fail the BRep validity check', n, 'solid healing / exact rebuild in the converter', CF, f'{p} invalid solids')
        elif t == 'non_positive_volume_solids':
            add(f'{n} solids inside-out or not closed (non-positive volume)', n, 'shell orientation / closing in the converter', CF, f'{p} shell orientation')
        elif t == 'parts_outside_volume_tolerance':
            add(f'{x.split(":")[1]} parts differ > 5% from the source volume', n, 'exact geometry for those parts (tessellation / boolean accuracy)', CF, f'{p} volume tolerance')
        elif t == 'parts_without_solid':
            add(f'{n} parts read back as surfaces, not solids', n, 'IFC writer: IfcShellBasedSurfaceModel of IfcClosedShell as CLOSED_SHELL / '
                'FACETED_BREP, close or heal open faceted shells (re-convert reused STEP)', CF, f'{p} parts without solid')
        elif t == 'coverage_by_part_count_only':
            add('coverage proven only by part count (older STEP without source ids or usable names)', None,
                're-convert with the current writer (PRODUCT.id = source GlobalId)', CF, f'{p} re-convert old writer')
        elif t == 'not_read_back_out_of_memory':
            add('STEP not verified (read-back ran out of memory on a shared box)', None, 'read-back on a dedicated large-memory box (final pass)', CF, 'read-back memory')
        elif t == 'not_read_back_large_file':
            add('STEP > 1 GB not verified by OCC read-back', None, 'large-file verification (streamed read-back)', CF, 'large-file read-back')
        elif t == 'per_part_verification_pending':
            add('per-part check pending: STEP too large or read-back memory-killed (coverage from part counts)', None,
                'per-part read-back / streamed verification (final pass)', CF, f'{p} per-part verification')
        elif t == 'source_inventory_unavailable':
            add('source inventory could not be computed (coverage unknown)', None, 'source inventory support for this file', CF, f'{p} source inventory')
        elif t == 'kernel_crash_elements_excluded':
            add(f'{n} elements left out (geometry kernel crash)', n, 'kernel-crash fix for those elements', CF, f'{p} kernel crash elements')
        elif t == 'source_truncated_tail_dropped':
            add('source file truncated: its unfinished tail was dropped', None, 'an intact copy of the source file', SDM, 'truncated source')
        elif t.startswith('bbox_extent'):
            add(f'model spans {x.split("_")[-1]} (stray or mis-placed parts)', None, 'check / remove stray parts in the source model', SDM, 'stray parts')
        elif t == 'parts_dropped_by_axis_guard':
            add(f'{n} parts dropped by the orientation guard', n, f'decoder fix for Tekla {eng} part orientation', CF, f'axis guard Tekla {eng}')
        elif t == 'cuts_not_applied':
            add(f'{n} cuts not applied', n, 'cut decoding fix', CF, 'db1 cuts')
        elif t == 'pieces_not_built':
            # sds2 v5.5 manifests name source gaps 'source_*' (no piece file / no faces / zero size / open double-sided
            # mesh): the job lacks that geometry, so it is source data absent, not a converter feature
            rs_ = [(k_, int(n_)) for k_, n_ in re.findall(r'([a-z][a-z_0-9]+):(\d+)', x.split(':', 1)[1])]
            src_ = [(k_, n_) for k_, n_ in rs_ if k_.startswith('source_')]
            if src_:
                ns_ = sum(n_ for _, n_ in src_)
                add(f'{ns_} pieces with no buildable geometry in the source (' + ','.join(f'{k_}:{n_}' for k_, n_ in src_) + ')', ns_,
                    'piece geometry in the source job (SDS/2 holds no faces, a zero size or an open mesh for them)', SDA, f'{p} piece geometry absent')
            if not src_ or len(src_) < len(rs_):
                add('pieces not built: ' + x.split(':', 1)[1][:120], None, 'converter support for those pieces', CF, f'{p} pieces not built')
        elif t == 'family_weight_outside_5pct':
            add('section families off the SDS/2 weight by > 5%: ' + x.split(':', 1)[1], None, 'exact geometry for those families', CF, 'sds2 family weight')
        elif t.startswith('steel_weight_ratio'):
            add(f'steel weight {x.split("_")[3]} x SDS/2 (outside 5%)', None, 'exact geometry for the off-weight pieces', CF, 'sds2 weight 5%')
        elif t == 'members_only_stage1_fallback':
            add('only members written (stage 2 failed: ' + x.split('stage 2: ', 1)[-1].rstrip(')') + ')', None, 'stage-2 converter fix for this job', CF, 'sds2 stage 2 failure')
        elif t in ('roots_not_transferred', 'parts_with_nonfinite_coords', 'step_load_errors'):
            add(f'{n} parts not readable from the STEP', n, 'STEP writer fix', CF, f'{p} unreadable parts')
        elif t in ('piece_inventory_unavailable', 'step_vs_decoder_join_unavailable', 'no_sds2_weights_for_check') or t.startswith('inventory from') or t.startswith('grading'):
            add(t.replace('_', ' '), None, 'grading data for this model', CF, 'grading data')
        else:
            add(t.replace('_', ' '), n, 'converter fix', CF, t)
    for st_ in r['standins']:
        t = st_['type']; n = st_.get('count'); rt = st_.get('real_type') or ''
        if st_.get('tolerated'):
            continue
        if t in ('joist_as_envelope_box', 'joist_envelope_box'):
            add(f'{n} joists written as envelope boxes ({rt})', n, "the joist manufacturer's detail model / drawings", SDA, 'joist vendor design')
        elif t == 'joist_openweb_standin':
            add(f'{n} open-web joists rebuilt from their designation ({rt})', n, "the joist manufacturer's detail model / drawings", SDA, 'joist vendor design')
        elif t in ('member_as_envelope', 'member_envelope'):
            add(f'{n} members without piece data written as envelopes', n, 'members detailed in the source job', SDA, 'undetailed members')
        elif t in ('nominal_bolt_from_hole_stack', 'nominal_bolt'):
            add(f'{n} bolts guessed from hole stacks (no bolt record)', n, 'bolt records in the source job', SDA, 'bolt records absent')
        elif t in ('rolled_profile_extrusion', 'plate_from_vertices', 'plate_fallback_approximate_no_holes', 'profile_fallback_approximate_no_holes', 'piece_table_standin'):
            add(f'{n} pieces approximated ({t.replace("_", " ")}: {rt})', n, f'exact piece geometry decoding for SDS/2 {ver}', CF, f'sds2 approx pieces {str(ver)[:3]}')
        elif t in ('grating_solid_panel', 'grating_as_solid_panel', 'grating_as_solid_plate'):
            add(f'{n} bar gratings written as solid panels', n, 'bar-grating geometry generation in the converter', CF, f'{p} grating geometry')
        elif t == 'holes_not_cut':
            add(f'{n} pieces without their holes', n, 'hole cutting for those pieces', CF, f'{p} holes')
        elif t in ('reference_open_surface', 'open_surface') or 'open_surface' in t or 'open-surface' in t:
            add(f'{n} reference parts written as open surfaces ({rt})', n, 'closed solid geometry for the imported reference model (the job stores open meshes)', SDA, 'reference open meshes')
        elif t in ('concrete_prism', 'concrete_as_prism'):
            add(f'{n} concrete parts as L x W x T prisms', n, 'concrete shapes are not in the job data', SDA, 'concrete shapes')
        elif t == 'pieces_without_bolt_holes':
            continue                                           # covered by the bolt-group need
        elif t.startswith('section_'):
            add(f'{n} parts with derived section dimensions ({rt})', n, 'exact section dimensions (catalog entry with all dimensions)', PCM, f'derived sections: {t[8:]}')
        elif t == 'bolt_nominal_head_nut':
            add(f'{n} bolts with nominal head/nut geometry', n, 'the bolt assembly catalog (exact head / nut / washer dimensions)', PCM, 'bolt catalog')
        elif t == 'hole_clearance_nominal':
            add(f'{n} holes with nominal clearance diameter', n, 'decode the bolt group hole tolerance', CF, f'hole tolerance Tekla {eng}')
        elif t == 'washer_nominal':
            add(f'{n} washers with nominal thickness', n, 'the washer catalog entry (exact thickness) for this bolt standard', PCM, 'washer catalog')
        elif t == 'washer_side_inferred':
            add(f'{n} bolts whose washer side is inferred from the assembly flags', n, 'decode the per-side washer flags', CF, f'washer side Tekla {eng}')
        elif t.startswith('v6_'):
            add(f'{n} parts: {rt}', n, 'exact solid repair / reconstruction in the IFC converter', CF, f'{p} {t}')
        elif t == 'bolt_axial_position_fitted':
            add(f'{n} bolts positioned along their axis by fitting to the plies', n, 'decode the bolt group offset / head side', CF, f'bolt offsets Tekla {eng}')
        elif t == 'bolt_solid_no_hole':
            add(f'{n} bolts without holes in the connected parts', n, 'hole cutting (Windows pipeline output)', CF, 'db1 holes (windows outputs)')
        elif t == 'stud_as_plain_cylinder':
            add(f'{n} shear studs as plain cylinders', n, 'headed-stud geometry', CF, 'db1 studs')
        elif t == 'bounding_box':
            add(f'{n} {rt} exported as bounding boxes by the authoring tool', n, 'the detailed model (source exported boxes)', SDA, 'boxes in source export')
        else:
            add(f'{n} {t.replace("_", " ")} ({rt})', n, 'exact geometry in the converter', CF, f'{p} {t}')
    for x in r['needs']:
        if x.startswith('bolt decoding'):
            add(f'{_n(x.replace("bolt decoding: ", "x:")) or ""} Tekla bolt groups not written; bolt holes not cut', None,
                f'decoder support for Tekla {eng} bolt groups', CF, f'bolt groups Tekla {eng}')
        elif x.startswith('records without profile'):
            add(x.split(': ', 1)[1], _n(x), f'decoder support for Tekla {eng} bolt groups (member records without a profile name)', CF, f'bolt groups Tekla {eng}')
        elif x.startswith('profile catalog entries'):
            add(x.replace('profile catalog entries: ', 'profiles missing from the catalog: '), None, 'the profile definitions (catalog entries)', PCM, 'profile catalog')
        elif x.startswith('profile sizes missing'):
            add(x, None, 'profile sizes (the model names them without dimensions)', SDA, 'profiles without size')
        elif x.startswith('reverse-engineered record layout'):
            continue
        elif 'job folder' in x:
            add('SDS/2 job folder incomplete', None, x, SFM, 'SDS/2 job files')
        elif 'ifcXML' in x:
            continue
        elif x.startswith('a stored copy'):
            continue
        else:
            add(x, None, x, CF, x[:60])
    if r['class'] == 2 and not need:
        cov = [k for k in ('coverage_members', 'coverage_connections', 'coverage_other') if r.get(k) is not None and r[k] < 1]
        if cov:
            add('some source parts not in the STEP (' + ', '.join(f'{k.split("_")[1]} {r[k]:.0%}' for k in cov) + ')', None,
                'converter support for the missing parts', CF, f'{p} missing parts')
    # dedupe needs by key
    seen = set(); need2 = []
    for nd in need:
        if nd['key'] not in seen:
            seen.add(nd['key']); need2.append(nd)
    return miss, need2


def fix_plan(rows):
    plan = {}
    for r in rows:
        if r['class'] not in (2, 3):
            continue
        keys = [n['key'] for n in r.get('needed_to_fix') or []]
        for nd in r.get('needed_to_fix') or []:
            e = plan.setdefault(nd['key'], {'fix': nd['fix'], 'category': nd['category'], 'models': 0, 'lift_to_class1_if_only_fix': 0,
                                            'by_pipeline': collections.Counter(), 'by_class': collections.Counter()})
            e['models'] += 1; e['by_pipeline'][r['pipeline']] += 1; e['by_class'][str(r['class'])] += 1
            if len(set(keys)) == 1 and r['class'] == 2:
                e['lift_to_class1_if_only_fix'] += 1
    out = sorted(({'key': k, **{kk: (dict(vv) if isinstance(vv, collections.Counter) else vv) for kk, vv in v.items()}} for k, v in plan.items()),
                 key=lambda e: (-e['lift_to_class1_if_only_fix'], -e['models']))
    return out


def rejoin_grades(grades):
    """reused IFC / DB1 grades: recompute the source-vs-STEP join with the current grade_join from the stored detail files (no re-run);
    cached per (grade result, grade_join version)"""
    d = os.path.join(W, 'rejoin'); os.makedirs(d, exist_ok=True)
    todo = []
    for gid, r in grades.items():
        if r.get('pipeline') not in ('ifc', 'db1') or r.get('status') != 'ok':
            continue
        if (r.get('join') or {}).get('mode') == 'gid':
            continue
        fin = r.get('finished') or ''
        cp = os.path.join(d, f'{gid}.{GJV}.json')
        if os.path.exists(cp):
            try:
                c = json.load(open(cp))
                if c.get('finished') == fin:
                    r['join'] = c['join']; r['rejoined'] = GJV
                    continue
            except Exception:
                pass
        todo.append((gid, r, cp, fin))

    def one(t):
        gid, r, cp, fin = t
        try:
            src = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{ST}/grade/detail/{gid}.src_parts.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]
            stp = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{ST}/grade/detail/{gid}.step_parts.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]
        except Exception:
            return gid, None, cp, fin
        return gid, grade_join.join(src, stp), cp, fin
    with ThreadPoolExecutor(32) as ex:
        for gid, j, cp, fin in ex.map(one, todo):
            if j is None:
                continue
            json.dump({'finished': fin, 'join': j}, open(cp, 'w'))
            grades[gid]['join'] = j; grades[gid]['rejoined'] = GJV
    return len(todo)


def detail_keys(row):
    pipe, i = row['pipeline'], row['id']
    if row.get('detail_prefix'):
        return row['detail_prefix'] + '.src_parts.jsonl.gz', row['detail_prefix'] + '.step_parts.jsonl.gz'
    if row.get('reused'):
        return f'{ST}/grade/detail/{pipe}-{i}.src_parts.jsonl.gz', f'{ST}/grade/detail/{pipe}-{i}.step_parts.jsonl.gz'
    return f'{ST}/{pipe}/detail/{i}.src_parts.jsonl.gz', f'{ST}/{pipe}/detail/{i}.step_parts.jsonl.gz'


def final_jobs(rows, cmaps):
    """final pass job list: IFC census v2 refresh where v1 inventories can cause volume outliers; OCC read-back + render where a STEP was
    never verified (memory kill, > 1 GB) or has no render"""
    jobs = []
    for r in rows:
        if r['pipeline'] not in ('ifc', 'db1') or not r.get('step_key') or r['class'] not in (1, 2):
            continue
        src_k, stp_k = detail_keys(r)
        tags = tags_of(r)
        c = cmaps[r['pipeline']].get(r['id']) or {}
        if r['pipeline'] == 'ifc' and ('parts_outside_volume_tolerance' in tags) and c.get('input_key'):
            jobs.append({'id': f'f-ifc-{r["id"][:40]}-census', 'final': True, 'kind': 'census', 'pipeline': 'ifc', 'model_id': r['id'],
                         'sha256': r.get('sha256'), 'input_key': c['input_key'], 'size': c.get('size'), 'step_parts_key': stp_k, 'step_key': r['step_key']})
        if tags & {'not_read_back_out_of_memory', 'not_read_back_large_file'} or (not r.get('render_key')):
            jobs.append({'id': f'f-{r["pipeline"]}-{r["id"][:40]}-readback', 'final': True, 'kind': 'readback', 'pipeline': r['pipeline'],
                         'model_id': r['id'], 'step_key': r['step_key'], 'step_bytes': r.get('step_bytes') or 0, 'src_parts_key': src_k})
    jobs.sort(key=lambda j: -(j.get('step_bytes') or j.get('size') or 0))
    return jobs


def apply_final(pipe, mid, r, finals):
    """overlay final-pass signals (census v2 join, read-back, render) on a result / grade record"""
    if r is None:
        return r
    out = r
    for kind in ('census', 'readback'):
        fr = finals.get(f'f-{pipe}-{mid[:40]}-{kind}')
        if not fr or fr.get('status') != 'ok':
            continue
        out = dict(out)
        if fr.get('join'):
            out['join'] = fr['join']
        if kind == 'census' and fr.get('census'):
            out['census'] = fr['census']
        if kind == 'readback' and fr.get('validate'):
            out['validate'] = fr['validate']
            if fr.get('render_key'):
                out['render_key'] = fr['render_key']
        out['final_pass'] = sorted(set((out.get('final_pass') or []) + [kind]))
    return out


# ------------------------------------------------------------------ progress
def progress(pipe):
    out = {}
    try:
        jobs = getj(f'{ST}/{pipe}/jobs.json') or []
    except Exception:
        jobs = []
    out['jobs'] = len(jobs)
    ids = {j['id'] for j in jobs}
    res = [o for o in lst(f'{ST}/{pipe}/results/') if o['Key'].endswith('.json')]
    done = sum(1 for o in res if o['Key'].rsplit('/', 1)[-1][:-5] in ids)
    t = time.time()
    claims = [o for o in lst(f'{ST}/{pipe}/claims/') if t - o['LastModified'].timestamp() < 1500]
    hosts = [o for o in lst(f'{ST}/{pipe}/hosts/') if t - o['LastModified'].timestamp() < 300]
    out.update(done=done, in_flight=len(claims), pending=max(0, len(jobs) - done), worker_processes_live=len(hosts),
               pct_done=round(100.0 * done / len(jobs), 2) if jobs else 0.0)
    return out


MEM_EDGES_MB = {'sds2': [0, 50, 100, 250, 800, 3000], 'default': [0, 1, 5, 20, 50, 100, 200, 500]}
MEM_BUCKET_FLOOR_GB = {'sds2': {0: 4, 50: 8, 100: 16, 250: 22, 800: 24, 3000: 40}}     # lead's minimum reservation per SDS2 bucket
MEM_FLOOR_GB = {'ifc': 2, 'db1': 3, 'sds2': 3, 'grade': 4}


def job_sizes(pipe):
    """id -> (size, model_bytes, kind) from the pipeline's job lists (cached by ETag)"""
    out = {}
    for key in (f'{ST}/{pipe}/jobs.json', f'{ST}/{pipe}/jobs_reconvert.json'):
        try:
            et = s3.head_object(Bucket=B, Key=key)['ETag']
        except ClientError:
            continue
        c = CACHE.get('sizes:' + key)
        if not c or c[0] != et:
            v = getj(key) or []
            v = v.get('jobs', []) if isinstance(v, dict) else v
            c = (et, {j['id']: (j.get('size'), j.get('model_bytes'), j.get('kind')) for j in v if isinstance(j, dict) and j.get('id')})
            CACHE['sizes:' + key] = c
        out.update(c[1])
    return out


def mem_tables(res, grades, hostpipe):
    """memory reservation per input-size bucket from measured peak RSS: done jobs (result peak_rss_gb), memory-killed jobs (peak at
    the kill, a lower bound) and running jobs (peak so far, a lower bound) -> reserve = 1.2 x p95 (monotone over size; 1.2 x max when
    a bucket has < 10 samples, never below the kit estimate then) -> _state/conv/<pipe>/mem_buckets.json, read by every worker; plus
    each job's own highest measured peak (peak_by_id: a re-run reserves >= 1.2x it)"""
    out = {}
    for pipe in ('ifc', 'db1', 'sds2', 'grade'):
        rs = grades if pipe == 'grade' else (res.get(pipe) or {})
        sizes = job_sizes(pipe)
        def eff(i, r=None):
            sz, mb, kind = sizes.get(i) or (None, None, None)
            if r:
                sz = r.get('size') or sz; mb = r.get('model_bytes') or mb; kind = r.get('kind') or kind
            if pipe == 'sds2':
                return mb or sz or 0
            return (sz or 0) * (6 if kind == 'ifczip' else 1)
        edges = [e << 20 for e in MEM_EDGES_MB.get(pipe, MEM_EDGES_MB['default'])] + [1 << 62]
        def bucket(n):
            for i in range(len(edges) - 1):
                if edges[i] <= n < edges[i + 1]:
                    return i
            return len(edges) - 2
        done = collections.defaultdict(list); low = collections.defaultdict(list); pk_id = {}
        for i, r in rs.items():
            g = r.get('peak_rss_gb')
            if g:
                done[bucket(eff(i, r))].append(float(g)); pk_id[i] = max(pk_id.get(i, 0), float(g))
        try:
            dfr = load_results(f'{ST}/{pipe}/deferred/')
        except Exception:
            dfr = {}
        for i, d in dfr.items():
            # only records of the v2 runtime carry the measured peak (1-s samples); legacy records hold compounded reservations
            # (1.3 x previous, up to 966 GB) that are not measurements -> ignored
            g = d.get('peak_rss_gb') if d.get('runtime') == 'z3-convfleet-v2' else None
            if g:
                low[bucket(eff(i, d))].append(float(g)); pk_id[i] = max(pk_id.get(i, 0), float(g))
        for host, pp in hostpipe.items():
            for h in pp.get(pipe) or []:
                for r in h.get('running') or []:
                    if r.get('peak_rss'):
                        g = r['peak_rss'] / 2 ** 30
                        low[bucket(eff(r.get('id'), {'size': r.get('size')}))].append(g); pk_id[r.get('id')] = max(pk_id.get(r.get('id'), 0), g)
        bks = []; prev = 0.0
        for b in range(len(edges) - 1):
            u = sorted(done[b] + low[b])
            if not u:
                continue
            p95 = u[int(0.95 * (len(u) - 1))]
            rv = max(float(MEM_FLOOR_GB.get(pipe, 2)), float((MEM_BUCKET_FLOOR_GB.get(pipe) or {}).get(edges[b] >> 20, 0)), 1.2 * p95, prev)
            few = len(u) < 10
            if few:
                rv = max(rv, 1.2 * u[-1])
            prev = rv
            p50 = u[int(0.5 * (len(u) - 1))]
            dn = sorted(done[b]); p50d = dn[int(0.5 * (len(dn) - 1))] if len(dn) >= 5 else 0.0
            # expected (admission): running jobs' peaks so far are not peaks yet (young jobs pull the median down) and done jobs of
            # big models are mostly fast failures -> the largest of the done median, the all-samples median and 1/4 of the reservation
            bks.append({'lo': edges[b], 'hi': edges[b + 1], 'lo_mb': edges[b] >> 20, 'hi_mb': (edges[b + 1] >> 20) if b + 2 < len(edges) else None,
                        'n_done': len(done[b]), 'n_lower_bound': len(low[b]), 'p50_gb': round(p50, 2), 'p95_gb': round(p95, 2), 'max_gb': round(u[-1], 2),
                        'reserve_gb': round(rv, 1), 'reserve_bytes': int(rv * (1 << 30)), 'replace': not few,
                        'p50_done_gb': round(p50d, 2),
                        'expected_gb': round(max(p50, p50d, 0.25 * rv, 0.5), 2), 'expected_bytes': int(max(p50, p50d, 0.25 * rv, 0.5) * (1 << 30))})
        doc = {'pipeline': pipe, 'updated': now(), 'rule': 'reserve = 1.2 x p95 peak RSS of the size bucket (done + killed + running peaks): the '
               'memory watchdog kills jobs above it first; expected = median of the same samples: admission counts every running job at '
               'max(RSS, expected)',
               'size_field': 'model_bytes' if pipe == 'sds2' else 'size', 'kind_factor': {'ifczip': 6} if pipe == 'ifc' else {},
               'buckets': bks, 'peak_by_id': {k: round(v, 2) for k, v in pk_id.items() if k}}
        s3.put_object(Bucket=B, Key=f'{ST}/{pipe}/mem_buckets.json', Body=json.dumps(doc).encode(), ContentType='application/json')
        out[pipe] = [{k: x[k] for k in ('lo_mb', 'hi_mb', 'n_done', 'n_lower_bound', 'p50_gb', 'p95_gb', 'max_gb', 'expected_gb', 'reserve_gb')} for x in bks]
    return out


def once(final=False):
    global RULES
    RULES = dict(DEFAULT_RULES); RULES.update(getj(f'{CTL}/coord/rules.json', CB) or {})
    res = {p: load_results(f'{ST}/{p}/results/') for p in ('ifc', 'db1', 'sds2')}
    grades = load_results(f'{ST}/grade/results/')
    try:
        n_rejoin = rejoin_grades(grades)
    except Exception as e:
        n_rejoin = f'error {type(e).__name__}: {str(e)[:120]}'
    rows = []
    def score(r):
        return ((r['class'] or 9), len(r['issues']) + len(r['standins']) + len(r['needs']))
    finals = load_results(f'{ST}/final/results/')
    for pipe, fn in (('ifc', classify_ifc), ('db1', classify_db1), ('sds2', classify_sds2)):
        for c in contents(pipe):
          try:
            g = apply_final(pipe, c['id'], grades.get(f'{pipe}-{c["id"]}'), finals)
            res_ = apply_final(pipe, c['id'], res[pipe].get(c['id']), finals)
            if c['action'] == 'reuse' and res_ is not None:
                # a fresh data-3 conversion of reused content (improved converter): keep the better of the two
                rr = fn(c, None, g)
                rn = fn(dict(c, action='convert'), res_, None)
                if rr is None or rn is None:
                    r = rr or rn
                elif rn['class'] is not None and (rr['class'] is None or score(rn) <= score(rr)):
                    rn['supersedes'] = {'from': rr.get('reuse_from'), 'step_key': rr.get('step_key'), 'class': rr['class']}
                    r = rn
                else:
                    rr['alternative'] = {'converter_code': rn.get('converter_code'), 'class': rn['class'], 'step_key': rn.get('step_key')}
                    r = rr
            else:
                r = fn(c, res_, g)
          except Exception as e:
            # one unreadable / unexpected result must not stop the round: that model is listed as a grading error (no class)
            r = base_row(c, pipe)
            r.update(status='grading_error', **{'class': None})
            r['issues'].append(f'grading_error:{type(e).__name__}: {str(e)[:160]}')
            GRADING_ERRORS.append([pipe, c['id'], f'{type(e).__name__}: {str(e)[:200]}', traceback.format_exc()[-600:]])
          if r is not None:
              rows.append(r)
    try:
        recon, hist = reconvert(rows, {p: contents(p) for p in ('ifc', 'db1', 'sds2')})
    except Exception as e:
        recon, hist = {'error': f'{type(e).__name__}: {str(e)[:200]}'}, getj(f'{ST}/history.json') or []
    try:
        SDS2_VERS.update(getj(f'{ST}/scan/sds2_versions.json') or {})
    except Exception:
        pass
    vmat = versions_matrix(rows)
    drained = None
    try:
        if RULES.get('auto_final') and isinstance(recon, dict) and 'error' not in recon:
            pend = {p: progress(p) for p in ('ifc', 'db1', 'sds2', 'grade')}
            open_t = {p: sum((recon.get(p) or {}).get('targeted_by_code', {}).values()) for p in ('ifc', 'db1', 'sds2')}
            drained = all((pend[p].get('pending') or 0) == 0 and (pend[p].get('in_flight') or 0) == 0 for p in pend) and not any(open_t.values())
            summ_auto = {'checked': now(), 'drained': drained, 'pending': {p: pend[p].get('pending') for p in pend},
                         'in_flight': {p: pend[p].get('in_flight') for p in pend}, 'open_rerun_targets': open_t}
            s3.put_object(Bucket=B, Key=f'{ST}/final/auto_status.json', Body=json.dumps(summ_auto).encode(), ContentType='application/json')
    except Exception as e:
        print('auto final check error', e, flush=True)
    if getj(f'{CTL}/coord/final_prep', CB) is not None or final or drained or getj(f'{ST}/final/auto_started.json') is not None:
        if drained and getj(f'{ST}/final/auto_started.json') is None:
            s3.put_object(Bucket=B, Key=f'{ST}/final/auto_started.json', Body=json.dumps({'at': now()}).encode(), ContentType='application/json')
        try:
            fj = final_jobs(rows, {p: {c['id']: c for c in contents(p)} for p in ('ifc', 'db1')})
            prevf = getj(f'{ST}/final/jobs.json') or []
            have = {j['id'] for j in fj}
            fj += [j for j in prevf if j['id'] not in have]            # the list never shrinks mid-run
            s3.put_object(Bucket=B, Key=f'{ST}/final/jobs.json', Body=json.dumps(fj).encode(), ContentType='application/json')
        except Exception as e:
            print('final jobs error', e, flush=True)
    for r in rows:
        r['missing'], r['needed_to_fix'] = explain(r) if r['class'] in (2, 3) else ([], [])
    plan = fix_plan(rows)
    s3.put_object(Bucket=B, Key=f'{ST}/class2_fix_plan.json', Body=json.dumps({'updated': now(), 'items': plan}, indent=1).encode(),
                  ContentType='application/json')
    # write index + class lists
    paths = {k: os.path.join(W, f'{k}.jsonl.gz') for k in ('index', 'class_1_complete', 'class_2_partial', 'class_3_broken')}
    fh = {k: gzip.open(p, 'wt') for k, p in paths.items()}
    for r in rows:
        line = json.dumps(r, default=str) + '\n'
        fh['index'].write(line)
        if r['class'] in (1, 2, 3):
            fh[{1: 'class_1_complete', 2: 'class_2_partial', 3: 'class_3_broken'}[r['class']]].write(line)
    for f in fh.values():
        f.close()
    for k, p in paths.items():
        s3.upload_file(p, B, f'{ST}/{k}.jsonl.gz')
    # summary
    summ = {'updated': now(), 'rules': RULES, 'final': final, 'models': len(rows), 'pipelines': {}}
    for pipe in ('ifc', 'db1', 'sds2'):
        rs = [r for r in rows if r['pipeline'] == pipe]
        cls = collections.Counter(str(r['class']) for r in rs)
        corp = collections.Counter(f"{r['class']}{r['corpus'] or ''}" for r in rs if r['class'])
        reas = collections.defaultdict(collections.Counter); iss = collections.defaultdict(collections.Counter)
        stin = collections.Counter(); needs = collections.Counter()
        for r in rs:
            for x in r['reasons']:
                reas[str(r['class'])][x.split(':')[0] if not x.startswith(('member_coverage', 'part_coverage', 'steel_weight')) else x.split('_0')[0].split('_1')[0]] += 1
            for x in r['issues']:
                iss[str(r['class'])][x.split(':')[0].split(' (')[0] if not x.startswith('bbox_extent') else 'bbox_extent_large'] += 1
            for s_ in r['standins']:
                stin[s_['type']] += 1
            for n_ in r['needs']:
                needs[n_.split(':')[0]] += 1
        summ['pipelines'][pipe] = {
            'models': len(rs), 'by_class': dict(cls), 'by_class_corpus': dict(corp),
            'by_status': dict(collections.Counter(r['status'] for r in rs)),
            'reused': sum(1 for r in rs if r['reused']), 'reused_by_source': dict(collections.Counter(r['reuse_from'] for r in rs if r['reused'])),
            'new_conversions': sum(1 for r in rs if not r['reused'] and r['step_key']),
            'class3_reasons': dict(reas['3'].most_common(25)), 'class2_issues': dict(iss['2'].most_common(25)),
            'standin_models_by_type': dict(stin.most_common(20)), 'needs': dict(needs.most_common(15)),
            'domain': dict(collections.Counter(r['domain'] for r in rs if r['domain'])),
            'progress': progress(pipe)}
    summ['grade_progress'] = progress('grade')
    summ['final_progress'] = progress('final')
    try:                                          # final jobs all done after an automatic start -> the coordinator builds the final index
        fp = summ['final_progress']
        if getj(f'{ST}/final/auto_started.json') is not None and (fp.get('pending') or 0) == 0 and (fp.get('in_flight') or 0) == 0 \
                and getj(f'{ST}/final/READY') is None:
            s3.put_object(Bucket=B, Key=f'{ST}/final/READY', Body=json.dumps({'at': now(), 'final_jobs': fp.get('jobs')}).encode(), ContentType='application/json')
    except Exception as e:
        print('final ready check error', e, flush=True)
    summ['reconvert'] = recon; summ['versions'] = vmat
    summ['class_rules'] = {
        '1': 'opens (OCC read-back or converter verify), 100% of expected physical parts present (members + connection parts the source has), '
             'all solids valid, no stand-ins, per-part volume within +-5% where an expected value exists, bbox plausible, render not blank',
        '2': 'opens with valid solids but: coverage < 100%, or stand-ins/approximations (listed with real type), or missing external input (needs), '
             'or invalid solids > 0, or parts outside the volume/weight tolerance, or not read back (STEP > 1 GB, text checks only)',
        '3': 'no STEP, read failure, 0 solids, source unreadable/corrupt/encrypted/geometry-free, member coverage < 50%, absurd bbox, blank render',
        'corpus': 'A = class 1 with connection parts; B = connection parts present, with stand-ins and/or listed missing pieces; '
                  'C = members only (no connection pieces in the STEP); R = reference / imported model geometry (SDS/2 reference models); '
                  'null = class 3 or non-steel model',
        'dedup': 'IFC by file sha256; DB1 by file sha256 (xslib.db1 excluded); SDS2 by converter-input fingerprint (main/jsetup, main/job_mtrl, '
                 'mem/mem_idx, mem/<n>, subm/subm_idx, subm/<n>)',
        'reuse': 'earlier accepted conversions of the same content (sha256 / fingerprint; Disk-2 run-2 by byte-identical archive + job root) '
                 'are indexed with their existing STEP key and re-graded under these rules (reused=true)'}
    json.dump(summ, open(os.path.join(W, 'index_summary.json'), 'w'), indent=1, default=str)
    s3.upload_file(os.path.join(W, 'index_summary.json'), B, f'{ST}/index_summary.json')
    # live-site status (lead's schema; counts only)
    def P(rs, pipe):
        pr = summ['pipelines'][pipe]['progress'] if pipe else None
        top = collections.Counter()
        for r in rs:
            for x in r['reasons'] if r['class'] == 3 else ([i for i in r['issues']] + [s_['type'] for s_ in r['standins']] if r['class'] == 2 else []):
                k = x.split(':')[0].split(' (')[0]
                if k.startswith(('member_coverage', 'part_coverage')):
                    k = k.rsplit('_', 1)[0] + '_low'
                if k.startswith('steel_weight_ratio'):
                    k = 'steel_weight_ratio_off'
                if k.startswith('bbox_extent'):
                    k = 'bbox_extent_large'
                top[f"{r['class']}:{k}"] += 1
        stp = [r for r in rs if r['step_key'] and r['class'] in (1, 2)]
        return {'distinct': len(rs), 'to_convert': sum(1 for r in rs if not r['reused'] and r['status'] not in ('failed_before', 'no_source_copy', 'empty_source')),
                'reused': sum(1 for r in rs if r['reused']),
                'done': pr['done'] if pr else None, 'in_flight': pr['in_flight'] if pr else None, 'pending': pr['pending'] if pr else None,
                'step_files': len(stp), 'step_bytes': sum(int(r.get('step_bytes') or 0) for r in stp),
                'graded': sum(1 for r in rs if r['class'] in (1, 2, 3)),
                'classes': {k: sum(1 for r in rs if r['class'] == int(k)) for k in ('1', '2', '3')},
                'corpus': {k: sum(1 for r in rs if r['corpus'] == k) for k in ('A', 'B', 'C', 'R')},
                'top_reasons': dict(top.most_common(8))}
    pipes_P = {p: P([r for r in rows if r['pipeline'] == p], p) for p in ('ifc', 'db1', 'sds2')}
    tot = P(rows, None)
    for k in ('done', 'in_flight', 'pending'):
        tot[k] = sum(pipes_P[p][k] or 0 for p in pipes_P)
    # fleet + utilization from live worker heartbeats (+ the coordinator)
    t = time.time(); hosts = {}; util = {}
    hostpipe = {}
    for p in ('ifc', 'db1', 'sds2', 'grade'):
        for o in lst(f'{ST}/{p}/hosts/'):
            if t - o['LastModified'].timestamp() < 300:
                h = getj(o['Key']) or {}
                if not h.get('host'):
                    continue
                hosts[h['host']] = max(hosts.get(h['host'], 0), int(h.get('cpus') or 0))
                hostpipe.setdefault(h['host'], {}).setdefault(p, []).append(h)
    for host, pp in hostpipe.items():
        cpus = hosts[host] or 0
        for p, hs in pp.items():
            u = util.setdefault(f'{p}@{cpus}vcpu', {'boxes': set(), 'slots': 0, 'in_flight': 0, 'load': []})
            u['boxes'].add(host); u['slots'] += max(h.get('slots') or 0 for h in hs)
            u['in_flight'] += sum(len(h.get('running') or []) for h in hs); u['load'].append(max(float(h.get('load') or 0) for h in hs))
    util = {k: {'boxes': len(v['boxes']), 'slots': v['slots'], 'in_flight': v['in_flight'],
                'load_avg': round(sum(v['load']) / len(v['load']), 1) if v['load'] else None} for k, v in sorted(util.items())}
    # per-box table: load / vCPU, jobs per pipeline (all worker generations), memory, the claim gate's last reading
    boxes = []
    for host, pp in sorted(hostpipe.items()):
        hs = [h for p_ in pp.values() for h in p_]
        newest = max(hs, key=lambda h: h.get('at') or '')
        prim = next((h.get('primary_pipe') for h in hs if h.get('primary_pipe')), None)
        gate = next((h.get('gate') for h in sorted(hs, key=lambda h: (h.get('gate') or {}).get('at') or '', reverse=True) if h.get('gate')), None) or {}
        boxes.append({'host': host, 'pipeline': prim, 'cpus': hosts.get(host), 'load': round(float(newest.get('load') or 0), 1),
                      'jobs': {p_: sum(len(h.get('running') or []) for h in v) for p_, v in pp.items()},
                      'worker_processes': len(hs), 'mem_total_gb': newest.get('mem_total_gb'), 'mem_avail_gb': newest.get('mem_avail_gb'),
                      'reserved_gb': gate.get('host_resv_gb'), 'gate': {k: gate.get(k) for k in ('ok_cpu', 'ok_mem', 'cap_cpu', 'recent_cores')} if gate else None})
    util['boxes'] = boxes
    try:
        util['mem_buckets'] = mem_tables(res, grades, hostpipe)
    except Exception as e:
        util['mem_buckets'] = {'error': f'{type(e).__name__}: {str(e)[:160]}'}
    # memory kills (watchdog) in the last 30 min, per pipeline: deferred records written recently
    try:
        util['oom_kills_30min'] = {p: sum(1 for o in lst(f'{ST}/{p}/deferred/') if t - o['LastModified'].timestamp() < 1800)
                                   for p in ('ifc', 'db1', 'sds2', 'grade')}
    except Exception:
        pass
    if GRADING_ERRORS:
        util['grading_errors'] = len(GRADING_ERRORS)
        s3.put_object(Bucket=B, Key=f'{ST}/grading_errors.json', Body=json.dumps(GRADING_ERRORS[:500], indent=1).encode(), ContentType='application/json')
    del GRADING_ERRORS[:]
    conv = getj(f'{CTL}/sds2/converter.json', CB) or {}
    status = {'updated': summ['updated'], 'final': final, 'grading': 'final' if final else 'interim (monitoring; the deliverable classes come from one final pass over the final STEP set)',
              'pipelines': pipes_P, 'totals': tot,
              'fleet': {'boxes': len(hosts) + 1, 'vcpu': sum(hosts.values()) + (os.cpu_count() or 0)}, 'utilization': util,
              'converters': {'ifc': 'ifc2step5', 'db1': 'db1step', 'sds2': conv.get('label', 'v4')},
              'fix_plan_top': [{k: e[k] for k in ('key', 'fix', 'category', 'models', 'lift_to_class1_if_only_fix')} for e in plan[:12]],
              'versions': vmat, 'history': [{k: v for k, v in h.items() if k != 'ids_key'} for h in hist],
              'class_rule': 'class 1 = opens, 100% of source parts, all solids valid, no stand-ins, per-part volume within 5%; '
                            'class 2 = opens with valid solids but partial / stand-ins / needs input / invalid or off-tolerance parts; '
                            'class 3 = no STEP, unreadable, empty, corrupt or geometry-free source, member coverage < 50%, absurd bbox, blank render'}
    s3.put_object(Bucket=B, Key=f'{ROOT}/_state/conv_status.json', Body=json.dumps(status, indent=1, default=str).encode(),
                  ContentType='application/json', CacheControl='no-cache')
    return summ


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--loop', type=int, default=0); ap.add_argument('--final', action='store_true')
    a = ap.parse_args()
    while True:
        try:
            s = once(a.final)
            print(now(), {p: (v['progress']['done'], v['progress']['jobs'], v['by_class']) for p, v in s['pipelines'].items()}, flush=True)
        except Exception as e:
            import traceback
            print(now(), 'error', type(e).__name__, str(e)[:300], traceback.format_exc()[-800:], flush=True)
        if not a.loop:
            break
        time.sleep(a.loop)
