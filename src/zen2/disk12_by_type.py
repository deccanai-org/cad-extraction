"""disk12_by_type.py - per file type raw and unique (distinct sha256) counts for Disk-1, Disk-2 and both combined,
from the Disk-1/2 union index. Output: zentitude-data-4/_state/stats/disk12_by_type.json"""
import sqlite3, json, time, collections, boto3
c = sqlite3.connect('/work/idx/union.sqlite')
disk_of = dict(c.execute('SELECT digest, disk FROM archives'))
raw = collections.defaultdict(lambda: collections.Counter())
for disk, bucket, v in c.execute('SELECT disk, bucket, value FROM baseline_raw'):
    raw[bucket][disk] += v or 0
for dg, bucket, v in c.execute('SELECT digest, bucket, value FROM archive_raw'):
    raw[bucket][disk_of.get(dg, '?')] += v or 0
out = {}
buckets = [b for (b,) in c.execute("SELECT DISTINCT bucket FROM digests WHERE kind='sha'")]
for b in buckets:
    u1 = c.execute("SELECT COUNT(DISTINCT digest) FROM digests WHERE kind='sha' AND disk='Disk-1' AND bucket=?", (b,)).fetchone()[0]
    u2 = c.execute("SELECT COUNT(DISTINCT digest) FROM digests WHERE kind='sha' AND disk='Disk-2' AND bucket=?", (b,)).fetchone()[0]
    uc = c.execute("SELECT COUNT(DISTINCT digest) FROM digests WHERE kind='sha' AND bucket=?", (b,)).fetchone()[0]
    key = b[1:] if b.startswith('.') else b
    out[key] = {'disk1_raw': raw[b].get('Disk-1', 0), 'disk2_raw': raw[b].get('Disk-2', 0), 'disk1_unique': u1, 'disk2_unique': u2, 'combined_unique': uc}
weak = dict(c.execute("SELECT disk, COUNT(*) FROM digests WHERE kind='weak' GROUP BY disk").fetchall())
doc = {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'by_type': out, 'weak_hash_rows': weak,
       'note': 'Disk-1/Disk-2 were extracted for CAD types only (pdf dxf dwg dg dpm stp step ifc db1 sat nc1 ...); unique = distinct sha256; '
               'archives from the early run with only a weak hash are not in the sha256 counts',
       'pdf_classes_rule': "Disk-1/2 'cad_pdf'/'other_pdf' come from that run's own PDF classifier"}
boto3.client('s3', region_name='ap-south-1').put_object(Bucket='annotationprod', Key='cad-disk-extract/zentitude-data-4/_state/stats/disk12_by_type.json',
                                                         Body=json.dumps(doc, indent=1).encode(), ContentType='application/json')
for k in sorted(out, key=lambda k: -out[k]['combined_unique']): print(k, out[k])
print('weak', weak)
