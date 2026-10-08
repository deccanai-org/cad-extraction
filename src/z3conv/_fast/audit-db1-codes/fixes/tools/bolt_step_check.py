"""bolt_step_check.py [KIT] [VER]: bolt solids end to end, per model: flags (audit) -> expected solids per bolt group -> decoder IFC
(IfcMechanicalFastener items) -> deployed STEP (same code: .i / .h) products + solids + validity. out: report/bolt_step_<VER>.json"""
import json, os, sys, gzip, glob, collections, subprocess
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
KIT = sys.argv[1] if len(sys.argv) > 1 else 'i_audit'; VER = sys.argv[2] if len(sys.argv) > 2 else '.i'
PY84 = '/opt/conv/ifc84/bin/python'
T = collections.Counter(); per = {}; EX = collections.defaultdict(list)
for ap in sorted(glob.glob(f'dec/{KIT}/*.audit.json')):
    i = os.path.basename(ap)[:-11]
    sp = f'det/{i}{VER}.step_parts.jsonl.gz'
    A = json.load(open(ap))
    exp_g = collections.Counter()
    for b in A['bolts']:
        if b['holes_only']: continue
        if b.get('head_up'):
            nn = max(1, b.get('nuts') or 1) if b.get('nuts', 1) else 0
            exp_g[b['gid']] += 2 + (1 if b.get('wash_head') else 0) + (b.get('wash_nut') or 0) + (b.get('wash_2') or 0) + nn
        else:
            exp_g[b['gid']] += 3
    q = subprocess.run([PY84, '-c', f'''
import ifcopenshell, json
f = ifcopenshell.open("dec/{KIT}/{i}.ifc")
print(json.dumps([[e.Name, len(e.Representation.Representations[0].Items)] for e in f.by_type("IfcMechanicalFastener")]))'''], capture_output=True, text=True, timeout=3600)
    try:
        ifc = json.loads(q.stdout.strip().splitlines()[-1])
    except Exception:
        ifc = None
    r = {'groups_expected': len(exp_g), 'solids_expected': sum(exp_g.values())}
    if ifc is not None:
        # parametric studs / anchors are IfcMechanicalFastener too: bolt groups are the MM-named ones
        ib = [x for x in ifc if (x[0] or '').startswith('MM')]
        r['ifc_groups'] = len(ib); r['ifc_solids'] = sum(x[1] for x in ib)
        r['ifc_vs_flags_equal'] = sorted(exp_g.values()) == sorted(x[1] for x in ib)
    if os.path.exists(sp) and ifc is not None:
        S = [json.loads(l) for l in gzip.open(sp, 'rt')]
        sb = [x for x in S if x.get('desc') == 'IfcMechanicalFastener' and (x.get('name') or '').startswith('MM')]
        r['step_groups'] = len(sb); r['step_solids'] = sum(x.get('solids') or 0 for x in sb); r['step_valid'] = sum(x.get('valid') or 0 for x in sb)
        bn = collections.defaultdict(list); sn = collections.defaultdict(list)
        for x in ib: bn[(x[0] or '')[:120]].append(x[1])
        for x in sb: sn[(x.get('name') or '')[:120]].append(x.get('solids') or 0)
        diff = [(k, sorted(bn[k]), sorted(sn.get(k, []))) for k in bn if sorted(bn[k]) != sorted(sn.get(k, []))]
        r['names_solids_mismatch'] = len(diff)
        for d in diff[:3]: EX['ifc_step_mismatch'].append({'id': i[:12], 'name': d[0][:80], 'ifc': d[1][:10], 'step': d[2][:10]})
        T['step_models'] += 1; T['step_groups'] += r['step_groups']; T['step_solids'] += r['step_solids']; T['step_valid'] += r['step_valid']
        T['step_models_exact'] += 1 if (r['step_groups'] == r['ifc_groups'] and r['step_solids'] == r['ifc_solids'] and not diff) else 0
    T['models'] += 1; T['groups_expected'] += r['groups_expected']; T['solids_expected'] += r['solids_expected']
    T['ifc_groups'] += r.get('ifc_groups') or 0; T['ifc_solids'] += r.get('ifc_solids') or 0; T['ifc_models_equal'] += 1 if r.get('ifc_vs_flags_equal') else 0
    per[i] = r
json.dump({'kit': KIT, 'ver': VER, 'totals': dict(T), 'per_model': per, 'examples': EX}, open(f'report/bolt_step{VER}.json', 'w'), indent=1)
print(json.dumps(dict(T), indent=1))
