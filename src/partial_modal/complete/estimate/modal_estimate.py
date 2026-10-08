"""Modal geometry check of the estimate track's patches (app pmp-estimate; our own app, nothing else in the workspace is
touched). Per sample, in parallel: merge ONLY the estimate patch into the baseline schedules with the integration's own
completion_core.merge, build every part the patch changes with the baseline's shipped steelbuild.py (the same builder
build_model.py uses), and check each solid (valid BRep, closed, positive volume), the op's target volume, the bbox, and for
modified parts the volume change against the baseline build. n3 (no baseline tree): the faceted GEOMs are built directly
with steelbuild.exact_part. Writes complete/estimate/out/<tag>/geometry_check.json locally.

    .venv/bin/modal run complete/estimate/modal_estimate.py [--only n1_db1_small,...]
"""
import json
import os
import pathlib

import modal

HERE = pathlib.Path(__file__).resolve().parent
COMPLETE = HERE.parent
ROOT = COMPLETE.parent
TAGS = {'n1_db1_small': ('n1', '51_Westwood_PETCT_Master'), 'n2_db1_addon': ('n2', 'F232-MASTER-d6c7cd'),
        'n3_ifc_approx': ('n3', None), 'n4_ifc_c2s': ('n4', 'GRID3'), 'n5_sds2': ('n5', 'BACKUP_DATA_ROOM_1021')}


def _ignore(p):
    s = str(p)
    return any(x in s for x in ('/source/', '/issues/', '__pycache__', '.step', '.stp', '.ifc'))


img = (modal.Image.debian_slim(python_version='3.11')
       .apt_install('libgl1', 'libxrender1', 'libxext6', 'libsm6', 'libfontconfig1', 'libxkbcommon0', 'libxi6')
       .env({'PYTHONUNBUFFERED': '1', 'OMP_NUM_THREADS': '1'})
       .pip_install_from_requirements(str(ROOT / 'code' / 'requirements.txt'))
       .add_local_file(str(COMPLETE / 'integrate' / 'completion_core.py'), '/est/integrate/completion_core.py')
       .add_local_dir(str(HERE / 'out'), '/est/out', ignore=lambda p: not str(p).endswith('patch.json')))
for tag, (short, folder) in TAGS.items():
    if folder:
        img = img.add_local_dir(str(ROOT / 'testB_results' / short / 'scripts' / folder), f'/est/trees/{tag}/{folder}',
                                ignore=_ignore)
        img = img.add_local_file(str(ROOT / 'testB_results' / short / 'scripts' / 'steelbuild.py'), f'/est/trees/{tag}/steelbuild.py')
img = img.add_local_file(str(ROOT / 'testB_results' / 'n1' / 'scripts' / 'steelbuild.py'), '/est/steelbuild_n3/steelbuild.py')

app = modal.App('pmp-estimate', image=img)


