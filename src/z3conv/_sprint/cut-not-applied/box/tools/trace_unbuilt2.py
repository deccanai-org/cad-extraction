"""trace_unbuilt.py KITDIR DB1 : run the kit's db1step.convert with every unbuilt cut body printed (reason, profile, polygon) and,
for new engines, the unlinked cut parts; writes nothing else (IFC to /tmp)."""
import sys, os, re, json, types, hashlib, collections
KIT = sys.argv[1]; sys.path.insert(0, KIT)
src = open(os.path.join(KIT, 'db1step.py')).read()
hook = "            else: why['cut_body_zero_thickness' if zero_section(m.get('prof')) else 'cut_body_unbuilt'] += 1   # cut-not-applied P10\n"
assert src.count(hook) == 2, src.count(hook)
src = src.replace(hook, "            else:\n                why['cut_body_zero_thickness' if zero_section(m.get('prof')) else 'cut_body_unbuilt'] += 1; _TRACE(m, b)\n")
src = src.replace("    links = db.find_cut_links(M)\n", "    links = db.find_cut_links(M); _LINKS(M, links); _DB.update(db=db, lay=lay)\n")
mod = types.ModuleType('db1step'); mod.__file__ = os.path.join(KIT, 'db1step.py')
R = collections.Counter(); EX = collections.defaultdict(list)
def _TRACE(m, b):
    key = (b[1], (m.get('prof') or '')[:2])
    if len(EX[key]) < 3 and _DB.get('db') is not None and m.get('seq') is not None:
        try:
            db_, lay_ = _DB['db'], _DB['lay']
            print('   RAW', m.get('seq'), m.get('prof'), 'L', round(m['L'], 3), 'outline_points', db_.outline_points(lay_, m), flush=True)
        except Exception as ex_: print('   RAW err', ex_)
    R[key] += 1
    if len(EX[key]) < 4:
        EX[key].append(dict(id=m.get('pid', m.get('seq')), prof=m.get('prof'), L=round(m['L'], 1), npoly=len(m.get('old_poly') or []),
                            poly=[[round(c, 1) for c in p] for p in (m.get('old_poly') or [])][:8], form=m.get('form'), off=m.get('off')))
def _LINKS(M, links):
    ln = {c for v in links.values() for c in v}
    un = [m for m in M if m.get('cut') and m['seq'] not in ln]
    print('LINKS cuts', sum(1 for m in M if m.get('cut')), 'linked', len(ln), 'unlinked', len(un))
    for m in un[:10]: print('   unlinked cut seq', m['seq'], m['prof'], 'L', round(m['L'], 1), 'off', m['off'])
_DB = {}
mod.__dict__['_TRACE'] = _TRACE; mod.__dict__['_LINKS'] = _LINKS; mod.__dict__['_DB'] = _DB
sys.modules['db1step'] = mod
exec(compile(src, 'db1step', 'exec'), mod.__dict__)
db1 = sys.argv[2]
os.environ['DB1_SHA256'] = hashlib.sha256(open(db1, 'rb').read()).hexdigest()
cat = json.load(open(os.path.join(KIT, 'tekla_profiles.json')))
ovp = os.path.join(KIT, 'tekla_profiles_overlay.json')
if os.path.exists(ovp):
    ov = json.load(open(ovp))
    for s_ in (ov.get('global') or {}, (ov.get('per_model') or {}).get(os.environ['DB1_SHA256']) or {}):
        cat.update({k: {'kind': v['kind'], 'dims': v['dims'], 'overlay': v.get('src')} for k, v in s_.items()})
L = json.load(open(os.path.join(KIT, 'layouts.json')))
raw = open(db1, 'rb').read(1 << 16)
import zlib
d = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
eng = re.search(rb'(\d+\.\d+)', d[:16]).group(1).decode()
lay = (L.get(eng) or {}).get('layout'); var = [v['layout'] for v in L.values() if v.get('layout')]
st = mod.convert(db1, '/tmp/_trace_%d.ifc' % os.getpid(), cat, lay, var, allow_full=True)
print('==', os.path.basename(db1)[:16], eng, st.get('status'), 'skipped', st.get('skipped'), 'cuts_applied', st.get('cuts_applied'), 'cut_layout', st.get('cut_layout'))
for k, v in R.most_common():
    print('  UNBUILT', v, k)
    for e in EX[k]: print('       ', e)
try: os.remove('/tmp/_trace_%d.ifc' % os.getpid())
except Exception: pass
