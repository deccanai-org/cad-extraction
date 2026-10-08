"""Run the kit's convert_old with instrumentation: report every cut part whose body() returns None (reason), via a traced copy."""
import sys, os, re, json, types
H = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(H, '..', os.environ.get('KIT', 'kit_snapshot'))
sys.path.insert(0, KIT)
src = open(os.path.join(KIT, 'db1step.py')).read()
src = src.replace("            else: why['cut_body_unbuilt'] += 1\n",
                  "            else:\n                why['cut_body_unbuilt'] += 1; print('UNBUILT', m.get('pid', m.get('seq')), repr(m.get('prof')), m.get('mat'), 'L', round(m['L'],1), 'form', m.get('form'), 'npoly', len(m.get('old_poly') or []), 'reason', b[1], 'poly', m.get('old_poly'))\n")
mod = types.ModuleType('db1step_traced'); mod.__file__ = os.path.join(KIT, 'db1step.py')
exec(compile(src, 'db1step_traced', 'exec'), mod.__dict__)
cat = json.load(open(os.path.join(KIT, 'tekla_profiles.json')))
for f in sys.argv[1:]:
    st = mod.convert(f, '/tmp/_cut_trace.ifc', cat)
    print('==', os.path.basename(f)[:12], st.get('status'), st.get('skipped'), 'cuts_applied', st.get('cuts_applied'))
