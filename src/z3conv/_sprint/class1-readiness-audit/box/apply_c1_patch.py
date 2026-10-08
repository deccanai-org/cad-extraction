"""apply_c1_patch.py KIT_DIR [CATALOG_JSON] : class1-readiness-audit fixes for the DB1 kit (anchor-checked, idempotent).
Applies on kit k (z3-db1-2026-10-01k) and on kit k + hole-tolerance-residue (its catalog_geometry ambiguity guard is subsumed).
  db1bolts.catalog_geometry(standard, d, L=None)
    * head from the size entry; when the catalog keeps per-length heads (build_cat.py by_L) the bolt's own length selects the row;
      an unresolved head returns None (never raises: code i/j/k raise KeyError 's' on {'ambiguous': n} -> 7c68f0c9874e class 3)
    * washers per slot from the assembly (washer1 = head side, washer2, washer3 = nut side; flag digits d4/d3/d2, washer_side_proof.json)
      in sg['washers'] = {'head'|'w2'|'nut': (OD, t)}; sg['washer_slots_agree'] = all used slots have the same OD/t
  db1bolts.washer_exact(b): a model-catalog washer is exact only when every slot the bolt uses is in the catalog and, if the bolt has
    washers on the nut side / washer 2, those slots carry the same OD/t as washer1 (the writer draws every washer with washer1's dims;
    which catalog slot Tekla draws on the nut side is not proven) - never claims exact for an unproven washer
  db1bolts.bolts_of: passes the bolt length to catalog_geometry
  db1step std_fn / db1bolts2.plan: pass the bolt length (v2 path, engines >= 7.5)
  CATALOG_JSON (optional): installs the rebuilt bolt_catalog.json (build_cat.py) into the kit
No other geometry changes."""
import os, sys, shutil
K = sys.argv[1]


bp = os.path.join(K, 'db1bolts.py'); s = open(bp).read()
TAG = 'c1audit-catalog'
if TAG not in s:
    i0 = s.index('def catalog_geometry(standard, d):'); i1 = s.index('\ndef bolt_fields(prof):')
    NEWCG = '''def catalog_geometry(standard, d, L=None):
    """exact head / nut / washer of the bolt assembly named in the bolt group (its standard string) from the model's own catalog
    (c1audit-catalog: per-length heads via the bolt's own L, per-slot washers, never raises on unresolved entries)"""
    a = model_catalog().get((standard or '').strip())
    if not a:
        return None
    sz = a.get('sizes') or {}
    e = sz.get(f'{float(d):.1f}') or sz.get(str(d)) or sz.get(f'{float(d):g}')
    if not e or not isinstance(e.get('bolt'), dict) or not isinstance(e.get('nut1'), dict) or not isinstance(e['nut1'].get('m'), (int, float)):
        return None
    b = e['bolt']
    if not all(isinstance(b.get(k), (int, float)) for k in ('s', 'k')):
        bl = (b.get('by_L') or {}).get(f'{float(L):g}') if L is not None else None
        if not isinstance(bl, dict) or not all(isinstance(bl.get(k), (int, float)) for k in ('s', 'k')):
            return None
        b = bl
    if (e['bolt'].get('types') or [1]) != [1]:
        return None          # cup / countersunk / torque-shear heads: the writer draws hex heads -> not exact (nominal, tagged)
    n1 = e['nut1']; w1 = e.get('washer1') if isinstance(e.get('washer1'), dict) else {}
    W = {}
    for slot, key in (('head', 'washer1'), ('w2', 'washer2'), ('nut', 'washer3')):
        w = e.get(key)
        if isinstance(w, dict) and isinstance(w.get('t'), (int, float)) and isinstance(w.get('do'), (int, float)):
            W[slot] = (float(w['do']), float(w['t']))
    return {'d': float(d), 'head_af': b['s'], 'head_h': b['k'], 'nut_af': n1.get('s', b['s']), 'nut_h': n1['m'],
            'washer_t': w1.get('t'), 'washer_od': w1.get('do'), 'washer_id': w1.get('di'), 'washers': W,
            'washer_slots_agree': len(set(W.values())) <= 1, 'hole_clearance': clearance(float(d)),
            'family': f"model catalog ({a.get('bolt_std') or '?'}, nut {a.get('nut1')}, washer {a.get('washer1')})" +
                      (f" [own assdb.db + environment screwdb consensus, {b.get('env_copies') or e['bolt'].get('env_copies')} copies]" if a.get('env') else ''),
            'catalog_scope': 'environment' if a.get('env') else 'own_folder', 'mapping': standard,
            'delta_mm': 0.0, 'source': 'model_catalog'}


def assdb_bolt_std(standard):
    # c1audit-catalog: the screw standard the model folder's OWN assdb.db assigns to this bolt assembly name (None: no own assdb / not listed)
    if 'a' not in _BC:
        try:
            _BC['a'] = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bolt_catalog.json'))).get('assdb_maps', {})
        except Exception:
            _BC['a'] = {}
    return (_BC['a'].get(os.environ.get('DB1_SHA256', '')) or {}).get((standard or '').strip())


def fallback_geometry(standard, d):
    # c1audit-catalog: Tekla harvest / standard tables keyed by the assembly NAME only when the model's own assdb.db does not say which
    # screw that name is. MoldTek folders map 'A307' -> 8.8XOX, 'A325' -> 8.8XOX / F10T / HSFG-XOX, 'A325N' -> HSFG-XOX: Tekla drew those
    # screws (and DIN 934-type GR8-HEX nuts), so ASTM heavy-hex / hex tables are not 'as Tekla draws it' there -> nominal (tagged) instead
    if assdb_bolt_std(standard):
        return None
    return standard_geometry(standard, d)

'''
    s = s[:i0] + NEWCG + s[i1:]
    old_call = "sg = catalog_geometry(bolt_standard(m), d) or standard_geometry(bolt_standard(m), d)"
    assert s.count(old_call) == 1, 'bolts_of call'
    s = s.replace(old_call, "sg = catalog_geometry(bolt_standard(m), d, L) or fallback_geometry(bolt_standard(m), d)")
    old_we = '''    sg = b.get('std') or {}
    if sg.get('source') in ('model_catalog', 'tekla_harvest', 'table+tekla_washer') and sg.get('washer_od') and sg.get('washer_t'):
        return True'''
    assert s.count(old_we) == 1, 'washer_exact anchor'
    new_we = '''    sg = b.get('std') or {}
    if sg.get('source') == 'model_catalog' and 'washers' in sg:      # c1audit-catalog: every used slot in the catalog, nut-side = washer1 dims
        W = sg['washers']
        used = [k for k, n in (('head', b.get('wash_head')), ('w2', b.get('wash_2')), ('nut', b.get('wash_nut'))) if n]
        return 'head' in W and all(W.get(k) == W['head'] for k in used)      # the writer draws washer1's OD/t (washer_dims)
    if sg.get('source') in ('model_catalog', 'tekla_harvest', 'table+tekla_washer') and sg.get('washer_od') and sg.get('washer_t'):
        return True'''
    s = s.replace(old_we, new_we)
    open(bp, 'w').write(s)
    print('db1bolts.py patched')
