T=/opt/conv/scratch_cutr
cat > $T/cmp.py <<'PY'
import json, glob, os
T='/opt/conv/scratch_cutr/out'
def g(d, *ks):
    for k in ks:
        d = (d or {}).get(k) if isinstance(d, dict) else None
    return d
for idd in sorted(os.listdir(T)):
    row = {}
    for v in ('o', 'r'):
        p = f'{T}/{idd}/{v}/convert.json'
        if not os.path.exists(p): row[v] = None; continue
        st = json.load(open(p))
        bs = st.get('bolt_stats') or {}
        row[v] = dict(status=st.get('status'), written=st.get('written'), cuts=st.get('cuts_applied'),
                      cut_stats={k: x for k, x in (st.get('cut_stats') or {}).items() if isinstance(x, (int, float))},
                      fit={k: x for k, x in (st.get('fittings') or {}).items() if isinstance(x, (int, float))},
                      holes=bs.get('holes_cut') or bs.get('holes'), slots=bs.get('slotted_holes_cut'), slot_groups=bs.get('slot_groups'),
                      rect=g(st, 'audit_patch_stats', 'rect_plates_thin_side_to_z'),
                      skipped=st.get('skipped'), secs=st.get('decode_sec') or st.get('secs'),
                      audit={k: x for k, x in (st.get('audit_patch_stats') or {}).items() if k in ('holes_merged','coaxial_holes_apart_cut_separately','p4_list_fallback_geometric','holes_not_bolted_dropped')},
                      sl_round=bs.get('slotted_bolts_cut_round'), v2slots=bs.get('v2_slots_on'), env=bs.get('tekla_env_catalog'), mcat=bs.get('model_catalog_bolts'), nominal=bs.get('nominal_head_nut_written'))
    print('==', idd)
    for v in ('o', 'r'): print(' ', v, json.dumps(row[v], default=str)[:1200])
PY
/opt/conv/ifc84/bin/python $T/cmp.py
