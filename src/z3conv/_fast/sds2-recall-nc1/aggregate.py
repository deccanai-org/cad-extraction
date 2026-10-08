#!/usr/bin/env python3
"""Aggregate the per-job NC1 hole checks and IFC recall runs (agent box) into report.json + report.md (+ S3).

Per job and STEP label: NC1 parts / distinct marks / holes, parts matched to a STEP piece (section + length), hole recall
and precision on the matched parts (overall and per role: rolled main members, angles, plates), STEP geometric hole
count vs the v5 manifest count; IFC recall per IFC class and STEP precision per kind. v4c vs v5.x deltas where both
exist, and the concrete defects (parts / groups with examples).
"""
import os, sys, json, glob, collections, time
import boto3

B = 'bim-proprietary-data'
D3 = 'cad-disk-extract/zenitude-data-3'
RES = f'{D3}/_state/agentwork/sds2-recall-nc1'
W = os.environ.get('W', '/work/agentwork/sds2-recall-nc1')
OUT = os.path.join(W, 'out')
V5 = ('v5.3', 'v5.2', 'v5.1', 'v5')


def ratio(a, b):
    return round(a / b, 4) if b else None


def family(v):
    """SDS2 version family as in conv_status: 7.1xx, 7.3xx, ..., 2015+"""
    try:
        a, b = str(v).split('.')[:2]
        if len(a) == 4:
            return '20xx'
        return f'{a}.{b[0]}xx'
    except Exception:
        return 'unknown'


def fmt(v):
    return '' if v is None else (f'{v:.3f}' if isinstance(v, float) else str(v))


