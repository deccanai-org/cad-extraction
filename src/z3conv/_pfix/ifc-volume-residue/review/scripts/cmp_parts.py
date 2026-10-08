import json, gzip, collections, os, sys
def load(p):
    out={}
    if not os.path.exists(p): return None
    for l in gzip.open(p,'rt'):
        r=json.loads(l)
        if r.get('pid'): out.setdefault(r['pid'],r)
    return out
def cmp(a,b,i):
    A=load(f'{a}/{i}/step_parts.jsonl.gz'); B=load(f'{b}/{i}/step_parts.jsonl.gz')
    if A is None or B is None: return None
    lost=[g for g in A if g not in B]; new=[g for g in B if g not in A]
    sol=lambda r:(r.get('solids') or 0)>0
    deg=[g for g in A if g in B and sol(A[g]) and not sol(B[g])]
    imp=[g for g in A if g in B and not sol(A[g]) and sol(B[g])]
    valid=lambda r:(r.get('valid') or 0)>=(r.get('solids') or 0)>0
    inv=[g for g in A if g in B and valid(A[g]) and sol(B[g]) and not valid(B[g])]
    vch=[g for g in A if g in B and sol(A[g]) and sol(B[g]) and abs((A[g].get('volume') or 0)-(B[g].get('volume') or 0))>1e-6*max(abs(A[g].get('volume') or 0),1)]
    tagch=[g for g in A if g in B and (A[g].get('desc') or '')!=(B[g].get('desc') or '')]
    return dict(nA=len(A),nB=len(B),lost=len(lost),new=len(new),solid_to_nonsolid=len(deg),nonsolid_to_solid=len(imp),valid_to_invalid=len(inv),vol_changed=len(vch),desc_changed=len(tagch)), lost, deg, A, B, vch
if __name__=='__main__':
    a,b=sys.argv[1],sys.argv[2]
    tot=collections.Counter()
    for i in sorted(os.listdir(b)):
        if not os.path.isdir(f'{b}/{i}') or not os.path.isdir(f'{a}/{i}'): continue
        r=cmp(a,b,i)
        if r is None: print(a,b,i,'missing step_parts'); continue
        print(b, i, r[0])
        for k,v in r[0].items():
            if k not in('nA','nB'): tot[k]+=v
    print('TOTAL',a,'->',b, dict(tot))
