"""Per-model bolt assembly catalog from the model folder's own assdb.db + screwdb.db (data-3 DB1 models).
assdb (v203, body 169): name@1[21] bolt_std@33 nut1@44 nut2@55 washer1@66 washer2@77 washer3@88 (11-byte slots)
screwdb: see screwdb.py. Bolt head k/s/e = p1/p4/p5; nut m/s/e = p1/p4/p5 (hole p3); washer t/di/do = p1/p3/p4.
Output bolt_catalog.json {sha256: {assembly: {bolt_std, nut1, nut2, washer1, washer2, washer3,
  sizes: {d: {bolt: {k, s, e, lengths}, nut1: {m, s, e}, washer1: {t, di, do}, ...}}}}} + provenance."""
import json, os, struct, sys, glob, collections
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import screwdb
P = os.path.dirname(HERE)
F = json.load(open(os.path.join(P, 'folders.json')))
def asm(p):
    d = screwdb.raw(p); v, n, b = struct.unpack('<3i', d[:12]); st = b + 1; out = {}
    if b != 169: return None, f'assdb body {b} (layout not decoded)'
    for i in range(n):
        r = d[12 + i * st:12 + (i + 1) * st]
        if len(r) < st or r[0] != 4: break
        cs = lambda o, l: r[o:o + l].split(b'\0')[0].decode('latin1').strip()
        out[cs(1, 21)] = dict(bolt_std=cs(33, 11), nut1=cs(44, 11), nut2=cs(55, 11), washer1=cs(66, 11), washer2=cs(77, 11), washer3=cs(88, 11))
    return out, None
def comp(rows, std, d, kind):
    c = [r for r in rows if r['std'] == std and abs(r['d'] - d) < 1e-3 and ((kind == 'bolt' and r['type'] in (1, 2, 3)) or (kind == 'nut' and r['type'] == 101) or (kind == 'washer' and r['type'] == 201))]
    if not c: return None
    p = c[0]['p']
    if any(x['p'][:5] != p[:5] for x in c): return {'ambiguous': len(c)}
    if kind == 'bolt': return dict(k=p[0], s=p[3], e=p[4], thread=p[1], lengths=sorted({x['L'] for x in c}), names=sorted({x['name'] for x in c})[:4])
    if kind == 'nut': return dict(m=p[0], s=p[3], e=p[4], name=c[0]['name'])
    return dict(t=p[0], di=p[2], do=p[3], name=c[0]['name'])
out = {}; prov = {}
for sha, v in sorted(F.items()):
    d = os.path.join(P, 'mf', sha[:10])
    a = os.path.join(d, 'assdb.db'); s = os.path.join(d, 'screwdb.db')
    if not (os.path.exists(a) and os.path.exists(s)): prov[sha] = 'no own assdb.db + screwdb.db'; continue
    A, err = asm(a)
    if A is None: prov[sha] = err; continue
    rows = screwdb.screws(s)['rows']
    ent = {}
    for name, x in A.items():
        ds = sorted({r['d'] for r in rows if r['std'] == x['bolt_std'] and r['type'] in (1, 2, 3)})
        sizes = {}
        for dd in ds:
            z = {'bolt': comp(rows, x['bolt_std'], dd, 'bolt')}
            for k in ('nut1', 'nut2'): z[k] = comp(rows, x[k], dd, 'nut') if x[k] else None
            for k in ('washer1', 'washer2', 'washer3'): z[k] = comp(rows, x[k], dd, 'washer') if x[k] else None
            sizes[str(dd)] = z
        ent[name] = dict(x, sizes=sizes)
    out[sha] = ent; prov[sha] = f'own folder assdb.db ({len(A)} assemblies) + screwdb.db ({len(rows)} components)'
json.dump(dict(meta=dict(src='model folder assdb.db + screwdb.db (Tekla bolt assembly / screw catalogs), decoded by prof/bolt/screwdb.py + build_boltcat.py',
                         params='bolt k = head height, s = across flats, e = across corners; nut m = height; washer t = thickness, di/do = inner/outer diameter (mm)',
                         validation='format and parameter meaning validated on BSA Ardent (Tekla 8.53): same-project screwdb vs Tekla IFC 29903.ifc - head k 1841/1841, head s 1841/1841, washer t+OD 1910/1910, nut m 1807/1807'),
               provenance=prov, models=out), open(os.path.join(P, 'bolt_catalog.json'), 'w'), indent=1)
print(len(out), 'models with own bolt catalog'); 
hx = {s: {k: v['bolt_std'] for k, v in e.items() if k.startswith('HEX B/N')} for s, e in out.items()}
print({s[:10]: v for s, v in hx.items() if v})
s0 = next(s for s, v in hx.items() if v); e = out[s0]['HEX B/N M16']; print(json.dumps({k: v for k, v in e.items() if k != 'sizes'}), json.dumps(e['sizes'])[:900])
