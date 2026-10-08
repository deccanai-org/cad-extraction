#!/usr/bin/env python3
"""probe4: census check against Tekla's own exports for 5b33 (MAGNETATION_GRINDING_CIRCUIT_MASTER, Tekla 7.24 db1):
GUID join of the python decoder's part list (decoded_parts: [tekla_id, profile, category, status, how, guid, n_cuts]) with
the GlobalIds of Tekla's own IFC exports (out1.ifc 2013-12-07, out2.ifc 2013-11-15) + Tekla-id join with the model's own
imports/*.csv (ID, PRELIM_MARK). Read-only. usage: probe4.py ZIP_KEY DB1_SHA DECODED_PARTS_KEY OUT_JSON"""
import os, sys, io, re, json, gzip, zipfile, collections, tempfile, shutil, csv
import boto3
B = 'bim-proprietary-data'
s3 = boto3.client('s3', region_name='ap-south-1')
zk, sha, dpk, outp = sys.argv[1:5]
parts = json.load(gzip.open(io.BytesIO(s3.get_object(Bucket=B, Key=dpk)['Body'].read()), 'rt'))
tmp = tempfile.mkdtemp(dir='/work/agentwork/coverage-regression')
zp = os.path.join(tmp, 'm.zip'); s3.download_file(B, zk, zp)
z = zipfile.ZipFile(zp)
folder = 'MAGNETATION_GRINDING_CIRCUIT_MASTER/'
RX = re.compile(rb"^#\d+\s*=\s*(IFCBEAM|IFCCOLUMN|IFCPLATE|IFCMEMBER|IFCBUILDINGELEMENTPROXY|IFCMECHANICALFASTENER|IFCSLAB)\s*\(\s*'([^']{22})'", re.M)
ifc = {}
for n in ('out1.ifc', 'out2.ifc', 'out.ifc'):
    g = {}
    with z.open(folder + n) as f:
        data = f.read()
    for m in RX.finditer(data):
        g[m.group(2).decode()] = m.group(1).decode()
    ifc[n] = g
dec = {p[5]: p for p in parts if p[5]}
out = {'decoder_parts': len(parts), 'decoder_with_guid': len(dec), 'by_cat': dict(collections.Counter(p[2] for p in parts))}
for n, g in ifc.items():
    inter = set(g) & set(dec)
    out[n] = {'ifc_elements': len(g), 'ifc_by_class': dict(collections.Counter(g.values())), 'guid_in_decoder': len(inter),
              'ifc_not_in_decoder': len(set(g) - set(dec)),
              'decoder_in_ifc_by_cat': dict(collections.Counter(dec[x][2] for x in inter)),
              'decoder_written_in_ifc': sum(1 for x in inter if dec[x][3] == 'written')}
allg = set().union(*[set(g) for g in ifc.values()])
notin = [p for p in parts if p[5] and p[5] not in allg and p[2] != 'feature']
out['decoder_nonfeature_not_in_any_export'] = len(notin)
out['not_in_export_by_cat_profile'] = [[c, pr, k] for (c, pr), k in collections.Counter((p[2], p[1]) for p in notin).most_common(15)]
# Tekla ids from the model's own import lists
ids = set()
for n in z.namelist():
    if n.startswith(folder + 'imports/') and n.lower().endswith('.csv'):
        for r in csv.DictReader(io.StringIO(z.read(n).decode('latin-1', 'replace'))):
            try:
                ids.add(int((r.get('ID') or '').strip()))
            except ValueError:
                pass
decids = {int(p[0]) for p in parts if str(p[0]).lstrip('-').isdigit()}
out['import_csv_ids'] = len(ids); out['import_ids_in_decoder'] = len(ids & decids)
json.dump(out, open(outp, 'w'), indent=1)
print(json.dumps(out, indent=1))
shutil.rmtree(tmp)
