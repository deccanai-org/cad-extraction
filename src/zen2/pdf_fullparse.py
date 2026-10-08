"""pdf_fullparse.py - last pass for data-4 PDFs still 'unknown' in /work/pdfcache/classes.sqlite: download the WHOLE file and read
Producer/Creator and page sizes with poppler's pdfinfo (the head/tail 64 KB scan misses PDFs whose page tree sits in compressed object
streams mid-file). Same rule as pdf_classify.py: CAD producer or page >= A3 -> cad; office/scanner producer or smaller page -> document.
Copies are found in the per-archive manifest caches (real keys) or via the data-4 sha marker. why = 'full:<reason>'."""
import glob, json, os, re, sqlite3, subprocess, tempfile, collections, threading, time
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B, Z4 = 'annotationprod', 'cad-disk-extract/zentitude-data-4'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=100, connect_timeout=20, read_timeout=120,
                                                                 retries={'max_attempts': 5, 'mode': 'standard'}))
src = open('/work/pdf_classify.py').read()
ns = {'re': re}
exec(src[src.index('CAD = re.compile'):src.index('def classify')], ns)
CAD, DOC = ns['CAD'], ns['DOC']
db = sqlite3.connect('/work/pdfcache/classes.sqlite', timeout=120, check_same_thread=False)
todo = {sha for (sha,) in db.execute("SELECT sha FROM cls WHERE cls='unknown'")}
print('unknown shas:', len(todo), flush=True)
keys = {}
for f in glob.glob('/work/pdfcache/*.json'):
    try:
        for sha, key, *_ in json.load(open(f)):
            if sha in todo and key.startswith('cad-disk-extract/'):
                keys.setdefault(sha, key)
    except Exception:
        pass
print('with a stored key in manifests:', len(keys), flush=True)
st = collections.Counter(); lock = threading.Lock()
SIZE = re.compile(r'Page\s+\d+\s+size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts')


def find_key(sha):
    if sha in keys:
        return keys[sha]
    try:
        k = s3.get_object(Bucket=B, Key=f'{Z4}/_state/sha/{sha[:2]}/{sha}')['Body'].read().decode().strip()
        return k if k.startswith('cad-disk-extract/') else None
    except Exception:
        return None


def one(sha):
    key = find_key(sha)
    if not key:
        return sha, 'unknown', 'full:no_copy'
    try:
        size = s3.head_object(Bucket=B, Key=key)['ContentLength']
        d = '/dev/shm' if size < 300_000_000 else '/work'
        with tempfile.NamedTemporaryFile(dir=d, suffix='.pdf') as t:
            s3.download_fileobj(B, key, t); t.flush()
            r = subprocess.run(['pdfinfo', '-f', '1', '-l', '5', t.name], capture_output=True, timeout=120)
        out, err = r.stdout.decode('latin-1'), r.stderr.decode('latin-1')
    except subprocess.TimeoutExpired:
        return sha, 'unknown', 'full:timeout'
    except Exception:
        return sha, 'unknown', 'full:read_error'
    meta = ' '.join(l.split(':', 1)[1].strip() for l in out.splitlines() if l.startswith(('Producer:', 'Creator:'))).encode('latin-1', 'replace')
    big = max([max(float(w), float(h)) for w, h in SIZE.findall(out)] or [0])
    if meta and CAD.search(meta):
        return sha, 'cad', 'full:producer'
    if big >= 1190:
        return sha, 'cad', 'full:page>=A3'
    if meta and DOC.search(meta):
        return sha, 'document', 'full:producer'
    if big > 0:
        return sha, 'document', 'full:page<A3'
    if 'Incorrect password' in err or 'encrypt' in err.lower():
        return sha, 'unknown', 'full:encrypted'
    return sha, 'unknown', 'full:not_a_pdf' if ('May not be a PDF' in err or 'Syntax Error' in err) else 'full:no_pages'


items = sorted(todo); t0 = time.time()
for i in range(0, len(items), 2000):
    with ThreadPoolExecutor(64) as ex:
        rows = list(ex.map(one, items[i:i + 2000]))
    db.executemany('INSERT OR REPLACE INTO cls VALUES (?,?,?)', rows); db.commit()
    st.update((c, w) for _, c, w in rows)
    print(time.strftime('%H:%M:%S'), i + len(rows), '/', len(items), round(time.time() - t0), 's', dict(st), flush=True)
print('DONE', db.execute('SELECT cls, COUNT(*) FROM cls GROUP BY cls').fetchall(), flush=True)
