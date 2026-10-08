#!/usr/bin/env python3
"""complete_core.py JOB.json WORK OUT   (container side, conda env python /opt/conv/env/bin/python)

DB1 restoration (GREEN) of one DB1-sourced partial model: the decoder kit_g (= kit_v + completion flags + restoration log)
re-decodes the DB1 with the data the shipped conversion left unused; the result is the COMPLETED IFC.

  1. control: kit_v convert_one (the shipped conversion's own decoder, same CPU numeric profile) -> base.ifc; every product's
     geometry must equal the delivered source IFC (source/model.ifc of the src_db1 stage) -> proves this container decodes
     exactly as the conversion did, so every difference in step 2 comes from the completion flags alone
  2. completion: kit_g convert_complete.py -> comp.ifc + restoration events (record -> what, DB1 field)
  3. GlobalIds: products get the delivered GlobalIds (record -> GlobalId through both parts lists); other IfcRoot entities get
     ifc_guid(model id, entity id) (regen_core.restore); header / OwnerHistory times := the source IFC's (determinism)
  4. per-product geometry comparison completed vs delivered source IFC (ifc_canon): unchanged / restored (changed with an
     event) / unexpected (changed without an event = failure)
  5. optional: ifc2step6 (the shipped STEP stage, same flags) on the completed IFC -> completed STEP + per-part volumes,
     compared with the shipped STEP's parts.json (unchanged parts: same volume; restored parts: volume change reported)
JOB.json {model_id, tag, db1, orig_ifc, skipped_records, orig_step_parts (optional), do_step}
OUT: model_completed.ifc, restoration_log.json, completed.stp (+ .parts.json) when do_step"""
import gzip, hashlib, json, os, re, shutil, sys, time

sys.path.insert(0, '/pmp/src_db1')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regen_core as R  # noqa: E402
import ifc_canon  # noqa: E402

PROFILE = 'x86-64-v4'
KIT_V = os.path.join(R.KITS, 'kit_v')
KIT_G = os.path.join(R.KITS, 'kit_g')
GEOM_KINDS = {'slotted_hole', 'fitting_applied', 'outline_despiked'}
VALIDATION = {
    'slots_v2': {'7.64': '1246/1249', '7.82': '5851/5988', '8.07': '5943/6067', '8.44': '1970/2019', '8.53': '619/621',
                 '8.85': '1706/1806', '9.08': '283/283'},
    'slots_old': {'6.87': '374/374 (7.01 layout) + six 6.87 models 45 -> 0 cut round, 0 invalid', '7.01': '374/374',
                  '7.24': '2370/2496', '7.30': '546/546'},
    'fittings_perp': '8.07 / 8.53 / 8.85 / 9.08 perpendicular trims >= 98 % better-or-equal vs Tekla IFC (kit_v z3 t)',
    'line_cuts': 'removed side = +normal; validated 8.07 / 8.53 / 8.85 / 9.08 (fittings.py LINECUT_TYPE)',
}