def to_md(rep):
    """machine-generated tables of report.json (per job and label: NC1 hole recall / precision, IFC recall)"""
    L = [f"# sds2-recall-nc1 results ({rep['updated']}, {rep['jobs']} jobs)", '', '## Totals by STEP label (NC1 holes on matched parts; IFC products)', '',
         '| label | jobs | NC1 parts | matched parts | NC1 holes | STEP holes | matched | recall | precision | rolled | angle | plate | IFC runs | IFC recall | STEP precision |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for lab, t in sorted(rep['totals_by_label'].items()):
        L.append(f"| {lab} | {t.get('jobs', 0)} | {t.get('nc1_parts', 0)} | {t.get('matched_parts', 0)} | {t.get('nc1_holes_matched_parts', 0)} | "
                 f"{t.get('step_holes_matched_parts', 0)} | {t.get('holes_matched', 0)} | {fmt(t.get('hole_recall'))} | {fmt(t.get('hole_precision'))} | "
                 f"{fmt(t.get('rolled_main_recall'))} | {fmt(t.get('angle_recall'))} | {fmt(t.get('plate_recall'))} | {t.get('ifc_runs', 0)} | "
                 f"{fmt(t.get('ifc_recall'))} | {fmt(t.get('step_precision'))} |")
    L += ['', '## NC1 hole recall by label, SDS2 version family and role', '', '| label | family | jobs | role | parts | NC1 holes | STEP holes | matched | recall |', '|---|---|---|---|---|---|---|---|---|']
    for lab, fams in sorted(rep.get('nc1_by_label_version_family_role', {}).items()):
        for fam, e in sorted(fams.items()):
            for ro in ('rolled_main', 'angle', 'plate'):
                v = e.get(ro)
                if v and v['parts']:
                    L.append(f"| {lab} | {fam} | {e.get('jobs')} | {ro} | {v['parts']} | {v['nc1_holes']} | {v['step_holes']} | {v['matched']} | {fmt(v['recall'])} |")
    L += ['', '## Per job: NC1', '', '| job | id | label | SDS2 | NC1 parts | matched parts | NC1 holes | STEP holes | matched | recall | precision | rolled | angle | plate | strict-zero parts (holes) | STEP holes/piece | early-state? |',
          '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for j in rep['jobs_detail']:
        for lab, e in j['labels'].items():
            n = e.get('nc1')
            if not n:
                continue
            br = n['by_role']; sz = n.get('strict_zero') or {}
            L.append(f"| {j['name'][:40]} | {j['id'][:8]} | {lab}{'*' if n.get('step_source') == 'agent_run' else ''} | {n.get('sds2_version') or ''} | {n['parts']} | "
                     f"{n['matched_parts']} | {n['matched_nc1_holes']} | {n['matched_step_holes']} | {n['holes_matched']} | {fmt(n['recall'])} | {fmt(n['precision'])} | "
                     f"{fmt(br['rolled_main']['hole_recall'])} | {fmt(br['angle']['hole_recall'])} | {fmt(br['plate']['hole_recall'])} | "
                     f"{sz.get('parts')} ({sz.get('nc1_holes')}) | {fmt(n.get('step_hole_density'))} | {'yes' if n.get('early_state_suspect') else ''} |")
    L += ['', '## Per job: IFC recall (registered = >= 20 inlier member pairs, rms <= 10 mm, IFC inside the STEP extent)', '',
          '| job | id | label | IFC | products (excl. welds) | IFC recall (excl. welds) | STEP precision in IFC coverage | beams | columns | plates (conn.) | bolts | registered (inliers, rms mm) |',
          '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for j in rep['jobs_detail']:
        for lab, e in j['labels'].items():
            for r in e.get('ifc') or []:
                if r.get('status') and r.get('status') != 'ok':
                    L.append(f"| {j['name'][:40]} | {j['id'][:8]} | {lab} | {r.get('ifc', '')[-50:]} | | {r.get('status')} | | | | | | |"); continue
                rr = r.get('recall_by_ifc_role', {}); ov = r.get('overall', {})
                def g(prefix):
                    a = [v for k, v in rr.items() if k.startswith(prefix)]
                    n = sum(x[0] for x in a); m = sum(x[1] for x in a)
                    return f'{m}/{n}' if n else ''
                L.append(f"| {j['name'][:40]} | {j['id'][:8]} | {lab} | {r.get('ifc', '')[-50:]} | {ov.get('ifc_products_excl_welds')} | {fmt(ov.get('ifc_recall_excl_welds'))} | "
                         f"{fmt(ov.get('step_precision_in_ifc_coverage'))} | {g('IfcBeam')} | {g('IfcColumn')} | {g('IfcDiscreteAccessory:CONNECTION MATERIAL:plate')} | "
                         f"{g('IfcMechanicalFastener')} | {'yes' if r.get('registered_same_job') else 'no'} {r.get('registration_quality')} |")
    L += ['', '## Strongest evidence of holes missing in the STEP (same section, length within 3 mm, no candidate piece has a hole)', '',
          '| job | label | SDS2 | mark | profile | length mm | NC1 holes | STEP label | job STEP holes/piece |', '|---|---|---|---|---|---|---|---|---|']
    for d in rep.get('strict_zero_examples', [])[:60]:
        L.append(f"| {d['job'][:36]} | {d['label']} | {d.get('sds2_version') or ''} | {d['mark']} | {d['profile']} | {d['length']} | {d['nc1_holes']} | {(d.get('step_label') or '')[:60]} | {fmt(d.get('job_hole_density'))} |")
    return '\n'.join(L) + '\n'


def main():
    pairs = json.load(open(os.path.join(W, 'inv', 'pairs.json')))
    nc = {}; nosel = []
    for f in glob.glob(os.path.join(OUT, 'nc1', '*.json')):
        d = json.load(open(f))
        if 'summary' not in d:
            nosel.append({'id': d.get('id'), 'name': d.get('name'), 'status': d.get('nc1_status'), 'selection': d.get('nc1_selection')})
            continue
        s = d['summary']
        nc[(s['job_id'], s['label'])] = d
    ifc = collections.defaultdict(list)
    for f in glob.glob(os.path.join(OUT, 'ifc', '*.json')):
        r = json.load(open(f))
        if r.get('job_id'):
            ifc[(r['job_id'], r['label'])].append(r)
    jobs = sorted({k[0] for k in nc} | {k[0] for k in ifc})
    rows = []; defects = []
    tot = collections.defaultdict(lambda: collections.Counter())
    fam_t = collections.defaultdict(collections.Counter)
    strict_zero_ex = []
    ifc_role_t = collections.defaultdict(lambda: [0, 0]); step_kind_t = collections.defaultdict(lambda: [0, 0])
    for jid in jobs:
        o = pairs.get(jid, {})
        labs = sorted({k[1] for k in nc if k[0] == jid} | {k[1] for k in ifc if k[0] == jid}, key=lambda l: (l != 'v4c', l))
        jr = {'id': jid, 'name': o.get('name'), 'path': (o.get('paths') or [''])[0][-140:], 'model_bytes': o.get('model_bytes'),
              'nc1_sets': [(s['folder'][-90:], s['n'], s['rel']) for s in (o.get('nc1_sets') or [])[:3]], 'labels': {}}
        for lab in labs:
            e = {}
            d = nc.get((jid, lab))
            if d:
                s = d['summary']; m = s['matched_parts']
                e['nc1'] = {'parts': s['nc1_parts'], 'marks': s['nc1_marks_distinct'], 'nc1_holes': s['nc1_holes'], 'match_rate_parts': s['match_rate_parts'],
                            'matched_parts': m['parts'], 'matched_nc1_holes': m['nc1_holes'], 'matched_step_holes': m['step_holes'],
                            'holes_matched': m['holes_matched_in_position'], 'recall': m['hole_recall'], 'precision': m['hole_precision'],
                            'parts_missing_all_holes': m['parts_missing_all_holes'], 'parts_all_holes_matched': m['parts_all_holes_matched'],
                            'by_role': {k: {kk: v.get(kk) for kk in ('parts', 'nc1_holes', 'step_holes', 'holes_matched_in_position', 'hole_recall',
                                                                       'parts_missing_all_holes')} for k, v in s['by_role'].items()},
                            'by_mark_best': {kk: s['by_mark_best'].get(kk) for kk in ('parts', 'nc1_holes', 'holes_matched_in_position', 'hole_recall')},
                            'status': s['status'], 'step_holes_geometric': s['step_holes_geometric'],
                            'manifest_holes': (s.get('manifest_holes') or {}).get('holes') if isinstance(s.get('manifest_holes'), dict) else s.get('manifest_holes'),
                            'step_holes_by_kind': s.get('step_holes_by_kind'), 'non_hole_arcs': s.get('step_non_hole_arcs'),
                            'step_approx_matched': {kk: s['step_approx_matched'].get(kk) for kk in ('parts', 'nc1_holes', 'holes_matched_in_position')},
                            'stage': s.get('stage'), 'step_bytes': s.get('step_bytes'), 'sds2_version': s.get('sds2_version'),
                            'step_source': s.get('step_source'), 'step_hole_density': s.get('step_hole_density'),
                            'strict_zero': {k: (s.get('strict_zero') or {}).get(k) for k in ('parts', 'nc1_holes', 'by_role', 'approx_pieces')},
                            'early_state_suspect': bool(s.get('step_hole_density') is not None and s['step_hole_density'] < 0.1 and m['nc1_holes'] > 50)}
                sz = s.get('strict_zero') or {}
                for ex in (sz.get('examples') or [])[:6]:
                    strict_zero_ex.append(dict(ex, job=o.get('name'), id=jid, label=lab, sds2_version=s.get('sds2_version'),
                                               job_hole_density=s.get('step_hole_density')))
                jr['sds2_version'] = jr.get('sds2_version') or s.get('sds2_version')
                fam = family(s.get('sds2_version'))
                for ro in ('rolled_main', 'angle', 'plate'):
                    v = s['by_role'][ro]
                    fam_t[(lab, fam, ro)]['nc1_holes'] += v['nc1_holes']; fam_t[(lab, fam, ro)]['matched'] += v['holes_matched_in_position']
                    fam_t[(lab, fam, ro)]['step_holes'] += v['step_holes']; fam_t[(lab, fam, ro)]['parts'] += v['parts']
                fam_t[(lab, fam, 'jobs')]['n'] += 1
                t = tot[lab]
                t['jobs'] += 1; t['nc1_parts'] += s['nc1_parts']; t['matched_parts'] += m['parts']; t['nc1_holes_matched_parts'] += m['nc1_holes']
                t['step_holes_matched_parts'] += m['step_holes']; t['holes_matched'] += m['holes_matched_in_position']
                for ro, v in s['by_role'].items():
                    t[f'{ro}_nc1_holes'] += v['nc1_holes']; t[f'{ro}_matched'] += v['holes_matched_in_position']; t[f'{ro}_parts'] += v['parts']
                    t[f'{ro}_parts_missing_all'] += v['parts_missing_all_holes']
                # defects: worst parts
                bad = [r for r in d['rows'] if r['status'] in ('missing_holes', 'extra_holes', 'count_equal')]
                for r in sorted(bad, key=lambda r: -(r['nc1_holes'] - r.get('matched_holes', 0)))[:8]:
                    defects.append({'job': o.get('name'), 'id': jid, 'label': lab, 'mark': r['mark'], 'profile': r['profile'], 'code': r['code'],
                                    'length_mm': r['length'], 'status': r['status'], 'nc1_holes': r['nc1_holes'], 'step_holes': r.get('step_holes'),
                                    'matched': r.get('matched_holes'), 'nc1_d': r.get('nc1_diameters'), 'step_d': r.get('step_diameters'),
                                    'step_label': r.get('step_label', '')[:100], 'approx': r.get('step_approx'), 'length_match': r.get('length_match'),
                                    'nc1_x': (r.get('nc1_hole_x') or [])[:8], 'step_x': (r.get('step_hole_x') or [])[:8], 'file': r['file'][-80:]})
            rr = ifc.get((jid, lab)) or []
            if rr:
                e['ifc'] = []
                for r in rr:
                    if r.get('status') != 'ok':
                        e['ifc'].append({'status': r.get('status'), 'ifc': (r.get('ifc_path') or '')[-100:], 'registration': r.get('registration')}); continue
                    e['ifc'].append({'ifc': (r.get('ifc_path') or '')[-100:], 'rel': r.get('ifc_rel'), 'ifc_products': r['ifc_products'], 'step_solids': r['step_solids'],
                                     'overall': r['overall'], 'reg_used': r['registration'].get('used'), 'rot_deg': r['registration'].get('rotation_deg'),
                                     'recall_by_ifc_role': {k: [v['n'], v['matched'], v['recall']] for k, v in r['recall_by_ifc_role'].items()},
                                     'precision_by_step_kind': {k: [v['n'], v['matched'], v['precision'], v.get('n_in_ifc_coverage'), v.get('precision_in_ifc_coverage')]
                                                                for k, v in r['precision_by_step_kind'].items()},
                                     'sds2_version': r.get('sds2_version'), 'step_source': r.get('step_source'),
                                     'section_agreement': r.get('section_agreement_on_matched'), 'plan_overlap': r.get('plan_overlap'),
                                     'unmatched_ifc_top': [(g['role'], g['section'], g['n']) for g in r.get('unmatched_ifc_top', [])[:8]],
                                     'unmatched_step_top': [(g['cls'], g['section'], g['n']) for g in r.get('unmatched_step_top', [])[:8]]})
                    reg_ = r.get('registration') or {}
                    registered = bool((reg_.get('inlier_pairs') or 0) >= 20 and (reg_.get('inlier_rms_mm') or 99) <= 10.0
                                      and ((r.get('plan_overlap') or {}).get('intersection_over_ifc') or 0) >= 0.8)
                    e['ifc'][-1]['registered_same_job'] = registered
                    e['ifc'][-1]['registration_quality'] = [reg_.get('inlier_pairs'), reg_.get('inlier_rms_mm')]
                    t = tot[lab + ('' if registered else ' (IFC not registered to this job)')]; ov = r['overall']
                    npx = ov.get('ifc_products_excl_welds') or 0
                    t['ifc_runs'] += 1; t['ifc_products'] += npx; t['ifc_matched'] += int(round((ov.get('ifc_recall_excl_welds') or 0) * npx))
                    nc_ = ov.get('step_solids_in_ifc_coverage') or 0
                    t['step_solids'] += nc_; t['step_matched'] += int(round((ov.get('step_precision_in_ifc_coverage') or 0) * nc_))
                    if registered:
                        for k, v in r['recall_by_ifc_role'].items():
                            base = k.split(':')[0] if not k.startswith('weld') else 'weld'
                            ifc_role_t[(lab, base)][0] += v['n']; ifc_role_t[(lab, base)][1] += v['matched']
                        for k, v in r['precision_by_step_kind'].items():
                            step_kind_t[(lab, k)][0] += v.get('n_in_ifc_coverage') or 0
                            step_kind_t[(lab, k)][1] += int(round((v.get('precision_in_ifc_coverage') or 0) * (v.get('n_in_ifc_coverage') or 0)))
            jr['labels'][lab] = e
        # v4c vs v5.x
        v5 = next((l for l in V5 if l in jr['labels']), None)
        if 'v4c' in jr['labels'] and v5:
            a, b = jr['labels']['v4c'].get('nc1'), jr['labels'][v5].get('nc1')
            if a and b:
                jr['nc1_v4c_vs_v5'] = {'v5_label': v5, 'recall': [a['recall'], b['recall']], 'matched_parts': [a['matched_parts'], b['matched_parts']],
                                       'holes_matched': [a['holes_matched'], b['holes_matched']], 'step_holes': [a['matched_step_holes'], b['matched_step_holes']]}
            ia = {x['ifc']: x for x in jr['labels']['v4c'].get('ifc') or [] if x.get('overall')}
            ib = {x['ifc']: x for x in jr['labels'][v5].get('ifc') or [] if x.get('overall')}
            both = sorted(set(ia) & set(ib))
            if both:
                jr['ifc_v4c_vs_v5'] = [{'ifc': k[-80:], 'v5_label': v5,
                                        'ifc_recall_excl_welds': [ia[k]['overall'].get('ifc_recall_excl_welds'), ib[k]['overall'].get('ifc_recall_excl_welds')],
                                        'step_precision_in_ifc_coverage': [ia[k]['overall'].get('step_precision_in_ifc_coverage'), ib[k]['overall'].get('step_precision_in_ifc_coverage')],
                                        'step_solids': [ia[k]['step_solids'], ib[k]['step_solids']]} for k in both]
        rows.append(jr)
    totals = {}
    for lab, t in tot.items():
        totals[lab] = dict(t)
        totals[lab]['hole_recall'] = ratio(t['holes_matched'], t['nc1_holes_matched_parts'])
        totals[lab]['hole_precision'] = ratio(t['holes_matched'], t['step_holes_matched_parts'])
        for ro in ('rolled_main', 'angle', 'plate'):
            totals[lab][f'{ro}_recall'] = ratio(t[f'{ro}_matched'], t[f'{ro}_nc1_holes'])
        totals[lab]['ifc_recall'] = ratio(t['ifc_matched'], t['ifc_products']); totals[lab]['step_precision'] = ratio(t['step_matched'], t['step_solids'])
        totals[lab]['ifc_recall_by_class'] = {b: [v[0], v[1], ratio(v[1], v[0])] for (l2, b), v in sorted(ifc_role_t.items()) if l2 == lab}
        totals[lab]['step_precision_in_coverage_by_kind'] = {k: [v[0], v[1], ratio(v[1], v[0])] for (l2, k), v in sorted(step_kind_t.items()) if l2 == lab}
    by_family = {}
    for (lab, fam, ro), c in sorted(fam_t.items()):
        e = by_family.setdefault(lab, {}).setdefault(fam, {})
        if ro == 'jobs':
            e['jobs'] = c['n']
        else:
            e[ro] = {'parts': c['parts'], 'nc1_holes': c['nc1_holes'], 'step_holes': c['step_holes'], 'matched': c['matched'],
                     'recall': ratio(c['matched'], c['nc1_holes']), 'precision': ratio(c['matched'], c['step_holes'])}
    rep = {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'jobs': len(rows), 'totals_by_label': totals,
           'nc1_by_label_version_family_role': by_family, 'jobs_detail': rows, 'jobs_without_nc1_for_the_job': nosel,
           'defects_top': sorted(defects, key=lambda d: -(d['nc1_holes'] - (d['matched'] or 0)))[:300],
           'strict_zero_examples': sorted(strict_zero_ex, key=lambda d: -d['nc1_holes'])[:200]}
    json.dump(rep, open(os.path.join(OUT, 'report.json'), 'w'), indent=1, default=str)
    open(os.path.join(OUT, 'report.md'), 'w').write(to_md(rep))
    c = boto3.client('s3', region_name='ap-south-1')
    c.upload_file(os.path.join(OUT, 'report.json'), B, f'{RES}/out/report.json')
    c.upload_file(os.path.join(OUT, 'report.md'), B, f'{RES}/out/report.md')
    print(json.dumps({'jobs': len(rows), 'totals': totals, 'by_family': by_family}, indent=1, default=str)[:8000])


if __name__ == '__main__':
    main()
