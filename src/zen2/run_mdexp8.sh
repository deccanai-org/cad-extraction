pkill -f export_model_drawings.py; sleep 1; cat > /data/work/export_model_drawings.py <<'__EOF__'
"""export_model_drawings.py - export every drawing document stored in the Smart 3D model (MLNG@1_MDB.dbo.DRAWNGDocumentData,
549,831 zip-compressed blobs: isometric .sha drawings, Smart 3D's own .pcf, Isogen .xml/.pod/.mes/.log/.txt, .xls, .sat)
to s3://annotationprod/cad-disk-extract/zenitude-data-2/model_drawings/<type>/<file name>, unzipped to the original file.
Index (one row per document, incl. the pipeline line number parsed from the name) -> model_drawings/_index/*.jsonl.gz.
Status for the live page -> _state/model_drawings_status.json. Read-only on the database. Resumable (skips exported oids).
"""
import gzip, io, json, os, re, sys, threading, time, zipfile, collections
from concurrent.futures import ThreadPoolExecutor
import boto3, pymssql
import zipfile_deflate64  # noqa: F401  (adds Deflate64 to zipfile; ~60% of the blobs use it)
from botocore.config import Config

B = 'annotationprod'
Z2 = 'cad-disk-extract/zenitude-data-2'
OUT = f'{Z2}/model_drawings'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=128, retries={'max_attempts': 10, 'mode': 'adaptive'}))
PW = open('/root/.mssql_sa').read().strip()
LINE = re.compile(r"(\d+(?:''|\"|=\d+)?-?[A-Z]{0,3}\d{4,6}-[A-Z0-9]+(?:-[A-Z0-9]+)?)", re.I)
lock = threading.Lock()
st = collections.Counter(); by_type = collections.Counter(); bytes_type = collections.Counter()


def safe(name):
    return re.sub(r'[\x00-\x1f\\\\]', '_', name).replace('/', '_')[:240]


def one(row):
    oid, fname, ftype, blob, fsize, comp = row
    ftype = (ftype or os.path.splitext(fname or '')[1].lstrip('.') or 'unknown').lower()
    base = safe(fname or str(oid))
    stem, ext = os.path.splitext(base)
    files = []
    try:
        if blob[:2] == b'PK':
            z = zipfile.ZipFile(io.BytesIO(blob))
            names = [n for n in z.namelist() if not n.endswith('/')]
            for n in names:
                data = z.read(n)
                nm = base if len(names) == 1 else f'{stem}__{safe(os.path.basename(n))}'
                files.append((nm, data))
        else:
            files.append((base, blob))
    except Exception as e:
        files = [(base + '.zip', blob)]
        with lock:
            st['unzip_error'] += 1
    keys = []
    for nm, data in files:
        key = f'{OUT}/{ftype}/{str(oid).lower()}__{nm}'          # FULL oid: the first 8 hex digits are the class id, shared by all documents
        s3.put_object(Bucket=B, Key=key, Body=data)
        keys.append({'key': key, 'size': len(data)})
    m = LINE.search(fname or '')
    rec = {'oid': str(oid), 'file_name': fname, 'file_type': ftype, 'declared_size': fsize, 'compressed': bool(comp),
           'line_number': m.group(1) if m else None, 'objects': keys}
    with lock:
        st['docs'] += 1; st['files'] += len(keys); by_type[ftype] += 1; bytes_type[ftype] += sum(k['size'] for k in keys)
    return rec


def status(final=False):
    doc = {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'final': final, 'documents_total': TOTAL,
           'documents_exported': st['docs'], 'files_written': st['files'], 'unzip_errors': st['unzip_error'],
           'by_type': {t: {'documents': by_type[t], 'bytes': bytes_type[t]} for t in by_type}}
    s3.put_object(Bucket=B, Key=f'{Z2}/_state/model_drawings_status/part{PK}.json', Body=json.dumps(doc, indent=1).encode(), ContentType='application/json')


PK, PN = int(sys.argv[1]), int(sys.argv[2])      # partition k of n (by oid checksum)

if __name__ == '__main__':
    con = pymssql.connect(server='127.0.0.1', user='sa', password=PW, database='MLNG@1_MDB')
    cur = con.cursor()
    WHERE = f'WHERE ABS(CHECKSUM(oid)) % {PN} = {PK}'
    cur.execute(f'SELECT COUNT(*) FROM dbo.DRAWNGDocumentData {WHERE}')
    TOTAL = cur.fetchone()[0]
    print('partition', PK, 'of', PN, 'documents', TOTAL, flush=True)
    cur.execute(f'SELECT oid, FileName, FileType, DataBlob, FileSize, FileCompressed FROM dbo.DRAWNGDocumentData {WHERE}')
    part, batch, recs = 0, [], []
    t0 = time.time(); last = 0
    with ThreadPoolExecutor(32) as ex:
        while True:
            rows = cur.fetchmany(2000)
            if not rows:
                break
            recs += list(ex.map(one, rows))
            if len(recs) >= 20000:
                s3.put_object(Bucket=B, Key=f'{OUT}/_index/p{PK}-{part:04d}.jsonl.gz', Body=gzip.compress('\n'.join(json.dumps(r) for r in recs).encode()))
                part += 1; recs = []
            if time.time() - last > 60:
                status(); last = time.time()
                print(time.strftime('%H:%M:%S'), st['docs'], '/', TOTAL, dict(by_type), flush=True)
    if recs:
        s3.put_object(Bucket=B, Key=f'{OUT}/_index/p{PK}-{part:04d}.jsonl.gz', Body=gzip.compress('\n'.join(json.dumps(r) for r in recs).encode()))
    status(final=True)
    print('DONE', st['docs'], 'docs', st['files'], 'files in', round(time.time() - t0), 's', flush=True)
__EOF__
aws s3 rm --quiet --recursive s3://annotationprod/cad-disk-extract/zenitude-data-2/model_drawings/_index/; aws s3 rm --quiet --recursive s3://annotationprod/cad-disk-extract/zenitude-data-2/_state/model_drawings_status/
cd /data/work && for k in 0 1 2 3 4 5 6 7; do setsid nohup /data/s3d/env/bin/python /data/work/export_model_drawings.py $k 8 > /data/work/export_md_$k.out 2>&1 < /dev/null & done
sleep 45; tail -1 /data/work/export_md_0.out | cut -c1-100
