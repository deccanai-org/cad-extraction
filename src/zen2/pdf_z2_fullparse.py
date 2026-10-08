"""pdf_z2_fullparse.py - classify the Zenitude-data-2 PDFs still 'unknown' in /work/pdfcache/classes.sqlite by reading the whole local
file with pdfinfo (same rule as pdf_classify.py / pdf_fullparse.py). Files: /work/in/src (drawing set), /work/out/extracted."""
import os, re, sqlite3, subprocess, collections
from concurrent.futures import ThreadPoolExecutor
src = open('/work/pdf_classify.py').read()
ns = {'re': re}
exec(src[src.index('CAD = re.compile'):src.index('def classify')], ns)
CAD, DOC = ns['CAD'], ns['DOC']
SIZE = re.compile(r'Page\s+\d+\s+size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts')
db = sqlite3.connect('/work/pdfcache/classes.sqlite', timeout=120)
unknown = {s for (s,) in db.execute("SELECT sha FROM cls WHERE cls='unknown'")}
paths = {}
for tsv, root in (('/work/out/json/source_sha256.tsv', '/work/in/src'), ('/work/out/json/extracted_sha256.tsv', '/work/out/extracted')):
    for line in open(tsv, errors='replace'):
        p = line.rstrip('\n').split('\t', 1)
        if len(p) == 2 and p[1].lower().endswith('.pdf') and p[0] in unknown:
            paths.setdefault(p[0], os.path.join(root, p[1]))
print('data-2 unknown PDFs:', len(paths), flush=True)


def one(item):
    sha, path = item
    if not os.path.exists(path):
        return sha, 'unknown', 'full:no_copy'
    if os.path.getsize(path) == 0:
        return sha, 'unknown', 'full:zero_bytes'
    r = subprocess.run(['pdfinfo', '-f', '1', '-l', '5', path], capture_output=True, timeout=120)
    out, err = r.stdout.decode('latin-1'), r.stderr.decode('latin-1')
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
    return sha, 'unknown', 'full:encrypted' if 'password' in err.lower() or 'encrypt' in err.lower() else 'full:no_pages'


with ThreadPoolExecutor(16) as ex:
    rows = list(ex.map(one, paths.items()))
db.executemany('INSERT OR REPLACE INTO cls VALUES (?,?,?)', rows); db.commit()
print(collections.Counter((c, w) for _, c, w in rows), flush=True)
