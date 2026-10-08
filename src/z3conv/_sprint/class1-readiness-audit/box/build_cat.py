"""build_cat.py SIBDIR_ROOT IDS_JSON OLD_CATALOG OUT_JSON
Per-model Tekla bolt-assembly catalog from the model folder's OWN assdb.db + screwdb.db (same decoders / semantics as
db1_v2/prof/bolt/build_boltcat.py, validated on BSA Ardent: head k/s 1841/1841, washer t+OD 1910/1910, nut m 1807/1807), with two fixes:
  1. bolt heads are 'ambiguous' only when the HEAD parameters differ (k = p1, s = p4, e = p5). build_boltcat compared p1..p5, which
     includes p2 = thread length; Tekla's screwdb gives every length its own thread length, so every multi-length size was marked
     ambiguous (A325N/HSFG-XOX/4.6CUP/8.8CUP: 9-16 sizes per model) -> no catalog geometry, and catalog_geometry() raised KeyError 's'
     (7c68f0c9874e convert_error, class 3).
  2. heads that really differ between lengths are kept per length (by_L) so the bolt's own L selects the exact row; nuts and washers
     keep their own ambiguity rule (all of p1..p5 must agree) - they have no length.
Coverage: every data-3 DB1 model whose folder holds assdb.db + screwdb.db (build_boltcat only ran on the 54 models graded by then).
Old catalog entries are kept byte-identical in format (sizes[d] = {bolt, nut1, nut2, washer1, washer2, washer3}); 'bolt' gains by_L."""
import json, os, struct, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screwdb

ROOT, IDS, OLD, OUTP = sys.argv[1:5]


def asm(p):
    """assdb.db: body 169 (v203, Xsteel/Tekla <= 7.x): name@1[21] bolt_std@33 nut1@44 nut2@55 washer1@66 washer2@77 washer3@88 (11-byte slots);
    body 355 (v3, Tekla 8.x/9.x): name@1[31] grade@32 bolt_std@58 nut1@84 nut2@110 washer1@136 washer2@162 washer3@188 (26-byte slots).
    The 355 layout is read off BSA Ardent's own assdb (8.53, the validation pair): its screw standard is the @58 string (screwdb rows exist
    for 'THRD_ROD', 'HILTI KB3 SS316', 'THRD ROD' at @58, none for the @32 strings 'HIT-HY200', 'HILTI', 'F1554-105')."""
    d = screwdb.raw(p); v, n, b = struct.unpack('<3i', d[:12]); st = b + 1; out = {}
    if b not in (169, 355): return None, f'assdb version {v} body {b} (layout not decoded)'
    for i in range(n):
        r = d[12 + i * st:12 + (i + 1) * st]
        if len(r) < st or r[0] != 4: break
        cs = lambda o, l: r[o:o + l].split(b'\0')[0].decode('latin1').strip()
        if b == 169:
            out[cs(1, 21)] = dict(bolt_std=cs(33, 11), nut1=cs(44, 11), nut2=cs(55, 11), washer1=cs(66, 11), washer2=cs(77, 11), washer3=cs(88, 11))
        else:
            out[cs(1, 31)] = dict(grade=cs(32, 26), bolt_std=cs(58, 26), nut1=cs(84, 26), nut2=cs(110, 26), washer1=cs(136, 26), washer2=cs(162, 26),
                                  washer3=cs(188, 26), layout='assdb355')
    return out, None


def comp(rows, std, d, kind):
    c = [r for r in rows if r['std'] == std and abs(r['d'] - d) < 1e-3 and ((kind == 'bolt' and r['type'] in (1, 2, 3)) or
                                                                            (kind == 'nut' and r['type'] == 101) or (kind == 'washer' and r['type'] == 201))]
    if not c: return None
    p = c[0]['p']
    if kind == 'bolt':
        head = lambda x: (x['p'][0], x['p'][3], x['p'][4])
        hs = collections.Counter(head(x) for x in c)
        base = dict(thread=p[1], lengths=sorted({x['L'] for x in c}), names=sorted({x['name'] for x in c})[:4], n_rows=len(c),
                    types=sorted({x['type'] for x in c}))           # screwdb type 1 hex, 2 cup / round, 3 countersunk
        if len(hs) == 1:
            k, s, e = head(c[0]); return dict(base, k=k, s=s, e=e)
        byL = {}
        for x in c:
            k, s, e = head(x); key = f"{x['L']:g}"
            if key in byL and (byL[key]['k'], byL[key]['s'], byL[key]['e']) != (k, s, e): byL[key] = {'ambiguous': True}
            elif key not in byL: byL[key] = dict(k=k, s=s, e=e)
        return dict(base, ambiguous=len(hs), by_L=byL)
    if any(x['p'][:5] != p[:5] for x in c): return {'ambiguous': len(c)}
    if kind == 'nut': return dict(m=p[0], s=p[3], e=p[4], name=c[0]['name'])
    return dict(t=p[0], di=p[2], do=p[3], name=c[0]['name'])


