import json, collections, sys
S=json.load(open(sys.argv[1])); ids=sys.argv[2].split(',') if len(sys.argv)>2 and sys.argv[2] else None
K=None
agg={'nom':collections.Counter(),'wash':collections.Counter(),'hole':collections.Counter(),'w2':collections.Counter(),'ax':collections.Counter(), 'slot':collections.Counter()}
per={}
for sid,v in S.items():
    if ids and sid[:12] not in ids: continue
    if 'rows' not in v: continue
    K=v['keys']; ix={k:i+1 for i,k in enumerate(K)}
    pm={'nom':collections.Counter(),'wash':collections.Counter(),'hole':collections.Counter(),'w2':0,'ax':collections.Counter(),'slot':0,'bolts':0}
    for r in v['rows']:
        n=r[0]; g=lambda k: r[ix[k]]
        ho=g('holes_only'); pm['bolts']+=n
        if not ho and not g('src'): pm['nom'][(g('standard'), g('d_stored'))]+=n; agg['nom'][g('standard')]+=n
        if g('tol') is None and g('holed'): pm['hole'][(g('standard'), g('d_stored'), g('tolraw'))]+=n; agg['hole'][('tolraw='+str(g('tolraw')))]+=n
        if not ho and (g('wh') or g('wn') or g('w2')) and not g('washer_exact'): pm['wash'][(g('standard'), g('d_stored'), g('src'), (g('family') or '')[:40])]+=n*((g('wh') or 0)+(g('wn') or 0)+(g('w2') or 0)); agg['wash'][(g('src'), (g('family') or '')[:30])]+=n
        if not ho and g('w2'): pm['w2']+=n
        if not ho and g('shifted'): pm['ax'][(g('standard'),)]+=n
        if g('slot12') not in (None,'0/0','0.0/0.0','0/0.0','0.0/0'): pm['slot']+=n
    per[sid[:12]]=pm
for sid,pm in per.items():
    print(sid, 'bolts',pm['bolts'],'| nominal head/nut:',dict(pm['nom']),'| nominal holes:',dict(pm['hole']),'| washers nominal:',dict(pm['wash']),'| w2:',pm['w2'],'| fitted:',dict(pm['ax']),'| slot:',pm['slot'])
print('AGG', {k:dict(v.most_common(25)) for k,v in agg.items()})
