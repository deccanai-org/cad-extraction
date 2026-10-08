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
import os, sys, json, gzip, time, math, argparse, collections
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
    'tolerated_standin_types': [],          # e.g. ["joist_openweb_standin"]: listed, but do not block class 1 (owner decision pending)
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
def base_row(c, pipe):
    return {'pipeline': pipe, 'id': c['id'], 'sha256': c.get('sha256'), 'fpc': c.get('fpc'), 'jsetup_sha256': c.get('jsetup_sha256'),
            'size': c.get('size') or c.get('model_bytes'), 'n_paths': c.get('n_paths'), 'paths': (c.get('paths') or [])[:5],
            'reused': False, 'reuse_from': None, 'step_key': None, 'render_key': None, 'class': None, 'corpus': None, 'domain': None,
            'coverage_members': None, 'coverage_connections': None, 'coverage_other': None, 'parts_source': None, 'parts_step': None,
            'solids': None, 'invalid_solids': None, 'standins': [], 'needs': [], 'issues': [], 'reasons': [], 'weight_ratio': None,
            'graded_by': None, 'status': None}


def step_checks(row, v, have_occ_keys=True):
    """common STEP signals from a step_check / validate dict"""
    rs = v.get('read_status')
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
    v = r.get('validate') or {}
    step_checks(row, v)
    cen = r.get('census') or {}; j = r.get('join') or {}
    row['schema'] = row.get('schema') or cen.get('schema')
    exp = cen.get('by_category') or {}
    row['parts_source'] = cen.get('expected_parts')
    row['parts_step'] = v.get('transferred') or (r.get('step') or {}).get('parts') or ((r.get('prior_result') or {}).get('stats') or {}).get('parts')
    if cen.get('error') or not j or j.get('error'):
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
    v = r.get('validate') or {}
    step_checks(row, v)
    dec = r.get('decoded') or {}
    j = r.get('join') or {}
    if row.get('reuse_from') == 'disk-1/2-windows' and not dec:
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
        {n_.split(':')[0] for n_ in r['needs']}
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


def reconvert(rows, contents_by_pipe):
    """rules s3://annotationprod/.../coord/reconvert.json: {pipe: {"code": <worker CODE that fixes it>, "match": [tags] | "*",
    "classes": [2, 3], "include_reused": true, "engines": [...] (db1 only, optional)}} -> _state/conv/<pipe>/redo.json (ids of
    data-3 results to re-run) and jobs_reconvert.json (reused models converted fresh into data-3; they supersede the reused STEP)"""
    rules = getj(f'{CTL}/coord/reconvert.json', CB) or {}
    hist = getj(f'{ST}/history.json') or []
    out = {}
    for pipe, rule_ in rules.items():
        if pipe not in ('ifc', 'db1', 'sds2'):
            continue
        rl = rule_ if isinstance(rule_, list) else [rule_]
        code = rl[0].get('code'); match = [m for r_ in rl for m in (r_.get('match') if isinstance(r_.get('match'), list) else ['*'])]
        cmap = {c['id']: c for c in contents_by_pipe[pipe]}
        redo_ids, jobs = [], []
        targeted = []

        def hit(r):
            for r_ in rl:
                if r['class'] not in set(r_.get('classes') or [2, 3]):
                    continue
                eng = set(r_.get('engines') or [])
                if eng and r.get('engine') not in eng:
                    continue
                m_ = r_.get('match', '*')
                if m_ != '*' and not (tags_of(r) & set(m_)):
                    continue
                return True
            return False
        for r in rows:
            if r['pipeline'] != pipe or not hit(r):
                continue
            if r.get('converter_code') == code or str(r.get('converter_code') or '').startswith(code):
                continue
            targeted.append(r['id'])
            if r['reused']:
                if rule.get('include_reused', True) and cmap.get(r['id']) and cmap[r['id']].get('input_key', True) is not None:
                    jobs.append(job_from_content(pipe, cmap[r['id']]))
            else:
                redo_ids.append(r['id'])
        # keep earlier targets in the list until their result carries the new code (the list must not shrink mid-run)
        prev = getj(f'{ST}/{pipe}/redo.json') or []
        prevj = getj(f'{ST}/{pipe}/jobs_reconvert.json') or []
        done_code = {r['id'] for r in rows if r['pipeline'] == pipe and r.get('converter_code') == code}
        redo_ids = sorted(set(redo_ids) | {i for i in prev if i not in done_code})
        have = {j['id'] for j in jobs}
        jobs += [j for j in prevj if j['id'] not in have]
        s3.put_object(Bucket=B, Key=f'{ST}/{pipe}/redo.json', Body=json.dumps(redo_ids).encode(), ContentType='application/json')
        s3.put_object(Bucket=B, Key=f'{ST}/{pipe}/jobs_reconvert.json', Body=json.dumps(jobs).encode(), ContentType='application/json')
        out[pipe] = {'code': code, 'redo': len(redo_ids), 'reconvert_reused': len(jobs)}
        # history: before/after class counts of the models this converter version targets
        ent = next((h for h in hist if h['pipeline'] == pipe and h['converter'] == code), None)
        byid = {r['id']: r for r in rows if r['pipeline'] == pipe}
        if ent is None and (targeted or jobs):
            ids = sorted(set(targeted) | {j['id'] for j in jobs})
            ent = {'pipeline': pipe, 'converter': code, 'started': now(), 'match': match, 'targeted': len(ids), 'ids_key': f'{ST}/history/{pipe}_{code}.json',
                   'before': dict(collections.Counter(str(byid[i]['class']) for i in ids if i in byid))}
            s3.put_object(Bucket=B, Key=ent['ids_key'], Body=json.dumps(ids).encode(), ContentType='application/json')
            hist.append(ent)
        if ent is not None:
            ids = getj(ent['ids_key']) or []
            reached = [i for i in ids if byid.get(i, {}).get('converter_code') == code]
            ent['after'] = dict(collections.Counter(str(byid[i]['class']) for i in reached))
            ent['reconverted'] = len(reached); ent['done'] = len(reached) >= len(ids); ent['updated'] = now()
    s3.put_object(Bucket=B, Key=f'{ST}/history.json', Body=json.dumps(hist, indent=1).encode(), ContentType='application/json')
    return out, hist


