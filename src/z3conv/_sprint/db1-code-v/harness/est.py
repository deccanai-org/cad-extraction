import gzip, json, collections, sys
PANEL_ENG = set(sys.argv[1].split(','))          # A*B exact engines
SLOT_FRAC = json.loads(sys.argv[2])               # engine -> share of tagged models expected to lose hole_slotted_cut_round
rows = [json.loads(l) for l in gzip.open('index.jsonl.gz')]
d = [r for r in rows if r.get('pipeline') == 'db1' and r.get('class') == 2]
T3 = {'section_parametric_panel', 'hole_slotted_cut_round', 'section_parametric_stud_shank'}
lose = collections.Counter(); c1 = collections.Counter(); byeng = collections.defaultdict(collections.Counter)
for r in d:
    ts = {s['type'] for s in r.get('standins', [])}; e = r.get('engine')
    blockers = (ts - T3) | {'ISS:' + i for i in r.get('issues', [])} | {'NEED:' + n for n in r.get('needs', [])}
    p_panel = 1.0 if e in PANEL_ENG else 0.0106      # square-only share outside the A*B engines (6 / 567 sample)
    p_slot = SLOT_FRAC.get(e, 0.0)
    if 'section_parametric_panel' in ts: lose['panel'] += p_panel; byeng['panel'][e] += p_panel
    if 'hole_slotted_cut_round' in ts: lose['slot'] += p_slot; byeng['slot'][e] += p_slot
    if not blockers and ts & T3 and 'section_parametric_stud_shank' not in ts:
        p = (p_panel if 'section_parametric_panel' in ts else 1) * (p_slot if 'hole_slotted_cut_round' in ts else 1)
        c1['to_class1'] += p
print({k: round(v) for k, v in lose.items()}, {k: round(v) for k, v in c1.items()})
for k, v in byeng.items(): print(k, {e: round(n) for e, n in sorted(v.items(), key=lambda kv: -kv[1]) if n >= 1})
