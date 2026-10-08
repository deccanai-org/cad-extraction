import re, sys, os, json, collections
sys.path.insert(0, 'patch'); import lumpsplit
# for every FACETED_BREP: decompose; how many breps that would be rewritten contain an open component
rx = re.compile(r'#(\d+)\s*=\s*([A-Z_0-9]*)\s*\((.*)\)\s*$', re.S)
for path in sys.argv[1:]:
    ent = {}; buf = ''
    for line in open(path, encoding='latin-1'):
        buf += line
        if not buf.rstrip().endswith(';'): continue
        s, buf = buf.strip()[:-1], ''
        m = rx.match(s)
        if m: ent[int(m.group(1))] = (m.group(2), m.group(3))
    refs = lambda s: [int(x) for x in re.findall(r'#(\d+)', s)]
    pt = {k: tuple(float(x) for x in re.findall(r'[-+0-9.Ee]+', b.split('(', 1)[1])[:3]) for k, (t, b) in ent.items() if t == 'CARTESIAN_POINT'}
    c = collections.Counter()
    for k, (t, b) in ent.items():
        if t != 'FACETED_BREP': continue
        loops = []
        for f in refs(ent[refs(b)[0]][1]):
            ls = []
            for bid in refs(ent[f][1].split(')', 1)[0]):
                bb = ent[bid][1]; p = refs(ent[refs(bb)[0]][1]); ls.append(p if '.T.' in bb.rsplit(',', 1)[-1] else p[::-1])
            loops.append(ls)
        comps, info = lumpsplit.decompose(loops, pt)
        rew = len(comps) > 1 or info['cancelled_faces']
        if not rew: continue
        c['rewritten'] += 1
        nopen = sum(1 for x in comps if not x['closed'])
        c['rewritten_with_open'] += nopen > 0
        c['rewritten_all_closed'] += nopen == 0
    print(path, dict(c))