def classify_sds2_manifest(row, r, man, s2):
    """v5 sidecar: counts, stand-in groups with real types, skipped pieces, weight check total and by family, read-back"""
    cnt = man.get('counts') or {}; rb = man.get('readback') or {}; v = r.get('validate') or {}
    row['graded_by'] = 'converter_verify + v5 manifest (OCP read-back, BRepCheck per placed instance)'
    sol = rb.get('solids', v.get('solids')); val = rb.get('valid', v.get('valid'))
    row['solids'] = sol; row['invalid_solids'] = (sol - val) if sol is not None and val is not None else None
    if sol is None or val is None:
        row['reasons'].append('step_read_failed')
    elif sol == 0:
        row['reasons'].append('step_no_geometry')
    elif row['invalid_solids']:
        row['issues'].append(f'invalid_solids:{row["invalid_solids"]}')
    if rb.get('load_errors'):
        row['issues'].append(f'step_load_errors:{rb.get("load_errors")}')
    ink = v.get('render_ink')
    if ink is not None and ink < RULES['render_blank_ink']:
        row['reasons'].append('blank_render')
    bb = v.get('bbox_mm') or (r.get('step') or {}).get('bbox_mm')
    if bbox_ok(bb) is False:
        row['reasons'].append('bbox_absurd')
    row['bbox_mm'] = bb
    m_ = cnt.get('members') or 0
    row['coverage_members'] = round((m_ - (cnt.get('members_without_geometry') or 0)) / m_, 4) if m_ else None
    placed = cnt.get('placed_pieces') or 0
    row['coverage_connections'] = round((cnt.get('pieces_written') or 0) / placed, 4) if placed else None
    bolts = (cnt.get('bolts_sds2') or 0) + (cnt.get('bolts_nominal') or 0)
    row['parts_source'] = m_ and (placed + bolts + (cnt.get('member_envelopes') or 0) + (cnt.get('joist_standins') or 0)) or None
    row['parts_step'] = cnt.get('solids_written')
    row['coverage_all'] = row['coverage_connections']
    for g in man.get('standin_groups') or []:
        row['standins'].append({'type': g.get('type'), 'real_type': g.get('real_type'), 'count': g.get('count'), 'why': (g.get('reason') or '')[:160]})
    sbr = {k: v for k, v in (man.get('skipped_by_reason') or {}).items() if k not in ('total', 'by_reason', 'parts') and isinstance(v, int)}
    sk_by = (man.get('skipped_detail') or {}).get('by_reason') or sbr
    skipped = cnt.get('skipped') if cnt.get('skipped') is not None else sum(sk_by.values())
    if skipped:
        row['issues'].append(f'pieces_not_built:{skipped} (' + ','.join(f'{k}:{n}' for k, n in list(sk_by.items())[:6]) + ')')
    w = man.get('weight') or {}
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
    off = [f for f, x in (w.get('by_family') or {}).items() if x.get('ratio') is not None and (x.get('n') or 0) >= nmin and abs(x['ratio'] - 1) > tol]
    if off:
        row['issues'].append('family_weight_outside_5pct:' + ','.join(off[:6]))
    row['manifest_class'] = {'class': man.get('class'), 'corpus': man.get('corpus'), 'reasons': man.get('class_reasons')}
    row['issues_info'] = ['welds are not modelled (no readable weld geometry in SDS/2 files)']
    pk = (r.get('inventory') or {}).get('pieces_by_kind') or {}
    has_conn = (pk.get('plate', 0) + pk.get('fastener', 0) + bolts) > 0 if pk else bolts > 0
    for g in man.get('standin_groups') or []:
        if g.get('needed'):
            row.setdefault('group_needs', []).append({'type': g.get('type'), 'needed': str(g['needed'])[:200], 'count': g.get('count')})
    finish_class(row, has_conn=has_conn, src_conn=None, steel=True)
    refp = cnt.get('reference_parts') or 0
    if row['class'] in (1, 2) and (man.get('corpus') == 'R' or (refp and refp >= 0.5 * max(1, cnt.get('solids_written') or 0))):
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
    for pipe, fn in (('ifc', classify_ifc), ('db1', classify_db1), ('sds2', classify_sds2)):
        for c in contents(pipe):
            g = grades.get(f'{pipe}-{c["id"]}')
            res_ = res[pipe].get(c['id'])
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
