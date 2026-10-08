import json,glob,collections,sys
rows={r['id']:r for r in json.load(open('live/pnb_rows.json'))}
CLOSABLE={'closed','open+degenerate'}
out=[]
for f in sorted(glob.glob('cls/*.json')):
    d=json.load(open(f)); i=f.split('/')[-1][:-5]; r=rows.get(i,{})
    ins=d['inst_by_class']; occ=d['occ_sample']
    # projected: closable if sample success ratio == 1 for that class
    proj=collections.Counter()
    for c,n in ins.items():
        o=occ.get(c,{})
        ok=(o.get('base',0)+o.get('drop_degenerate+conform',0))/max(1,o.get('n',0)) if o else 0
        if c in ('parse_none',): proj['triangle_or_unparsed->open surface/skip']+=n
        elif c=='over_max_faces': proj['over_max_faces(skip)']+=n
        elif ok==1.0: proj['solid']+=n
        elif ok==0: proj['open surface']+=n
        else: proj['mixed']+=n
    allsolid = set(proj)=={'solid'}
    out.append(dict(id=i,job=d['job'],placed=d['placed_inst'],v5skip=sum(r.get('reasons',{}).values()),proj=dict(proj),allsolid=allsolid,only=r.get('only'),conv=r.get('conv')))
for o in out: print(f"{o['id'][:6]} {o['job'][:20]:20s} {o['conv']} placed {o['placed']:7d} v5skip {o['v5skip']:7d} -> {o['proj']} {'ALL-SOLID' if o['allsolid'] else ''}")
print('n',len(out),'all-solid',sum(o['allsolid'] for o in out))
T=collections.Counter()
for o in out:
    for k,v in o['proj'].items(): T[k]+=v
print(dict(T))