COPIES = []      # every model folder's own screwdb rows (environment consensus for folders that ship assdb.db without screwdb.db)


def _key(z):
    return None if z is None else json.dumps({k: v for k, v in z.items() if k not in ('names', 'lengths', 'n_rows', 'name', 'thread')}, sort_keys=True)


def env_comp(std, d, kind):
    """component dims defined IDENTICALLY by every model-folder screwdb copy that defines (std, d) (>= 3 copies), else None"""
    res = [comp(rows, std, d, kind) for rows in COPIES]
    res = [z for z in res if z is not None]
    if len(res) < 3 or len({_key(z) for z in res}) != 1 or 'ambiguous' in res[0] and 'by_L' not in res[0]:
        return None
    return dict(res[0], env_copies=len(res))


def build(sd, env=False):
    a = os.path.join(sd, 'assdb.db'); s = os.path.join(sd, 'screwdb.db')
    if not os.path.exists(a): return None, 'no own assdb.db', None
    A, err = asm(a)
    if A is None: return None, err, None
    amap = {n: x['bolt_std'] for n, x in A.items()}
    if not os.path.exists(s):
        if not env: return None, f'own assdb.db ({len(A)} assemblies) without screwdb.db', amap
        ent = {}
        for name, x in A.items():
            ds = sorted({r['d'] for rows in COPIES for r in rows if r['std'] == x['bolt_std'] and r['type'] in (1, 2, 3)})
            sizes = {}
            for dd in ds:
                z = {'bolt': env_comp(x['bolt_std'], dd, 'bolt')}
                if z['bolt'] is None: continue
                for k in ('nut1', 'nut2'): z[k] = env_comp(x[k], dd, 'nut') if x[k] else None
                for k in ('washer1', 'washer2', 'washer3'): z[k] = env_comp(x[k], dd, 'washer') if x[k] else None
                sizes[str(dd)] = z
            ent[name] = dict(x, sizes=sizes, env=True)
        return ent, f'own assdb.db ({len(A)} assemblies) + environment screwdb consensus ({len(COPIES)} folder copies)', amap
    S = screwdb.screws(s); rows = S['rows']
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
    return ent, f'own folder assdb.db ({len(A)} assemblies) + screwdb.db v{S["version"]} body {S["body"]} ({len(rows)} components)', amap


old = json.load(open(OLD))
ENV = os.environ.get('BOLTCAT_ENV') == '1'
for j in json.load(open(IDS)):
    sp = os.path.join(ROOT, j['sha256'][:12] + '_sib', 'screwdb.db')
    if os.path.exists(sp):
        try: COPIES.append(screwdb.screws(sp)['rows'])
        except Exception: pass
out = {}; prov = {}; diff = {}; amaps = {}
for j in json.load(open(IDS)):
    sha = j['sha256']; sd = os.path.join(ROOT, sha[:12] + '_sib')
    try:
        e, pv, am = build(sd, ENV)
    except Exception as ex:
        e, pv, am = None, f'decode error {type(ex).__name__}: {str(ex)[:120]}', None
    prov[sha] = pv
    if e: out[sha] = e
    if am: amaps[sha] = am
    o = old['models'].get(sha)
    if o is not None:
        # same assemblies / nuts / washers as the old build; bolt heads differ only where the old build had 'ambiguous'
        ch = collections.Counter()
        for an, ae in o.items():
            ne = (e or {}).get(an)
            if ne is None: ch['assembly_missing'] += 1; continue
            for dd, z in ae['sizes'].items():
                nz = ne['sizes'].get(dd) or {}
                for k in ('nut1', 'nut2', 'washer1', 'washer2', 'washer3'):
                    ch['same_' + k if z.get(k) == nz.get(k) else 'diff_' + k] += 1
                ob, nb = z.get('bolt') or {}, nz.get('bolt') or {}
                if 'ambiguous' in ob:
                    ch['bolt_was_ambiguous_now_' + ('exact' if 'k' in nb else ('by_L' if 'by_L' in nb else 'none'))] += 1
                else:
                    ch['bolt_same' if all(ob.get(k) == nb.get(k) for k in ('k', 's', 'e')) else 'bolt_diff'] += 1
        diff[sha] = dict(ch)
json.dump(dict(meta=dict(old['meta'], fixes='build_cat.py (class1-readiness-audit): head ambiguity on k/s/e only (thread length varies by L), '
                                          'per-length heads (by_L), all data-3 models with own assdb.db + screwdb.db'),
               provenance=prov, models=out, assdb_maps=amaps), open(OUTP, 'w'), indent=1)
json.dump(diff, open(OUTP + '.vs_old.json', 'w'), indent=1)
print(len(out), 'models with catalog (env %s);' % ENV, len(amaps), 'own assdb maps;', collections.Counter(v.split(' (')[0].split(' v')[0] for v in prov.values()))
