import sys, io, types, importlib.util, subprocess, json
def load(p):
    spec = importlib.util.spec_from_file_location('m' + str(abs(hash(p))), p); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
new = load(sys.argv[1])
names = {"plain": "W12X26", "one_quote": "Joe's beam", "two_quotes_inch": "Basic Wall:Concrete - 200mm (8'')", "trail_quote": "L 3'", "lead_quote": "'x",
         "backslash": "C:\\path\\x", "nonascii": "Stahltr\u00e4ger \u00d8200", "raw4": None}
def model(path, nm, raw=None):
    w = new.StepWriter(open(path, 'w'), 'test.ifc', '.MILLI.', 0.01)
    P = [(0,0,0),(100,0,0),(100,100,0),(0,100,0),(0,0,100),(100,0,100),(100,100,100),(0,100,100)]
    ids = [w.pt(*p) for p in P]
    F = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    faces = [w.face([([ids[i] for i in f], [P[i] for i in f], True)]) for f in F]
    br = w.solid(faces, True)
    if raw:   # emulate the old writer: name.replace("'", "''")
        w.part.__func__  # noqa
        old_nm = raw.replace("'", "''")
        p = w.e("PRODUCT('%s','%s','',(#%d))" % (old_nm, old_nm, w.ctx_prod)); pdf = w.e("PRODUCT_DEFINITION_FORMATION('','',#%d)" % p)
        pd = w.e("PRODUCT_DEFINITION('design','',#%d,#%d)" % (pdf, w.ctx_pdef)); pds = w.e("PRODUCT_DEFINITION_SHAPE('','',#%d)" % pd)
        rep = w.e("FACETED_BREP_SHAPE_REPRESENTATION('%s',(#%d,#%d),#%d)" % (old_nm, w.origin_ax, br[0], w.ctx_geom)); w.e("SHAPE_DEFINITION_REPRESENTATION(#%d,#%d)" % (pds, rep))
    else:
        w.part(nm, [br[0]], True)
    w.close(); w.fh.close()
res = {}
for k, nm in names.items():
    p = f'/tmp/qt_{k}.step'
    model(p, nm, raw=("Basic Wall:Concrete - 200mm (8'')" if k == 'raw4' else None))
    r = subprocess.run([sys.executable, sys.argv[2], p], capture_output=True, text=True)
    try: v = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: v = {'rc': r.returncode}
    res[k] = (r.returncode, v.get('read_status'), v.get('transferred'), v.get('solids'), [l for l in open(p) if 'PRODUCT(' in l][0].strip()[:90])
for k, v in res.items(): print(k, v)
