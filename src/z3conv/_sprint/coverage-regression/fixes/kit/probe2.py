#!/usr/bin/env python3
"""probe2: raw structure of one model's profdb.bin around user profiles (name table order, families, index records, value
blocks with their parameter codes) to see whether the missed names' parameter blocks can be located from the file itself."""
import os, sys, json, io, zipfile, struct, re, collections, gzip
import boto3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profdb
B = 'bim-proprietary-data'
s3 = boto3.client('s3', region_name='ap-south-1')
zk, member_folder = sys.argv[1], sys.argv[2]
names_want = sys.argv[3].split('|')
z = zipfile.ZipFile(io.BytesIO(s3.get_object(Bucket=B, Key=zk)['Body'].read()))
pk = next(n for n in z.namelist() if n.lower() == (member_folder + 'profdb.bin').lower())
d = z.read(pk)
if d[:2] == b'\x1f\x8b':
    d = gzip.decompress(d)
print('profdb bytes', len(d))
nm, vals = profdb.parse(d)
tab = profdb.table_entries(d)
print('index-record names', len(nm), 'value blocks', len(vals), 'table entries', len(tab))
fam = collections.Counter((f, c) for o, n, f, c in tab)
print('families', fam.most_common(40))
# value blocks in file order
order = []
seen = set()
for m in re.finditer(rb'\x04(.{4})\x01\x00\x00\x00(.{4})\x00\x00\x00\x00(.{8})', d, re.S):
    p = struct.unpack('<i', m.group(1))[0]
    if p in vals and p not in seen:
        seen.add(p); order.append((m.start(), p))
print('value blocks in order', len(order))
# parameter code sets per family among blocks that have an index record
byfam = collections.defaultdict(collections.Counter)
tabname = {n: (f, c, o) for o, n, f, c in tab}
for p, n in nm.items():
    if n in tabname and p in vals:
        byfam[tabname[n][:2]][tuple(sorted(vals[p]))] += 1
for k, v in sorted(byfam.items()):
    print('family/type', k, 'param code sets (indexed):', v.most_common(3))
# where are the wanted names in the table, and their neighbours
for w in names_want:
    hits = [(i, o, n, f, c) for i, (o, n, f, c) in enumerate(tab) if n == w]
    print('WANT', repr(w), hits[:3])
    for i, o, n, f, c in hits[:1]:
        for j in range(max(0, i - 3), min(len(tab), i + 4)):
            oo, nn, ff, cc = tab[j]
            print('    tab', j, oo, repr(nn), ff, cc, 'index pid', next((p for p, x in nm.items() if x == nn), None))
        # raw bytes of the table record
        print('    raw', d[o:o + 153].hex())
# value blocks that look like family-5 rectangles (h 6106 / b 6105 only) and are not indexed
cand = [(p, v) for p, v in vals.items() if p not in nm]
print('unindexed value blocks', len(cand))
for p, v in cand[:60]:
    print('   pid', p, {k: round(x, 4) for k, x in sorted(v.items())})
