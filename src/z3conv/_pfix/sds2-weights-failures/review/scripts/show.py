import json, sys
d=json.load(open(sys.argv[1]))
ids={k:[l.strip() for l in open(f'stage/ids_{k}.txt')] for k in ('ctl','ctl2','fam','s2','spot')}
grp={i:k for k,v in ids.items() for i in v}
def fm(x):
    if not x: return '-'
    return f"pub={int(x['publish2'])} {x['solids']}/{x['valid']} r={x['steel_ratio']} man={x['manifest_class'][0]}{x['manifest_class'][1]} cur={x['grade_cur']['cls']}{x['grade_cur'].get('corpus') or ''}" + (f" new={x['grade_new']['cls']}{x['grade_new'].get('corpus') or ''}" if 'grade_new' in x else '')
for k,v in sorted(d.items(), key=lambda kv: grp.get(kv[0],'z')):
    print(f"[{grp.get(k,'?')}] {k[:10]} {str(v.get('name'))[:26]}")
    for t in ('b553','w553','b555'):
        if t in v and 'error' not in v[t]: print('   ',t.ljust(5), fm(v[t]))
