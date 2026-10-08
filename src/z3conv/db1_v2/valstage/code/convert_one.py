"""convert_one.py DB1 OUT_IFC CATALOG LAYOUT_JSON STATS_JSON  (runs in the conda env)"""
import sys, json, os, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db1step import convert
db1, out_ifc, catp, layp, statp = sys.argv[1:6]
varp = sys.argv[6] if len(sys.argv) > 6 else None
try:
    lay = json.load(open(layp)) if os.path.exists(layp) else None
    variants = json.load(open(varp)) if varp and os.path.exists(varp) else []
    import hashlib as _hl
    os.environ['DB1_SHA256'] = _hl.sha256(open(db1, 'rb').read()).hexdigest()     # per-model catalogs (profiles overlay, bolt catalog)
    cat = json.load(open(catp))
    try:  # db1prof-patch: exact profiles from the models' own catalogs (tekla_profiles_overlay.json: global + per DB1 sha256)
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
    import gzip
    with gzip.open(statp + '.parts.json.gz', 'wt') as g:
        json.dump(pl, g)
    st['parts_list_n'] = len(pl)
json.dump(st, open(statp, 'w'), default=str)
sys.exit(0)
