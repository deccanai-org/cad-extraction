#!/usr/bin/env python3
"""coverage-regression patch for coord/build_index.py (anchor-checked, idempotent; prints what it changed).

  1. DB1 rows reused from the Windows (C#) pipeline (reuse_from = disk-1/2-windows): coverage from the exact per-part Tekla-id join
     of the STEP's child products ('... [tekla_id]') with the decoder inventory (windows_join.py results, WJ_PREFIX/<sha>.json),
     instead of the manifest ratio solids_written / parts (bolt groups counted as parts, says nothing about members). Manifest
     ratio kept only as the fallback when no join result exists.
  2. DB1 best-of between a reused STEP and a fresh data-3 conversion (once()): class first, then member coverage, then all-parts
     coverage (each only when the difference is > 1 point), and only then the stock rule (fewer issues + stand-ins + needs).
     IFC / SDS2 keep the stock rule.

usage: apply_cov_patch.py BUILD_INDEX.py [OUT.py]     (OUT defaults to in-place)
"""
import sys, re

src_p = sys.argv[1]; out_p = sys.argv[2] if len(sys.argv) > 2 else src_p
s = open(src_p).read()
MARK = '# [coverage-regression patch v1]'
if MARK in s:
    print('already patched'); open(out_p, 'w').write(s); sys.exit(0)
changes = []

# 1) constants
a1 = "W = os.environ.get('INDEX_WORK', '/work/index'); os.makedirs(W, exist_ok=True)\n"
assert s.count(a1) == 1, 'anchor 1 (INDEX_WORK line) not found exactly once'
s = s.replace(a1, a1 + f"""{MARK}
# exact per-part Tekla-id join of the Windows (C#) pipeline STEPs with the decoder inventory (windows_join.py; static inputs,
# computed once on an agent box): {{sha256: {{'status', 'join': {{coverage, expected, matched, ...}}, 'lost': ..., 'schedule': ...}}}}
WJ_PREFIX = f'{{ROOT}}/_state/agentwork/coverage-regression/wj/'
WJ = {{}}
BEST_OF_COV_TOL = 0.01          # DB1 best-of: coverage differences up to 1 point count as equal
""")
changes.append('constants WJ_PREFIX / WJ / BEST_OF_COV_TOL')

# 2) classify_db1 Windows branch
old2 = re.search(r"    if row.get\('reuse_from'\) == 'disk-1/2-windows'.*?\n        return finish_class\(row, has_conn=has_conn, src_conn=None, steel=True\)\n", s, re.S)
assert old2 and s.count("if row.get('reuse_from') == 'disk-1/2-windows'") == 1, 'anchor 2 (Windows branch in classify_db1) not found exactly once'
new2 = """    if row.get('reuse_from') == 'disk-1/2-windows':
        # the Windows (C#) pipeline writes the whole model under ONE root product (children '... [tekla_id]' via NAUO), so the
        # name join of step_check sees 1 part. Coverage = exact Tekla-id join of the children with the decoder inventory (WJ);
        # the manifest ratio (solids written / parts incl. bolt groups) is only the fallback when no join result exists.
        pm = (r.get('prior_result') or {}).get('manifest') or {}
        try:
            parts = int(pm.get('parts') or 0); written = int(pm.get('solids_written') or 0); bolts = int(pm.get('bolts') or 0)
        except ValueError:
            parts = written = bolts = 0
        wjr = WJ.get(row['id']) or {}
        jj = r.get('windows_join') if isinstance(r.get('windows_join'), dict) and r['windows_join'].get('coverage') else None
        jj = jj or (wjr.get('join') if wjr.get('status') == 'ok' else None)
        if jj and jj.get('coverage'):
            cv = jj['coverage']
            row['coverage_members'] = cv.get('member'); row['coverage_connections'] = cv.get('connection')
            row['coverage_other'] = cv.get('other'); row['coverage_all'] = cv.get('all')
            row['parts_source'] = jj.get('parts_source'); row['parts_step'] = jj.get('parts_step')
            row['coverage_basis'] = 'windows_tekla_id_join'
            row['windows_join'] = {k: jj.get(k) for k in ('expected', 'matched', 'axis_dropped', 'step_products_with_solid', 'ids_unknown_to_decoder')}
            row['windows_join']['lost_top'] = ((wjr.get('lost') or {}).get('by_cat_why_profile') or [])[:8]
            row['issues_info'] = (row.get('issues_info') or []) + [f'Windows pipeline manifest: {written} solids written of {parts} parts (bolt groups counted as parts)']
        else:
            row['parts_source'] = parts; row['parts_step'] = v.get('transferred') or written
            row['coverage_all'] = round(written / parts, 4) if parts else None
            row['coverage_basis'] = 'windows_manifest'
            row['issues'].append('inventory from the Windows pipeline manifest (parts vs solids written)')
        if bolts:
            row['standins'].append({'type': 'bolt_solid_no_hole', 'real_type': 'bolt (holes not cut)', 'count': bolts})
        has_conn = int(pm.get('plates') or 0) + bolts > 0
        return finish_class(row, has_conn=has_conn, src_conn=None, steel=True)
"""
s = s[:old2.start()] + new2 + s[old2.end():]
changes.append('classify_db1: Windows rows graded on the Tekla-id join (manifest ratio = fallback)')

