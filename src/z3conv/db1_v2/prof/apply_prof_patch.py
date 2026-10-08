"""Apply the db1prof profile fixes to a db1 kit directory (idempotent, anchor-checked).
  python3 apply_prof_patch.py KIT_DIR        (KIT_DIR holds db1step.py, db1old.py, convert_one.py)
Copies db1prof.py and model_catalogs.json into KIT_DIR. Every anchor must match exactly once, else nothing is written."""
import os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
K = sys.argv[1]
MARK = '# db1prof-patch'

EDITS = {
    'db1step.py': [
        # import
        ("from db1dec import decode, members, _axis_agreement, _axis_flags\n",
         "from db1dec import decode, members, _axis_agreement, _axis_flags\nimport db1prof  " + MARK + "\n"),
        # tapered parametric sections (ELD / EPD), before the contour-plate fallback
        ("    if P_PLATE1.match(n): return None, 'contour_plate', None\n",
         "    tp = db1prof.parse_tapered(n)  " + MARK + "\n    if tp: return tp\n"
         "    if P_PLATE1.match(n): return None, 'contour_plate', None\n"),
        # plausibility of frustums
        ("        if kind == 'CHS': return 0 < 2 * v[0] <= 3000 and 0 < v[1] < v[0]\n",
         "        if kind == 'CHS': return 0 < 2 * v[0] <= (db1prof.MAX_D if how == 'parametric_epd' else 3000) and 0 < v[1] < v[0]\n"
         "        if kind == 'FRUSTUM': return db1prof.plausible_frustum(v)  " + MARK + "\n"),
        # CIRC from ELD (constant section) uses the frustum bound, not the round-bar one
        ("            if how == 'parametric_stud_shank': lim = 100\n",
         "            if how == 'parametric_stud_shank': lim = 100\n"
         "            elif how == 'parametric_eld': lim = db1prof.MAX_D  " + MARK + "\n"),
        # profile entity for frustums: a marker consumed by element()
        ("        elif kind in ('ARB', 'ARBV'):\n            pts = [f.createIfcCartesianPoint((float(x), float(y))) for x, y in v]",
         "        elif kind == 'FRUSTUM':  " + MARK + "\n            p = db1prof.Frustum(v[0], v[1], v[2], nm)\n"
         "        elif kind in ('ARB', 'ARBV'):\n            pts = [f.createIfcCartesianPoint((float(x), float(y))) for x, y in v]"),
        ("        solid = self.extrusion(prof, depth); rtype = 'SweptSolid'\n",
         "        if isinstance(prof, db1prof.Frustum):  " + MARK + "\n"
         "            solid = db1prof.frustum_solid(f, prof, depth); rtype = 'Brep'\n"
         "        else:\n            solid = self.extrusion(prof, depth); rtype = 'SweptSolid'\n"),
        ("            rtype = 'CSG'\n        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', rtype, [solid])\n",
         "            rtype = 'CSG'\n        rep = f.createIfcShapeRepresentation(self.ctx, 'Body', rtype, [solid])\n"),
        # orient frustums (h1 at the part start point) in both writers' body()
        ("        prof = out.profile(m['prof'], kind, v)\n        if prof is None: return (None, 'writer_skip')\n        return (out.member_frame(m), prof, m['L'], how)\n",
         "        prof = out.profile(m['prof'], kind, v)\n        if prof is None: return (None, 'writer_skip')\n"
         "        if isinstance(prof, db1prof.Frustum): prof = db1prof.oriented(prof, m)  " + MARK + "\n"
         "        return (out.member_frame(m), prof, m['L'], how)\n"),
        ("        prof = out.profile(m['prof'], kind, v)\n        if prof is not None and BOLTS_ON:\n",
         "        prof = out.profile(m['prof'], kind, v)\n"
         "        if isinstance(prof, db1prof.Frustum): prof = db1prof.oriented(prof, m)  " + MARK + "\n"
         "        if prof is not None and BOLTS_ON:\n"),
        # old engines: records without geometry are not parts
        ("    M, info, cut_rel = db1old.read(data, engine)\n",
         "    M, info, cut_rel = db1old.read(data, engine)\n"
         "    _null = [m for m in M if db1prof.is_null_record(m)]  " + MARK + "\n"
         "    M = [m for m in M if not db1prof.is_null_record(m)]\n"),
        ("              axis_mismatch_dropped=bad_axis)\n",
         "              axis_mismatch_dropped=bad_axis, null_records=len(_null), null_record_names=sorted({m.get('prof') or '' for m in _null})[:10])\n"),
    ],
    'db1old.py': [
        ("    def cstr(self, o, n):\n        e = self.b.find(b'\\0', o, o + n)\n",
         "    def cstr(self, o, n):\n        # db1prof-patch: Latin-1 letters kept ('R.B \\xd820' = 'R.B Ø20'; the ASCII-only cut gave 'R.B ')\n"
         "        if True:\n            import db1prof\n            return db1prof.latin1_cstr(self.b, o, n)\n"
         "        e = self.b.find(b'\\0', o, o + n)\n"),
    ],
    'convert_one.py': [
        ("    st = convert(db1, out_ifc, json.load(open(catp)), lay or None, variants, allow_full=os.environ.get('DB1_FULL_DISCOVERY', '0') == '1')\n",
         "    cat = json.load(open(catp))\n"
         "    try:  " + MARK + ": exact profiles from the models' own catalogs (tekla_profiles_overlay.json: global + per DB1 sha256)\n"
         "        import hashlib\n"
         "        here = os.path.dirname(os.path.abspath(__file__))\n"
         "        ovp = os.path.join(here, 'tekla_profiles_overlay.json')\n"
         "        if os.path.exists(ovp):\n"
         "            ov = json.load(open(ovp))\n"
         "            h = hashlib.sha256(open(db1, 'rb').read()).hexdigest()\n"
         "            for src in (ov.get('global') or {}, (ov.get('per_model') or {}).get(h) or {}):\n"
         "                cat.update({k: {'kind': v['kind'], 'dims': v['dims'], 'overlay': v.get('src')} for k, v in src.items()})\n"
         "    except Exception:\n"
         "        pass\n"
         "    st = convert(db1, out_ifc, cat, lay or None, variants, allow_full=os.environ.get('DB1_FULL_DISCOVERY', '0') == '1')\n"),
    ],
}

new = {}
for fn, edits in EDITS.items():
    p = os.path.join(K, fn)
    s = open(p).read()
    if MARK in s or 'db1prof.latin1_cstr' in s:
        print(fn, 'already patched'); new[fn] = None; continue
    for a, b in edits:
        n = s.count(a)
        if a == b: continue
        if n != 1:
            sys.exit(f'{fn}: anchor found {n}x: {a[:70]!r}')
        s = s.replace(a, b)
    new[fn] = s
for fn, s in new.items():
    if s is not None:
        open(os.path.join(K, fn), 'w').write(s); print('patched', fn)
for f in ('db1prof.py', 'tekla_profiles_overlay.json'):
    if os.path.exists(os.path.join(HERE, f)): shutil.copy(os.path.join(HERE, f), os.path.join(K, f))