def md5(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def decode(kit_dir, script, db1, wd, eng, env, log):
    os.makedirs(wd, exist_ok=True)
    layouts = json.load(open(os.path.join(kit_dir, 'layouts.json')))
    lp = os.path.join(wd, 'layout.json'); json.dump(layouts[eng].get('layout'), open(lp, 'w'))
    vp = os.path.join(wd, 'variants.json'); json.dump([v['layout'] for v in layouts.values() if v.get('layout')], open(vp, 'w'))
    indb = os.path.join(wd, 'in.db1')
    if not os.path.exists(indb):
        os.link(db1, indb)
    ifc = os.path.join(wd, 'model.ifc'); stats = os.path.join(wd, 'convert.json')
    tmp = os.path.join(wd, 'tmp'); os.makedirs(tmp, exist_ok=True)
    env = dict(env, TMPDIR=tmp, TMP=tmp, TEMP=tmp)
    cmd = [R.PY84, os.path.join(kit_dir, script), indb, ifc, os.path.join(kit_dir, 'tekla_profiles.json'), lp, stats, vp]
    rc, sec = R.run(cmd, log, R.DEC_TIMEOUT, env, wd)
    cs = json.load(open(stats)) if os.path.exists(stats) else {}
    if rc == 0 and cs.get('status') == 'deferred_layout':
        rc, sec2 = R.run(cmd, log, R.DEC_TIMEOUT, dict(env, DB1_FULL_DISCOVERY='1'), wd); sec += sec2
        cs = json.load(open(stats)) if os.path.exists(stats) else {}
    pl = json.load(gzip.open(stats + '.parts.json.gz', 'rt')) if os.path.exists(stats + '.parts.json.gz') else None
    rs = json.load(open(stats + '.restore.json')) if os.path.exists(stats + '.restore.json') else None
    return dict(rc=rc, sec=sec, stats=cs, parts=pl, restore=rs, ifc=ifc)


def rec_gid(parts):
    """parts list -> {record: gid} of written products (first occurrence)"""
    out = {}
    for p in parts or []:
        if p[3] == 'written' and p[5] and p[0] not in out:
            out[p[0]] = p[5]
    return out


def header_time(ifc):
    head = open(ifc, 'rb').read(4096)
    m = re.search(rb"FILE_NAME\('(?:[^']|'')*','([^']*)'", head)
    return m.group(1).decode() if m else None


def main():
    job = json.load(open(sys.argv[1])); wd = sys.argv[2]; out = sys.argv[3]
    os.makedirs(wd, exist_ok=True); os.makedirs(out, exist_ok=True)
    log = os.path.join(out, 'complete_db1.log')
    mid = job['model_id']; db1 = job['db1']; orig_ifc = job['orig_ifc']
    t0 = time.time()
    res = {'schema': 'pmp.complete.db1.restoration_log/1', 'model_id': mid, 'tag': job.get('tag'), 'track': 'db1 (GREEN restoration)'}
    if R.sha256(db1) != mid:
        res['verdict'] = 'fail'; res['reason'] = 'db1 sha256 != model id'
        json.dump(res, open(os.path.join(out, 'restoration_log.json'), 'w'), indent=1); return
    eng = R.engine_of(db1); res['engine'] = eng
    env = R.profile_env(PROFILE); env.pop('PYTHONPATH', None)
    res['cpu_profile'] = {'name': PROFILE, 'env': R.PROFILES[PROFILE]['env']}
    kg = json.load(open(os.path.join(KIT_V, 'KIT.json')))
    res['kit'] = {'base': 'kit_v ' + kg['code'], 'kit_g_files_md5': {fn: md5(os.path.join(KIT_G, fn)) for fn in sorted(os.listdir(KIT_G))
                                                                   if fn.endswith(('.py', '.json')) and fn != 'KIT.json'},
                  'kit_g_changed_vs_kit_v': sorted(fn for fn, m in kg['files'].items() if md5(os.path.join(KIT_G, fn)) != m) + ['convert_complete.py (new)']}
    # 1. control decode with kit_v
    base = decode(KIT_V, 'convert_one.py', db1, os.path.join(wd, 'base'), eng, env, log)
    # 2. completion decode with kit_g
    comp = decode(KIT_G, 'convert_complete.py', db1, os.path.join(wd, 'comp'), eng, env, log)
    res['decode'] = {k: {'rc': d['rc'], 'sec': d['sec'], 'status': d['stats'].get('status'), 'written': d['stats'].get('written'),
                         'sources': d['stats'].get('sources'), 'skipped': d['stats'].get('skipped'),
                         'bolt_stats_slots': {kk: (d['stats'].get('bolt_stats') or {}).get(kk) for kk in
                                              ('slotted_holes_cut', 'slot_groups', 'v2_slots_on', 'slots_rotated', 'slotted_bolts_cut_round',
                                               'slotted_groups_cut_round', 'slot_rule', 'holes_in_slotted_groups_cut_round', 'holes_cut')},
                         'fittings': d['stats'].get('fittings')} for k, d in (('kit_v_control', base), ('kit_g_completion', comp))}
    if base['rc'] != 0 or comp['rc'] != 0 or base['stats'].get('status') != 'ok' or comp['stats'].get('status') != 'ok':
        res['verdict'] = 'fail'; res['reason'] = 'decode failed'; res['trace'] = [base['stats'].get('trace'), comp['stats'].get('trace')]
        json.dump(res, open(os.path.join(out, 'restoration_log.json'), 'w'), indent=1, default=str); return
    sk = json.load(open(job['skipped_records']))
    orig_parts = sk['parts']                      # [record, profile, category, status, how, gid, in_shipped_step, n_cuts]
    og = rec_gid(orig_parts)
    # control: kit_v decode == delivered source IFC (geometry per product, through records)
    H0 = ifc_canon.hashes(orig_ifc)
    Hb = ifc_canon.hashes(base['ifc'])
    bg = rec_gid(base['parts'])
    ctl = {'products_source_ifc': len(H0), 'products_control': len(Hb), 'records': len(og), 'equal': 0, 'differ': [], 'unmatched': []}
    for r, g in og.items():
        gb = bg.get(r)
        if gb is None or gb not in Hb or g not in H0:
            ctl['unmatched'].append(r); continue
        if Hb[gb]['geom'] == H0[g]['geom'] and Hb[gb]['name'] == H0[g]['name']:
            ctl['equal'] += 1
        else:
            ctl['differ'].append(r)
    ctl['identical'] = not ctl['differ'] and not ctl['unmatched'] and ctl['equal'] == len(og) == len(H0)
    res['control_kit_v_vs_source_ifc'] = ctl
    # 3. GlobalIds + times
    cg = rec_gid(comp['parts'])
    gmap = {}
    new_records = []
    for r, g in cg.items():
        if r in og:
            gmap[g] = og[r]
        else:
            new_records.append(r)
    stamp = header_time(orig_ifc)
    tmp1 = os.path.join(wd, 'comp_restored.ifc')
    rst = R.restore(mid, comp['ifc'], tmp1, gmap)
    final = os.path.join(out, 'model_completed.ifc')
    nt = R.normalise_times(tmp1, final, stamp)
    res['guid_restore'] = {k: rst[k] for k in ('ifcroot_entities', 'product_guids_restored', 'other_guids_derived', 'map_entries_not_found_in_ifc')}
    res['time_normalisation'] = nt
    res['completed_ifc'] = {'bytes': os.path.getsize(final), 'sha256': R.sha256(final)}
    # 4. comparison completed vs source
    Hc = ifc_canon.hashes(final)
    ev = (comp['restore'] or {}).get('parts') or {}
    groups = (comp['restore'] or {}).get('groups') or {}
    res['completion_env'] = (comp['restore'] or {}).get('env')
    rec_of = {g: r for r, g in og.items()}
    prof_of = {p[0]: p[1] for p in orig_parts}
    cmpres = {'unchanged': 0, 'restored': [], 'unexpected_change': [], 'event_but_unchanged': [], 'missing_in_completed': [], 'new_in_completed': new_records,
              'renamed_only': []}
    parts_out = {}
    for g, h in H0.items():
        r = rec_of.get(g)
        evs = ev.get(str(r), []) if r is not None else []
        geo_evs = [e for e in evs if e.get('kind') in GEOM_KINDS]
        if g not in Hc:
            cmpres['missing_in_completed'].append(g); continue
        same = Hc[g]['geom'] == h['geom']
        if same:
            cmpres['unchanged'] += 1
            if Hc[g]['name'] != h['name']:
                cmpres['renamed_only'].append(g)
            if geo_evs:
                cmpres['event_but_unchanged'].append(g)
            if evs or Hc[g]['name'] != h['name']:
                parts_out[g] = {'record': r, 'profile': prof_of.get(r), 'class': h['cls'], 'geometry': 'unchanged',
                                'name_source': h['name'], 'name_completed': Hc[g]['name'], 'events': evs}
            continue
        if geo_evs:
            cmpres['restored'].append(g)
            parts_out[g] = {'record': r, 'profile': prof_of.get(r), 'class': h['cls'], 'geometry': 'restored',
                            'name_source': h['name'], 'name_completed': Hc[g]['name'], 'events': evs}
        else:
            cmpres['unexpected_change'].append(g)
            parts_out[g] = {'record': r, 'profile': prof_of.get(r), 'class': h['cls'], 'geometry': 'CHANGED_WITHOUT_EVENT',
                            'name_source': h['name'], 'name_completed': Hc[g]['name'], 'events': evs}
    res['comparison_completed_vs_source_ifc'] = {k: (v if not isinstance(v, list) else {'n': len(v), 'items': v[:400]}) for k, v in cmpres.items()}
    res['untouched_parts_geometrically_identical'] = (not cmpres['unexpected_change'] and not cmpres['missing_in_completed'])
    # bolt-group slot decisions: which plies (records -> gids)
    gout = {}
    for k, v in groups.items():
        v = dict(v)
        for key in ('plies_head_first', 'slotted'):
            if v.get(key) is not None:
                v[key + '_gid'] = [og.get(p) for p in v[key]]
        bg_gid = og.get(int(k)) if k.lstrip('-').isdigit() else None
        v['bolt_group_gid'] = bg_gid
        gout[k] = v
    res['slot_groups'] = gout
    # 5. STEP
    if job.get('do_step'):
        stp = os.path.join(out, 'completed.stp')
        rc, sec = R.run([R.PY84, os.path.join(KIT_V, 'ifc2step6.py'), final, stp, '--mode', 'hybrid', '--prec', '2', '--threads', '4'],
                        log, R.STEP_TIMEOUT, env, wd)
        res['step'] = {'rc': rc, 'sec': sec, 'bytes': os.path.getsize(stp) if os.path.exists(stp) else None}
        pj = stp + '.parts.json'
        try:
            _step_volume_check(res, parts_out, pj, job)
        except Exception as ex_:
            res['step_volume_check'] = {'error': f'{type(ex_).__name__}: {str(ex_)[:300]}'}
    res['parts'] = parts_out
    res['verdict'] = 'ok' if (res['untouched_parts_geometrically_identical'] and ctl['identical']) else 'check'
    res['seconds'] = round(time.time() - t0, 1)
    json.dump(res, open(os.path.join(out, 'restoration_log.json'), 'w'), indent=1, default=str)
    print(json.dumps({k: res.get(k) for k in ('verdict', 'seconds', 'engine')}))


def _step_volume_check(res, parts_out, pj, job):
    if True:
        if os.path.exists(pj) and job.get('orig_step_parts') and os.path.exists(job['orig_step_parts']):
            def _lj(p_):
                raw_ = open(p_, 'rb').read()
                return json.loads(gzip.decompress(raw_) if raw_[:2] == b'\x1f\x8b' else raw_)
            P1 = {p['gid']: p for p in _lj(pj)['parts']}
            P0 = {p['gid']: p for p in _lj(job['orig_step_parts'])['parts']}
            vc = {'parts_completed_step': len(P1), 'parts_shipped_step': len(P0), 'unchanged_volume_equal': 0, 'unchanged_volume_differs': [],
                  'missing_in_completed_step': sorted(set(P0) - set(P1))}
            for g, p0 in P0.items():
                p1 = P1.get(g)
                if p1 is None: continue
                v0, v1 = p0.get('volume_mm3'), p1.get('volume_mm3')
                if g in parts_out and parts_out[g]['geometry'] == 'restored':
                    parts_out[g].update(volume_shipped_mm3=v0, volume_completed_mm3=v1,
                                        volume_change_pct=(round(100.0 * (v1 - v0) / v0, 4) if v0 and v1 is not None else None),
                                        step_solids=p1.get('solids'), step_src=p1.get('src'), step_exact=p1.get('exact'), step_why=p1.get('why'))
                else:
                    if v0 == v1: vc['unchanged_volume_equal'] += 1
                    else: vc['unchanged_volume_differs'].append([g, v0, v1])
            res['step_volume_check'] = vc


if __name__ == '__main__':
    main()
