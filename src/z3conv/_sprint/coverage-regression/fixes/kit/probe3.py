#!/usr/bin/env python3
"""probe3: independent part count for a 7.24 model whose folder ships Tekla's OWN IFC exports (out*.ifc) and a material report:
is the python decoder inventory (expected parts) or the Windows reader's part list closer to what Tekla itself exported?
usage: probe3.py ZIP_KEY DB1_SHA OUT_JSON"""
import os, sys, io, re, json, zipfile, hashlib, collections, tempfile, shutil
import boto3
B = 'bim-proprietary-data'
s3 = boto3.client('s3', region_name='ap-south-1')
zk, sha, outp = sys.argv[1:4]
tmp = tempfile.mkdtemp(dir='/work/agentwork/coverage-regression')
zp = os.path.join(tmp, 'm.zip'); s3.download_file(B, zk, zp)
z = zipfile.ZipFile(zp)
out = {'zip_key': zk, 'members': len(z.namelist())}
db1s = [n for n in z.namelist() if n.lower().endswith('.db1') and 'xslib' not in n.lower()]
folder = None
for n in db1s:
    h = hashlib.sha256(z.read(n)).hexdigest()
    if h == sha:
        folder = n.rsplit('/', 1)[0] + '/'; out['db1'] = n
out['folder'] = folder
ENT = re.compile(rb'^#\d+\s*=\s*(IFC[A-Z]+)\s*\(', re.M)
for n in z.namelist():
    if folder and not n.startswith(folder):
        continue
    ln = n.lower()
    if ln.endswith('.ifc'):
        c = collections.Counter(); hdr = b''
        with z.open(n) as f:
            buf = b''
            first = True
            while True:
                b = f.read(1 << 24)
                if not b:
                    break
                if first:
                    hdr = b[:1500]; first = False
                b = buf + b
                k = b.rfind(b'\n')
                for m in ENT.finditer(b[:k]):
                    c[m.group(1).decode()] += 1
                buf = b[k:]
            for m in ENT.finditer(buf):
                c[m.group(1).decode()] += 1
        keep = {k: v for k, v in c.items() if k in ('IFCBEAM', 'IFCCOLUMN', 'IFCMEMBER', 'IFCPLATE', 'IFCMECHANICALFASTENER', 'IFCFASTENER',
                                                     'IFCBUILDINGELEMENTPROXY', 'IFCDISCRETEACCESSORY', 'IFCELEMENTASSEMBLY', 'IFCFOOTING',
                                                     'IFCSLAB', 'IFCWALL', 'IFCWALLSTANDARDCASE', 'IFCOPENINGELEMENT', 'IFCPROJECT')}
        out.setdefault('ifc', {})[n] = {'bytes': z.getinfo(n).file_size, 'classes': keep, 'header': hdr.decode('latin-1', 'replace')[:900],
                                        'parts_like': sum(v for k, v in keep.items() if k in ('IFCBEAM', 'IFCCOLUMN', 'IFCMEMBER', 'IFCPLATE', 'IFCBUILDINGELEMENTPROXY', 'IFCDISCRETEACCESSORY'))}
    elif ln.endswith(('.rpt', '.xsr', '.csv')):
        t = z.read(n).decode('latin-1', 'replace')
        out.setdefault('reports', {})[n] = {'bytes': len(t), 'lines': t.count('\n'), 'head': t[:1200]}
json.dump(out, open(outp, 'w'), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != 'reports'}, indent=1)[:5000])
for n, r in (out.get('reports') or {}).items():
    print('REPORT', n, r['bytes'], r['lines']); print(r['head'][:800])
shutil.rmtree(tmp)
