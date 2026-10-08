"""asmmap.py : every model folder's own assdb.db -> {assembly: component standards} + screwdb digest (bolt std -> sizes, heads) -> asmmap.json"""
import json, os, sys, glob, struct, collections, hashlib
sys.path.insert(0, 'job')
import screwdb
def asm(p):
    d = screwdb.raw(p); v, n, b = struct.unpack('<3i', d[:12]); st = b + 1; out = {}
    for i in range(n):
        r = d[12 + i * st:12 + (i + 1) * st]
        if len(r) < st or r[0] != 4: break
        cs = lambda o, l: r[o:o + l].split(b'\0')[0].decode('latin1').strip()
        if b == 169: out[cs(1, 21)] = [cs(33, 11), cs(44, 11), cs(55, 11), cs(66, 11), cs(77, 11), cs(88, 11)]
        elif b == 355: out[cs(1, 31)] = [cs(58, 26), cs(84, 26), cs(110, 26), cs(136, 26), cs(162, 26), cs(188, 26)]
    return {'version': v, 'body': b, 'n': n, 'asm': out, 'md5': hashlib.md5(d).hexdigest()}
R = {}
for sd in sorted(glob.glob('src/*_sib')):
    k = os.path.basename(sd)[:12]; e = {}
    a = os.path.join(sd, 'assdb.db'); s = os.path.join(sd, 'screwdb.db')
    try:
        if os.path.exists(a): e['assdb'] = asm(a)
    except Exception as ex: e['assdb_err'] = str(ex)[:100]
    try:
        if os.path.exists(s):
            S = screwdb.screws(s); dig = collections.defaultdict(dict)
            for r in S['rows']:
                if r['type'] in (1, 2, 3, 101, 201):
                    dig[r['std']].setdefault(f"{r['d']:g}", [r['type'], r['p'][0], r['p'][2], r['p'][3], r['p'][4]])
            e['screwdb'] = {'version': S['version'], 'body': S['body'], 'n': S['count'], 'md5': hashlib.md5(screwdb.raw(s)).hexdigest(), 'std': dig}
    except Exception as ex: e['screwdb_err'] = str(ex)[:100]
    if e: R[k] = e
json.dump(R, open('asmmap.json', 'w'))
import boto3; boto3.client('s3', region_name='ap-south-1').upload_file('asmmap.json', 'bim-proprietary-data', 'cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/asmmap.json')
print(len(R), 'model folders;', sum(1 for v in R.values() if 'assdb' in v), 'assdb;', sum(1 for v in R.values() if 'screwdb' in v), 'screwdb')
