import sys, os, json, glob, csv, collections
W='/work/agentwork/sds2-weights-failures-review'
sys.path.insert(0, f'{W}/trees/w553/sds2-step-pipeline/decode')
from piece_table import read_pieces
from sds2job import read_members
import instances
JN, JID = sys.argv[1], sys.argv[2]
job=glob.glob(f'{W}/jobs/'+JN)[0]
P=read_pieces(job)
mems,_=read_members(job); mt={m.id:m.type for m in mems}
B=list(csv.DictReader(open(glob.glob(f'{W}/out/w553nx/'+JID+'/*_pieces.csv')[0])))
A=list(csv.DictReader(open(glob.glob(f'{W}/out/w553/'+JID+'/*_pieces.csv')[0])))
ka=collections.Counter((r['member'],r['piece']) for r in A)
extra=[r for r in B if ka[(r['member'],r['piece'])]==0]
c=collections.Counter()
for r in extra:
    sid=int(r['piece']); n=int(r['member'])
    c[(mt.get(n), sid in P, (P.get(sid) or {}).get('name'))]+=1
print('extra', len(extra)); 
for k,v in c.most_common(30): print(v, k)
# piece files in subm without piece table entry
ids=[int(x) for x in os.listdir(f'{job}/subm') if x.isdigit()]
print('piece files', len(ids), 'in table', sum(i in P for i in ids), 'table entries', len(P))
# members with extra placements: what does the normal run write for them
ms={r['member'] for r in extra}
print('normal rows for those members:', collections.Counter((r['member_type'], r['builder']) for r in A if r['member'] in ms).most_common(10))
sk=list(csv.DictReader(open(glob.glob(f'{W}/out/w553/'+JID+'/*_skipped.csv')[0])))
print('normal skipped for those members', [r for r in sk if r['member'] in ms][:5])
