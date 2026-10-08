import csv,glob,os,json,collections,re
GR=re.compile(r"G[TR]\d")
TOT=collections.Counter(); summ=[]
for d in sorted(glob.glob('held/*')):
    mid=os.path.basename(d)
    def L(t):
        m=json.load(open(glob.glob(f'{d}/{t}/*_manifest.json')[0]))
        p={}
        for r in csv.DictReader(open(glob.glob(f'{d}/{t}/*_pieces.csv')[0])):
            p[(r['member'],r['piece'],r['inst'])]=r
        return m,p
    (ma,a),(mb,b)=L('old'),L('new')
    ca,cb=ma['counts'],mb['counts']; ra,rb=ma['readback'],mb['readback']
    trans=collections.Counter(); ex={}
    lost=[k for k in a if k not in b]; new=[k for k in b if k not in a]
    for k in a:
        if k not in b: continue
        x,y=a[k],b[k]
        tx='T' if x['standin'] else 'E'; ty='T' if y['standin'] else 'E'
        if (x['builder'],tx)!=(y['builder'],ty):
            key=('GR' if GR.match(x['name']) else 'other',x['builder'],tx,y['builder'],ty)
            trans[key]+=1; ex.setdefault(key,(x['name'],x['standin'][:70],'->',y['standin'][:110]))
    print(f"== {mid} {mb['job'][:40]} {ma.get('version')} cls {ma['class']}->{mb['class']} placed {ca['placed_pieces']}->{cb['placed_pieces']} written {ca['pieces_written']}->{cb['pieces_written']} skipped {ca.get('skipped')}->{cb.get('skipped')} rb {ra.get('solids')}/{ra.get('invalid')} -> {rb.get('solids')}/{rb.get('invalid')} ratio {ma['weight_check']['ratio']}->{mb['weight_check']['ratio']} lost {len(lost)} new {len(new)}")
    g=mb.get('grating'); 
    if g: print('   grating', {k:v for k,v in g.items() if k!='note'})
    if mb.get('rods'): print('   rods', mb['rods'])
    for k,v in trans.most_common(): print('   ',v,k,ex[k]); TOT[k]+=v
    for k in lost[:3]: print('   LOST', a[k]['name'], a[k]['builder'])
    summ.append(dict(id=mid,job=mb['job'],cls=(ma['class'],mb['class']),inv=(ra.get('invalid'),rb.get('invalid')),lost=len(lost),grating=g,rods=mb.get('rods')))
print('TOTAL'); [print('  ',v,k) for k,v in TOT.most_common()]
json.dump(summ,open('held_summary.json','w'),indent=0)
