"""tekla_profiles_overlay.json: {global: {designation: entry}, per_model: {sha256: {designation: entry}}, meta}
global = MoldTek profdb.bin entries defined identically by every MoldTek copy (27 files) - angles with r1/r2, R.B Ø<d>;
per_model = D<d>/ROD<d> vessel rounds proven per model (own report weight / diameter continuity / stacked run / env grammar)
and any own-profdb value that differs from global (none found). Lift counts from the data-3 decoded parts lists."""
import json, gzip, glob, os, re, sys, collections
sys.path.insert(0, '.')
import profdb
F = json.load(open('folders.json')); E = json.load(open('catalog_evidence.json'))
J = {j['sha256']: j for j in json.load(open('../work/d3jobs.json'))}
mold = {sha for sha, v in F.items() if 'MOLDTEK' in v['dir'].upper()}
files = sorted(p for p in glob.glob('mf/*/profdb.bin') if any(s.startswith(os.path.basename(os.path.dirname(p))) for s in mold))
vals = collections.defaultdict(list); srcs = collections.defaultdict(set)
for p in files:
    for n, e in profdb.model_catalog(profdb.load(p)).items():
        vals[n].append(json.dumps([e['kind'], e['dims']])); srcs[n].add(e['src'].split(':')[0])
glob_ = {}
for n, v in vals.items():
    if len(set(v)) == 1 and len(v) >= 0.9 * len(files):           # every copy that defines it agrees (26/27 for L150*90*9)
        k, dims = json.loads(v[0])
        glob_[n] = dict(kind=k, dims=dims, n=len(v), src=f'MoldTek model-folder profdb.bin, identical in all {len(v)} of {len(files)} copies that define it ({sorted(srcs[n])[0]})')
per = {}; tierc = {}
mc = json.load(open('model_catalogs.json'))
for sha, ents in mc.items():
    for n, e in ents.items():
        g = glob_.get(n)
        if g and json.dumps([g['kind'], g['dims']]) == json.dumps([e['kind'], e['dims']]): continue
        if e.get('tier') == 'C':
            tierc.setdefault(sha, {})[n] = dict(kind=e['kind'], dims=e['dims'], n=1, tier='C', src=e['src']); continue
        per.setdefault(sha, {})[n] = dict(kind=e['kind'], dims=e['dims'], n=1, tier=e.get('tier'), src=e['src'])
# ------------------------------------------------ lift counts (data-3 decoded parts; names after the latin-1 fix from the evidence run)
APPROX = {'parametric_angle', 'parametric_angle_equal'}
fix = collections.defaultdict(lambda: [0, set()])
remaining = collections.defaultdict(lambda: [0, set()])
model_rows = []
for f in sorted(glob.glob('detail/*.decoded_parts.json.gz')):
    sha = os.path.basename(f).split('.')[0]; ev = E.get(sha, {})
    pl = json.load(gzip.open(f, 'rt'))
    avail = set(glob_) | set(per.get(sha, {}))
    names_needed = set(ev.get('need') or [])
    rb_names = [n for n in names_needed if n.startswith('R.B')]
    left_prof = 0; left_ang = 0
    for seq, prof, cat, st, how, guid, nc in pl:
        p = prof or ''
        if how in APPROX:
            if p in avail: fix['angle_root_radius'][0] += 1; fix['angle_root_radius'][1].add(sha)
            else: left_ang += 1; remaining['angle_root_radius'][0] += 1; remaining['angle_root_radius'][1].add(sha)
        elif st == 'skipped' and how == 'profile_without_size' and p.startswith('R.B'):
            if rb_names and all(n in avail for n in rb_names): fix['R.B_name_latin1+profdb'][0] += 1; fix['R.B_name_latin1+profdb'][1].add(sha)
            else: left_prof += 1; remaining['R.B'][0] += 1; remaining['R.B'][1].add(sha)
        elif st == 'skipped' and how in ('unresolved', 'implausible_profile'):
            if re.match(r'^(ELD|EPD)', p): fix['ELD/EPD_tapered_parser'][0] += 1; fix['ELD/EPD_tapered_parser'][1].add(sha)
            elif p in avail: fix['D/ROD_vessel_round'][0] += 1; fix['D/ROD_vessel_round'][1].add(sha)
            elif p.startswith('/') or p in ('5', '0*5955'): fix['null_record_not_a_part'][0] += 1; fix['null_record_not_a_part'][1].add(sha)
            elif p in tierc.get(sha, {}): left_prof += 1; remaining['D_tier_C_not_applied'][0] += 1; remaining['D_tier_C_not_applied'][1].add(sha)
            else: left_prof += 1; remaining[p][0] += 1; remaining[p][1].add(sha)
    model_rows.append((sha, left_prof, left_ang))
profile_clean = [s for s, a, b in model_rows if a == 0 and b == 0]
meta = dict(updated=__import__('time').strftime('%Y-%m-%dT%H:%M:%SZ', __import__('time').gmtime()),
            consume='global entries: cat.update(global) before convert; per_model: cat.update(per_model.get(sha256 of the DB1, {})). '
                    "R.B names need the db1old.cstr Latin-1 fix (old reader cut 'R.B \\xd820' to 'R.B '); ELD/EPD need db1prof.parse_tapered + frustum writer "
                    '(apply_prof_patch.py); null records need db1prof.is_null_record in convert_old.',
            lift={k: {'parts': v[0], 'models': len(v[1])} for k, v in fix.items()},
            remaining={k: {'parts': v[0], 'models': len(v[1])} for k, v in remaining.items()},
            models_profile_clean_after=len(profile_clean), models_total=len(model_rows),
            tiers={'global': 'MoldTek model-folder profdb.bin values identical in every copy that defines them', 'P': 'own model-folder profdb.bin', 'A': 'own (or same-model) Tekla report weight = solid round, or exact diameter continuity with an adjacent tapered part', 'B': 'stacked run of D/ROD rounds on one axis (vessel shell); D/ROD = solid round per the environment reports', 'C (not applied)': 'environment-verified D<d> grammar only'},
            note='class 1 additionally needs the bolt groups (all 52 graded data-3 DB1 models carry pieces_without_bolt_holes)')
json.dump(dict(meta=meta, **{'global': glob_}, per_model=per, not_applied_tier_c=tierc), open('tekla_profiles_overlay.json', 'w'), indent=1, ensure_ascii=False)
print(json.dumps(meta, indent=1, ensure_ascii=False)); print('global', len(glob_), 'per_model models', len(per), 'entries', sum(len(v) for v in per.values()))
