import csv,glob,os,collections,re
GR=re.compile(r"G[TR]\d")
TOT=collections.Counter()
for j in sorted(os.listdir('v553h')):
    def L(v):
        p=glob.glob(f'{v}/{j}/*_pieces.csv')
        if not p: return None
        d={}
        for r in csv.DictReader(open(p[0])):
            d[(r['member'],r['piece'],r['inst'])]=r
        return d
    a,b=L('v553'),L('v553h')
    if a is None or b is None: print(j,'missing'); continue
    trans=collections.Counter(); ex=collections.defaultdict(list)
    lost=[k for k in a if k not in b]; new=[k for k in b if k not in a]
    for k in a:
        if k not in b: continue
        ra,rb=a[k],b[k]
        ta='T' if ra['standin'] else 'E'; tb='T' if rb['standin'] else 'E'
        if (ra['builder'],ta)!=(rb['builder'],tb):
            key=(('GR' if GR.match(ra['name']) else 'other'),ra['builder'],ta,rb['builder'],tb)
            trans[key]+=1
            if len(ex[key])<2: ex[key].append((ra['name'],ra['standin'][:80],'->',rb['standin'][:80]))
        elif ra['standin']!=rb['standin'] and ta=='T':
            trans[('tagtext',ra['builder'])]+=1
            k2=('tagtext',ra['builder'])
            if len(ex[k2])<2: ex[k2].append((ra['name'],ra['standin'][:100],'->',rb['standin'][:100]))
        # origin change
        if ra['builder']==rb['builder'] and (ra['ox'],ra['oy'],ra['oz'])!=(rb['ox'],rb['oy'],rb['oz']):
            trans[('origin_moved',ra['builder'])]+=1
    print('==',j,'rows',len(a),'->',len(b),'lost',len(lost),'new',len(new))
    for k in lost[:3]: print('   LOST',a[k]['name'],a[k]['builder'],a[k]['standin'][:80])
    for k,v in trans.most_common():
        print('  ',v,k, ex.get(k,[''])[0])
        TOT[k]+=v
print('TOTAL');[print(' ',v,k) for k,v in TOT.most_common()]
