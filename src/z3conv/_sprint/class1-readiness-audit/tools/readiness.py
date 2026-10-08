"""readiness.py CURRENT_INDEX_GZ FINAL_PROJ OUT_JSON : per-tag readiness table for every graded DB1 model: decision (a source limit /
b converter gap with data present / c bookkeeping bug), models carrying the tag now (index) and after the fixes (projection), models whose
ONLY remaining blocker is that tag, and the fix that addresses it."""
import json, gzip, sys, collections
sys.path.insert(0, __file__.rsplit('/', 1)[0])
cur = [json.loads(l) for l in gzip.open(sys.argv[1]) if json.loads(l)['pipeline'] == 'db1']
P = json.load(open(sys.argv[2]))
import lift
D = {
 'bolt_nominal_head_nut': ('c+b+a', 'c: holes-only bolts counted (13,915 bolts / 56 models, kit k); v2 path counted every bolt (e.g. 0f3629014894: 37,997); catalog entries '
     "'ambiguous' on thread length -> no catalog head + KeyError crash (3 models). b: own screwdb+assdb never built into the catalog "
     '(14 -> 35 models own, +31 assdb-only via environment consensus). a: assembly / size absent from the own catalog (e.g. HEX B/N d16, SA325-1 rows 20/22/27 only), '
     'standards with no published table (316L S.S, LAG SCREW, NELSON studs, HILTI anchors)', 'apply_c1_patch + apply_c1_stats + apply_bi_c1 + bolt_catalog.c1_*'),
 'hole_clearance_nominal': ('c+b', 'b: tolerance field 0 / negative / >10 discarded (hole-tolerance-residue patch: 0 nominal holes left on old engines); '
     'c: v2 results counted holes_cut as nominal (all decoded)', 'htr patch + apply_bi_c1 (holes_cut - holes_tolerance_decoded) + kit m/c1 stats'),
 'washer_nominal': ('b+a', 'ASTM F436 thickness range (kit k: table+tekla_washer exact); catalog washer3 != washer1 (HSFG: LI t3/OD37 vs FLAT-HSFG t3.7/OD44) - '
     'which catalog slot Tekla draws on the nut side is unproven -> stays nominal; FLAT-E d27 absent from own screwdb (a)', 'catalog slot proof needed (Tekla IFC of a MoldTek HSFG model)'),
 'washer_side_inferred': ('a/b', 'flag digit d3 (washer 2): side unproven (washer_side_proof: 4/4 groups mismatch)', 'needs a GUID-joined Tekla IFC with d3 groups'),
 'bolt_axial_position_fitted': ('a', 'old engines: f6/f10 grip fields absent on these groups -> fitted to plies; v2: grip centre differs from plies', 'none (source)'),
 'bolt_axial_position_unknown': ('c (new stand-in)', 'centred shank, no ply on the axis: was name-tag only (and the tag was cut off at 120 chars in the STEP)', 'apply_c1_stats + apply_bi_c1'),
 'hole_slotted_cut_round': ('c (new stand-in) + b', 'slot x/y stored but the slotted-plies selection is not decoded: holes cut round, untagged in kit k '
     '(98,993 bolts / 83 models). Tekla NC of 5a2284473e4e: 523 slotted 18 mm BO holes in 150 parts with slot lengths 17/22/57 = the DB1 fields; '
     '6b87b724b554 / 6eabb07e7145: slot fields but no slotted NC hole -> selection varies. Not in the bolt string (fieldscan) nor a byte of the '
     'attribute record (maskscan)', 'decode the slotted-parts selection (top lever)'),
 'approx_tagged_products': ('c', "old-engine groups always named '[approx: ]' (exact ones too); ifc2step6 cuts PRODUCT names at 120 chars so long names lost the marker",
     'apply_c1_stats (_c1_name)'),
 'section_parametric_*': ('b+a', 'angle r1/r2, RHS radii, UPN alias, panel orientation, HSS radii: own profdb defines only R.B 20 in 5 Lego models '
     '(240 parts, overlay_own_profdb.json; kit m adds the same 5); Bruning L/U/SHS names absent from their own profdb; panel AxB orientation (a)', 'overlay_own_profdb.json'),
 'profile catalog entries / coverage<1': ('b+a', 'tier-C vessel rounds D<d>, bare numeric names (31.75), GRATING TREAD, washers/studs modelled as parts', 'profile stream'),
 'step_stage (L4 / parts_without_solid / invalid)': ('b', 'ifc2step6 stage', 'IFC/STEP stream'),
 'cuts_not_applied': ('b', 'cut bodies unbuilt', 'cut-not-applied stream'),
 'pieces_without_bolt_holes / bolt decoding': ('b', '7.30 bolt groups not enabled (BOLT_ENGINES 6.87/7.01/7.24), unplaced v2 groups', 'decoder'),
 'reverse: ASTM tables vs own assdb': ('c', "7,273 bolts / 32 models drawn with ASTM inch tables (and counted exact) although the model's own assdb.db maps "
     "'A307'/'A325'/'A325N' to metric 8.8XOX / F10T / HSFG-XOX (19/19 screwdb copies agree: 8.8XOX M16 k10 s24, GR8-HEX m13)", 'apply_c1_patch fallback_geometry'),
 'reverse: non-hex catalog heads': ('c', 'TSF10T cup heads drawn hex, counted exact (15 bolts, 39a8f23724f8)', 'apply_c1_patch (types)'),
}
now = collections.Counter(); after = collections.Counter(); only = collections.Counter()
for r in cur:
    if r['class'] == 1: continue
    for s in r['standins']: now[s['type'] if not s['type'].startswith('section_') else 'section_parametric_*'] += 1
for k, v in P.items():
    if v.get('projected') != 2: continue
    ts = set(t if not t.startswith('section_') else 'section_parametric_*' for t in v['standins'])
    for t in ts: after[t] += 1
    fam = lift.fam(v)
    if len(fam) == 1: only[next(iter(fam))] += 1
json.dump({'tags': {t: {'decision': d[0], 'evidence': d[1], 'fix': d[2], 'models_now': now.get(t), 'models_after_fixes': after.get(t)} for t, d in D.items()},
           'single_blocker_families_after_fixes': dict(only)}, open(sys.argv[3], 'w'), indent=1)
print(json.dumps(dict(only)), dict(now.most_common(12)), dict(after.most_common(12)))
