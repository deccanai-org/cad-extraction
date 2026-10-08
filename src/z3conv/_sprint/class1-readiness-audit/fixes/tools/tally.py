import json, collections, sys
for f in sys.argv[1:]:
    P=json.load(open(f)); c=collections.Counter(); combos=collections.Counter(); ex=collections.defaultdict(list)
    for k,v in P.items():
        if v.get('projected')!=2: continue
        b=set(v['standins'])|{'I:'+i.split(':')[0] for i in v['issues']}|{'N:'+n.split(':')[0][:30] for n in v['needs']}
        b|={'cov<1:'+x.replace('coverage_','') for x,y in v['coverage'].items() if y is not None and y<1}
        c.update(b); combos[tuple(sorted(b))]+=1; ex[tuple(sorted(b))].append(k[:12])
    print(f, 'class2:', sum(combos.values()))
    for k,n in c.most_common(): print('  ',n,k)
    print(' combos (<=3 blockers):')
    for k,n in combos.most_common():
        if len(k)<=3: print('  ',n,k, ex[k][:12])