# 3) best_of_db1 helper, right before classify_sds2
a3 = '\ndef classify_sds2(c, res, grade):\n'
assert s.count(a3) == 1, 'anchor 3 (def classify_sds2) not found exactly once'
s = s.replace(a3, '''
def _cov_m(r):
    cm = r.get('coverage_members')
    if cm is None:
        cm = r.get('coverage_all')
    return min(float(cm), 1.0) if isinstance(cm, (int, float)) else 0.0


def _cov_a(r):
    ca = r.get('coverage_all')
    return min(float(ca), 1.0) if isinstance(ca, (int, float)) else 0.0


def best_of_db1(rr, rn):
    """reused STEP (rr) vs fresh data-3 conversion (rn) of the same DB1 -> (row kept, why). Class first; within one class the STEP
    holding clearly more of the source (member coverage, then all-parts coverage, each > BEST_OF_COV_TOL apart) wins; only then
    the stock rule (fewer issues + stand-ins + needs). A short issue list is not a better STEP: the Windows-pipeline rows list
    almost nothing, and on the count alone they kept STEPs with 0-15 % of the members over data-3 conversions with 49-100 %."""
    def n(r):
        return len(r['issues']) + len(r['standins']) + len(r['needs'])
    if rn['class'] is None:
        win, why = rr, 'fresh conversion not graded'
    elif rr['class'] is None:
        win, why = rn, 'reused STEP not graded'
    elif rn['class'] != rr['class']:
        win = rn if rn['class'] < rr['class'] else rr
        why = f'class {rn["class"]} vs {rr["class"]}'
    elif abs(_cov_m(rn) - _cov_m(rr)) > BEST_OF_COV_TOL:
        win = rn if _cov_m(rn) > _cov_m(rr) else rr
        why = f'member coverage {_cov_m(rn):.4f} vs {_cov_m(rr):.4f}'
    elif abs(_cov_a(rn) - _cov_a(rr)) > BEST_OF_COV_TOL:
        win = rn if _cov_a(rn) > _cov_a(rr) else rr
        why = f'all-parts coverage {_cov_a(rn):.4f} vs {_cov_a(rr):.4f}'
    else:
        win = rn if n(rn) <= n(rr) else rr
        why = f'coverage equal; issues+stand-ins+needs {n(rn)} vs {n(rr)}'
    if win is rn:
        rn['supersedes'] = {'from': rr.get('reuse_from'), 'step_key': rr.get('step_key'), 'class': rr['class'],
                            'coverage_members': rr.get('coverage_members'), 'coverage_all': rr.get('coverage_all'), 'why': why}
    else:
        rr['alternative'] = {'converter_code': rn.get('converter_code'), 'class': rn['class'], 'step_key': rn.get('step_key'),
                             'coverage_members': rn.get('coverage_members'), 'coverage_all': rn.get('coverage_all'), 'why': why}
    return win, why

''' + a3)
changes.append('best_of_db1()')

# 4) once(): load WJ each round + DB1 uses best_of_db1
a4 = "    finals = load_results(f'{ST}/final/results/')\n"
assert s.count(a4) == 1, 'anchor 4 (finals = load_results) not found exactly once'
s = s.replace(a4, a4 + """    try:
        WJ.clear(); WJ.update({k: v for k, v in load_results(WJ_PREFIX).items() if not k.startswith('_')})
    except Exception as e:
        print('windows join load error', e, flush=True)
""")
a5 = "                    r = rr or rn\n                elif rn['class'] is not None and (rr['class'] is None or score(rn) <= score(rr)):\n"
assert s.count(a5) == 1, 'anchor 5 (best-of branch in once) not found exactly once'
s = s.replace(a5, "                    r = rr or rn\n                elif pipe == 'db1':\n                    r, _why = best_of_db1(rr, rn)\n"
                  "                elif rn['class'] is not None and (rr['class'] is None or score(rn) <= score(rr)):\n")
changes.append('once(): WJ loaded every round; DB1 best-of via best_of_db1')

compile(s, out_p, 'exec')
open(out_p, 'w').write(s)
print('patched ->', out_p); [print('  -', c) for c in changes]