@app.function(cpu=4.0, memory=16384, timeout=3600)
def verify(tag: str, model_id: str):
    import importlib.util
    import sys
    import tempfile
    import time
    t0 = time.time()
    short, folder = TAGS[tag]
    sys.path.insert(0, '/est/integrate')
    import completion_core as cc
    patch_path = f'/est/out/{tag}/patch.json'
    patch = json.load(open(patch_path))
    sbdir = f'/est/trees/{tag}' if folder else '/est/steelbuild_n3'
    spec = importlib.util.spec_from_file_location('steelbuild', f'{sbdir}/steelbuild.py')
    sb = importlib.util.module_from_spec(spec)
    sys.modules['steelbuild'] = sb
    spec.loader.exec_module(sb)
    import hashlib
    report = {'tag': tag, 'ops': len(patch['ops']), 'parts': {}, 'problems': [],
              'ops_sha256': hashlib.sha256(json.dumps(patch['ops'], sort_keys=True).encode()).hexdigest()}
    target = {}
    for o in patch['ops']:
        pid = o.get('part_id') or (o.get('part') or {}).get('part_id') or (cc.new_part_id('estimate', o['id']) if o['op'] in ('add_part', 'marker') else None)
        if o.get('target'):
            target[pid] = o['target']

    def check(pid, solids, old=None):
        r = {'solids': len(solids), 'defects': [], 'volume_mm3': 0.0}
        lo = [1e18] * 3
        hi = [-1e18] * 3
        for s in solids:
            d = sb.solid_defects(s)
            if d:
                r['defects'].append(d)
            v = sb._volume(s.wrapped)
            if v <= 0:
                r['defects'].append('nonpositive_volume')
            r['volume_mm3'] += v
            bb = s.bounding_box()
            lo = [min(lo[0], bb.min.X), min(lo[1], bb.min.Y), min(lo[2], bb.min.Z)]
            hi = [max(hi[0], bb.max.X), max(hi[1], bb.max.Y), max(hi[2], bb.max.Z)]
        r['volume_mm3'] = round(r['volume_mm3'], 2)
        r['bbox'] = [round(x, 2) for x in lo + hi] if solids else None
        if not solids:
            r['defects'].append('nothing_built')
        tg = target.get(pid)
        if tg and tg.get('volume_mm3'):
            rel = r['volume_mm3'] / tg['volume_mm3'] - 1.0
            r['target_volume_mm3'] = tg['volume_mm3']
            r['target_rel_diff'] = round(rel, 5)
            # compound items may overlap (cross bars through bearing bars): the solids' sum can only exceed the target
            r['target_ok'] = abs(rel) <= max(tg.get('tol_rel', 0.005), 0.005)
        if old is not None:
            r['baseline_volume_mm3'] = round(old, 2)
            r['volume_change_mm3'] = round(r['volume_mm3'] - old, 2)
        r['ok'] = not r['defects'] and r.get('target_ok', True)
        if not r['ok']:
            report['problems'].append({'part_id': pid, 'defects': r['defects'], 'target_rel_diff': r.get('target_rel_diff')})
        return r

    if folder:
        bt = f'/est/trees/{tag}/{folder}'
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, folder)
        comp = cc.merge(bt, [(patch_path, patch)], out, tag, model_id, log=lambda *a, **k: None)
        report['merge_counts'] = comp.get('counts')
        new = sb.Schedules(os.path.join(out, 'schedules'))
        old = sb.Schedules(os.path.join(bt, 'schedules'))
        old_by = {p['part_id']: p for p in old.parts}
        changed = [(pid, e) for pid, e in comp['parts'].items() if e.get('status') in ('replaced', 'modified', 'added')]
        for p in new.parts:
            pid = p['part_id']
            st = next((e['status'] for q, e in changed if q == pid), None)
            if not st:
                continue
            try:
                sols = sb.build_part(p, new)
            except Exception as ex:
                report['parts'][pid] = {'status': st, 'ok': False, 'defects': [f'build_error: {type(ex).__name__}: {str(ex)[:200]}']}
                report['problems'].append({'part_id': pid, 'defects': report['parts'][pid]['defects']})
                continue
            ov = None
            if st == 'modified' and pid in old_by:
                try:
                    ov = sum(sb._volume(s.wrapped) for s in sb.build_part(old_by[pid], old))
                except Exception:
                    ov = None
            r = check(pid, sols, ov)
            r['status'] = st
            report['parts'][pid] = r
    else:
        for o in patch['ops']:
            g = o['geometry']
            pid = (o.get('part') or {}).get('part_id') or o.get('part_id')
            sols = sb.exact_part({'solids': g['solids']})
            r = check(pid, sols)
            r['status'] = o['op']
            report['parts'][pid] = r
    report['n_parts_checked'] = len(report['parts'])
    report['n_ok'] = sum(1 for r in report['parts'].values() if r.get('ok'))
    report['seconds'] = round(time.time() - t0, 1)
    return report


@app.local_entrypoint()
def main(only: str = ''):
    jobs = {}
    for ln in open(ROOT / 'jobs' / 'new5.jsonl'):
        if ln.strip():
            r = json.loads(ln)
            jobs[r['tag']] = r['model_id']
    tags = [t for t in (only.split(',') if only else TAGS) if t and (HERE / 'out' / t / 'patch.json').exists()]
    for rep in verify.starmap([(t, jobs[t]) for t in tags]):
        p = HERE / 'out' / rep['tag'] / 'geometry_check.json'
        p.write_text(json.dumps(rep, indent=1) + '\n')
        lp = HERE / 'out' / rep['tag'] / 'estimate_log.json'
        lg = json.loads(lp.read_text())
        vals = list(rep['parts'].values())
        lg['geometry_check'] = {
            'how': 'Modal app pmp-estimate (complete/estimate/modal_estimate.py): the estimate patch merged alone into the baseline '
                   'schedules with the integration\'s completion_core.merge, every changed part built with the baseline\'s shipped '
                   'steelbuild.py, each solid checked (BRepCheck valid, closed, volume > 0), target volume within tolerance',
            'ops_sha256': rep['ops_sha256'], 'parts_checked': rep['n_parts_checked'], 'parts_ok': rep['n_ok'],
            'solids': sum(v.get('solids', 0) for v in vals), 'problems': rep['problems'], 'seconds': rep['seconds'],
            'file': f"complete/estimate/out/{rep['tag']}/geometry_check.json"}
        lp.write_text(json.dumps(lg, indent=1) + '\n')
        print(rep['tag'], 'checked', rep['n_parts_checked'], 'ok', rep['n_ok'], 'problems', len(rep['problems']), f"{rep['seconds']}s",
              rep.get('merge_counts'))
        for pr in rep['problems'][:8]:
            print('   ', pr)
