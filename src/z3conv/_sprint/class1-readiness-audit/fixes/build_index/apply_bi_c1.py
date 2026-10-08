"""apply_bi_c1.py BUILD_INDEX_PY [OUT_PY] : class1-readiness-audit bookkeeping fixes in build_index.classify_db1 (anchor-checked, idempotent).
  * bolt_nominal_head_nut counts only bolts written with a shank and no head/nut geometry: bolt_stats['nominal_head_nut_written'] when the
    kit reports it (apply_c1_stats.py); before, bolts - standard_table_geometry also counted holes-only bolts (no head / nut written at all)
  * hole_clearance_nominal: when holes_nominal_clearance is absent (DB1 code k v2 path, engines >= 7.5) it is holes_cut -
    holes_tolerance_decoded, not holes_cut (code k results counted every decoded-tolerance hole as nominal)
  * new stand-ins, never hidden: hole_slotted_cut_round (slot length stored, slotted plies not decoded, hole cut round) and
    bolt_axial_position_unknown (v2: no connected ply on the axis, shank centred on the bolt plane)
No rule is relaxed: every bolt / hole / washer that is not exact keeps a blocking stand-in."""
import sys
src = sys.argv[1]; dst = sys.argv[2] if len(sys.argv) > 2 else src
s = open(src).read()
if 'c1audit-bi' in s:
    print('already patched'); sys.exit(0)
R = [
    ("""        n_nom = bs['bolts'] - n_tab if RULES.get('bolt_standard_geometry_exact') else bs['bolts']""",
     """        n_nom = bs['bolts'] - n_tab if RULES.get('bolt_standard_geometry_exact') else bs['bolts']
        if RULES.get('bolt_standard_geometry_exact') and isinstance(bs.get('nominal_head_nut_written'), int):
            n_nom = bs['nominal_head_nut_written']          # c1audit-bi: holes-only bolts write no head / nut"""),
    ("""        n_hn = bs.get('holes_nominal_clearance', bs.get('holes_cut') or 0)""",
     """        n_hn = bs.get('holes_nominal_clearance', bs.get('holes_cut') or 0)
        if 'holes_nominal_clearance' not in bs and isinstance(bs.get('holes_tolerance_decoded'), int):
            n_hn = max(0, (bs.get('holes_cut') or 0) - bs['holes_tolerance_decoded'])     # c1audit-bi: v2 (code k) stats"""),
    ("""        if bs.get('bolts_shifted_to_plies'):
            row['standins'].append({'type': 'bolt_axial_position_fitted', 'real_type': 'bolt (axial position fitted to the connected plies)', 'count': bs['bolts_shifted_to_plies']})""",
     """        if bs.get('bolts_shifted_to_plies'):
            row['standins'].append({'type': 'bolt_axial_position_fitted', 'real_type': 'bolt (axial position fitted to the connected plies)', 'count': bs['bolts_shifted_to_plies']})
        if bs.get('bolts_axial_unknown'):                   # c1audit-bi
            row['standins'].append({'type': 'bolt_axial_position_unknown', 'real_type': 'bolt (no connected ply on its axis: shank centred on the bolt plane)', 'count': bs['bolts_axial_unknown']})
        n_sl = bs.get('slotted_bolts_cut_round') or bs.get('holes_in_slotted_groups_cut_round') or 0
        if n_sl:                                            # c1audit-bi
            row['standins'].append({'type': 'hole_slotted_cut_round', 'real_type': 'bolt hole of a slotted group cut round (slotted plies not decoded)', 'count': n_sl})"""),
]
for old, new in R:
    assert s.count(old) == 1, f'anchor missing / not unique: {old[:90]!r}'
    s = s.replace(old, new)
open(dst, 'w').write(s)
print('patched ->', dst)