else:
    print('db1bolts.py already patched')

sp = os.path.join(K, 'db1step.py'); s = open(sp).read()
if 'c1audit-stdL' not in s:
    o1 = '''    def std_fn(s_, d_):
        """the model folder's own bolt catalog first, then Tekla's own dims (IFC harvest), then the standards tables"""
        cg_ = getattr(db1bolts, 'catalog_geometry', None)
        sg_ = cg_(s_, d_) if cg_ else None'''
    n1 = '''    def std_fn(s_, d_, L_=None):   # c1audit-stdL
        """the model folder's own bolt catalog first, then Tekla's own dims (IFC harvest), then the standards tables"""
        cg_ = getattr(db1bolts, 'catalog_geometry', None)
        sg_ = cg_(s_, d_, L_) if cg_ else None'''
    assert s.count(o1) == 1, 'std_fn anchor'
    s = s.replace(o1, n1)
    o1b = "        return sg_ or db1bolts.standard_geometry(s_, d_)"
    assert s.count(o1b) == 1, 'std_fn return anchor'
    s = s.replace(o1b, "        return sg_ or db1bolts.fallback_geometry(s_, d_)   # c1audit-catalog: no name-keyed tables against the own assdb")
    open(sp, 'w').write(s); print('db1step.py patched')
else:
    print('db1step.py already patched')

b2 = os.path.join(K, 'db1bolts2.py'); s = open(b2).read()
if 'c1audit-stdL' not in s:
    o2 = "d_st = g['d']; L = g['L']; sg = std_fn(g.get('standard'), d_st) if std_fn else None"
    n2 = "d_st = g['d']; L = g['L']; sg = std_fn(g.get('standard'), d_st, L) if std_fn else None   # c1audit-stdL"
    assert s.count(o2) == 1, 'plan anchor'
    open(b2, 'w').write(s.replace(o2, n2)); print('db1bolts2.py patched')
else:
    print('db1bolts2.py already patched')

if len(sys.argv) > 2:
    shutil.copy(sys.argv[2], os.path.join(K, 'bolt_catalog.json')); print('bolt_catalog.json installed from', sys.argv[2])
