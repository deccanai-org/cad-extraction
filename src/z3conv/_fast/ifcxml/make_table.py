#!/usr/bin/env python3
"""make_table.py - join the box outputs of the ifcxml stream into one evidence table (small JSON files only).

    make_table.py EVDIR      EVDIR holds: conv/<sha>/summary.json (first run: v1.0.0 SPF + STEP chain),
                             v11/conv/<sha>/summary.json (final converter v1.1.0: conversion + validation + census),
                             harness/results/<sha>.json (patched fleet worker), spf_identity_v10_v11.json
Writes EVDIR/ifcxml_evidence.json and prints one line per input.
"""
import os, sys, json, glob

ev = sys.argv[1]


def load(p):
    try:
        return json.load(open(p))
    except Exception:
        return None


ident = load(os.path.join(ev, 'spf_identity_v10_final.json')) or load(os.path.join(ev, 'spf_identity_v10_v11.json')) or {}
same = set(ident.get('identical_data_sections') or [])
rows = []
for p in sorted(glob.glob(os.path.join(ev, 'conv', '*', 'summary.json'))):
    r1 = load(p)
    sha = r1['sha256']
    r2 = load(os.path.join(ev, 'final', 'conv', sha, 'summary.json')) or load(os.path.join(ev, 'v11', 'conv', sha, 'summary.json')) or {}
    h = load(os.path.join(ev, 'harness', 'results', sha + '.json')) or {}
    x = r2.get('ifcxml2spf') or r1.get('ifcxml2spf') or {}
    v = r2.get('validate') or r1.get('validate') or {}
    c = r2.get('census') or r1.get('census') or {}

    def chain(s):
        if not s:
            return None
        cv = s.get('convert') or {}
        ck = s.get('check') or {}
        j = s.get('join') or {}
        vol = j.get('volume') or {}
        return {'parts': cv.get('parts'), 'rc': cv.get('rc'), 'sec': cv.get('sec'), 'tags': cv.get('tags'),
                'readback_roots': ck.get('roots'), 'solids': ck.get('solids'), 'invalid_solids': ck.get('invalid_solids'),
                'step_bytes': s.get('step_bytes'), 'expected': j.get('expected'), 'matched': j.get('matched'),
                'coverage_all': (j.get('coverage') or {}).get('all'), 'unmatched_step_parts': j.get('step_parts_unmatched'),
                'volume_checked': vol.get('checked'), 'volume_within_5pct': vol.get('within_5pct'),
                'volume_outside_5pct': vol.get('outside_5pct'), 'volume_median': vol.get('median')}
    hs = h.get('step') or {}
    hj = h.get('join') or {}
    hv = h.get('validate') or {}
    row = {
        'sha256': sha, 'name': r1.get('name'), 'path': (r1.get('paths') or [None])[0], 'in_bytes': r1.get('in_bytes'),
        'conversion': {k: x.get(k) for k in ('status', 'schema', 'container', 'member', 'xml_bytes', 'instances',
                                             'references', 'dangling_references', 'unknown_xml_names', 'value_errors', 'notes',
                                             'xml_root')},
        'converter_version_final': 'ifcxml2spf 1.1.1' if r2 else None,
        'spf_data_section_identical_first_run_vs_final': (sha[:12] in same) if ident else None,
        'validation': {k: v.get(k) for k in ('verdict', 'spf_instances', 'xml_instances_with_id', 'xml_instance_elements',
                                             'instance_count_equal', 'per_type_equal', 'roundtrip_counts', 'roundtrip_failures',
                                             'schema_issues', 'schema_issue_kinds', 'duplicate_globalids_in_source',
                                             'unit_scale_m', 'products', 'products_with_representation')},
        'opens_in_ifcopenshell_0.8.4': (r2.get('open_ifcopenshell_084') or r1.get('open_ifcopenshell_084') or {}).get('out'),
        'census': {k: c.get(k) for k in ('products', 'with_body', 'by_category')},
        'ifc2step6_on_spf': chain(r1.get('v6')),
        'ifc2step6_builtin_reader_on_raw_xml': chain(r1.get('v6raw')),
        'patched_worker': {'status': h.get('status'), 'reason': h.get('reason'), 'code': h.get('code'),
                           'input_fix': h.get('input_fix'), 'ifcxml': h.get('ifcxml'),
                           'step_parts': hs.get('parts'), 'grade': hv.get('grade'), 'solids': hv.get('solids'),
                           'invalid_solids': hv.get('invalid_solids'), 'coverage': hj.get('coverage'),
                           'volume': {k: (hj.get('volume') or {}).get(k) for k in ('checked', 'within_5pct', 'outside_5pct')},
                           'redirected_uploads': len(h.get('redirected_uploads') or [])} if h else None,
    }
    rows.append(row)
    s6 = row['ifc2step6_on_spf'] or {}
    pw = row['patched_worker'] or {}
    print(sha[:12], (row['conversion']['status'] or '')[:12], row['conversion']['instances'], 'valid', row['validation']['verdict'],
          'rt_fail', row['validation']['roundtrip_failures'], '| census', row['census']['by_category'], '| v6 parts', s6.get('parts'),
          'cov', s6.get('coverage_all'), 'vol5', s6.get('volume_within_5pct'), '/', s6.get('volume_checked'), '| worker', pw.get('status'),
          pw.get('reason'), pw.get('step_parts'), (pw.get('coverage') or {}).get('all') if isinstance(pw.get('coverage'), dict) else None)
json.dump(rows, open(os.path.join(ev, 'ifcxml_evidence.json'), 'w'), indent=1, default=str)
print('rows', len(rows))
