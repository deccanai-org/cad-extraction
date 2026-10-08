"""convert_complete.py DB1 OUT_IFC CATALOG LAYOUT_JSON STATS_JSON [VARIANTS_JSON]   (kit_g = kit_v + completion; ifc84 venv)

Completion run of the DB1 decoder: exactly convert_one.py of kit_v, with the DB1 data the shipped conversion left unused
switched on (env defaults below, each overridable), plus the restoration log the instrumented db1step.py collects:
  DB1_FITTINGS_NEW=1        new-engine (>= 7.5) Tekla fittings (relation type 9) and line cuts (type 12) applied
                            (kit_v: decoded but not applied, parts tagged 'fitting / line cut not applied')
  DB1_V2_SLOT_ENGINES       new-engine slotted holes cut from the bolt group's slot x / y + 'slotted holes in part 1..5' mask
                            (kit_v: 8.53 only); Tekla NC1 per-part agreement of the mask decode (kit_v code-v corpus study, 193
                            archives): 7.64 1246/1249, 7.82 5851/5988, 8.07 5943/6067, 8.44 1970/2019, 8.53 619/621,
                            8.85 1706/1806, 9.08 283/283
  DB1_SLOT_ENGINES          old-engine (6.87-7.30) slotted holes (kit_v: none); NC1: 6.87/7.01 374/374 + 116/116, 7.24 2370/2496,
                            7.30 546/546
Writes STATS_JSON (as convert_one) + STATS_JSON.parts.json.gz + STATS_JSON.restore.json {parts: {record: [events]},
groups: {bolt group record: slot decision}, env: the completion flags used}."""
import sys, json, os, traceback, gzip

COMPLETION_ENV = {
    'DB1_FITTINGS_NEW': '1',
    'DB1_V2_SLOT_ENGINES': '7.64,7.82,8.07,8.44,8.53,8.85,9.08',
    'DB1_SLOT_ENGINES': '6.87,7.01,7.24,7.30',
}
for k, v in COMPLETION_ENV.items():
    os.environ.setdefault(k, v)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db1step  # noqa: E402
from db1step import convert  # noqa: E402

db1, out_ifc, catp, layp, statp = sys.argv[1:6]
varp = sys.argv[6] if len(sys.argv) > 6 else None
try:
    lay = json.load(open(layp)) if os.path.exists(layp) else None
    variants = json.load(open(varp)) if varp and os.path.exists(varp) else []
    import hashlib as _hl
    os.environ['DB1_SHA256'] = _hl.sha256(open(db1, 'rb').read()).hexdigest()
    cat = json.load(open(catp))
    try:
        import hashlib
        here = os.path.dirname(os.path.abspath(__file__))
        ovp = os.path.join(here, 'tekla_profiles_overlay.json')
        if os.path.exists(ovp):
            ov = json.load(open(ovp))
            h = hashlib.sha256(open(db1, 'rb').read()).hexdigest()
            for src in (ov.get('global') or {}, (ov.get('per_model') or {}).get(h) or {}):
                cat.update({k: {'kind': v['kind'], 'dims': v['dims'], 'overlay': v.get('src')} for k, v in src.items()})
    except Exception:
        pass
    st = convert(db1, out_ifc, cat, lay or None, variants, allow_full=os.environ.get('DB1_FULL_DISCOVERY', '0') == '1')
except Exception:
    st = {'status': 'convert_error', 'trace': traceback.format_exc()[-2000:]}
pl = st.pop('parts_list', None) if isinstance(st, dict) else None
if pl is not None:
    with gzip.open(statp + '.parts.json.gz', 'wt') as g:
        json.dump(pl, g)
    st['parts_list_n'] = len(pl)
json.dump(st, open(statp, 'w'), default=str)
json.dump({'parts': {str(k): v for k, v in sorted(db1step.RESTORE.items(), key=lambda kv: str(kv[0]))},
           'groups': {str(k): v for k, v in sorted(db1step.RESTORE_GROUPS.items(), key=lambda kv: str(kv[0]))},
           'env': {k: os.environ.get(k) for k in COMPLETION_ENV}},
          open(statp + '.restore.json', 'w'), default=str, indent=0)
sys.exit(0)
