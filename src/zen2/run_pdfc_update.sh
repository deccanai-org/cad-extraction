cat > /work/pdf_classify.py <<'__EOF__'
"""pdf_classify.py - CAD vs non-CAD PDF classification for both new disks (runs in-region on cad-zen2-files, loops).

For every UNIQUE PDF (by sha256) read only the first and last 64 KB (range GETs for S3 objects, local reads for data-2) and
classify from Producer/Creator/XMP CreatorTool and page size:
  cad      : producer/creator is a CAD/plotting tool, or largest page side >= 1190 pt (A3 or larger)
  document : office/scanner/report producer, or a smaller page
  unknown  : metadata and page boxes not readable in head/tail (compressed object streams)
Raw counts follow the manifests (every path), unique counts the distinct sha256.
Outputs: <disk>/_state/stats/pdf_classes.json   (cache: /work/pdfcache)
"""
import gzip, json, os, re, sqlite3, time, collections
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B = 'annotationprod'
Z4 = 'cad-disk-extract/zentitude-data-4'
Z2 = 'cad-disk-extract/zenitude-data-2'
C = '/work/pdfcache'
os.makedirs(C, exist_ok=True)
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=300, retries={'max_attempts': 8, 'mode': 'adaptive'}))
db = sqlite3.connect(f'{C}/classes.sqlite', check_same_thread=False)
db.execute('CREATE TABLE IF NOT EXISTS cls (sha TEXT PRIMARY KEY, cls TEXT, why TEXT)')

CAD = re.compile(rb'autocad|autodesk|acad|dwg|tekla|sds ?/ ?2|sds2|design data|microstation|bentley|revit|navisworks|solidworks|'
                 rb'inventor|smartplant|smart ?3d|intergraph|hexagon|smartsketch|isogen|aveva|pdms|e3d|cadworx|bricscad|draftsight|'
                 rb'progecad|zwcad|gstarcad|advance steel|prosteel|strucad|designjet|plotwave|hpgl|archicad|vectorworks|sketchup|'
                 rb'rhino|catia|creo|teigha|open design|dwg ?true ?view|trueview|volo view|cadpdf|pdf-?xchange for autocad', re.I)
DOC = re.compile(rb'microsoft|word|excel|powerpoint|outlook|pdfmaker|libreoffice|openoffice|quartz|skia|chrome|wkhtml|scan|canon|'
                 rb'xerox|ricoh|konica|kyocera|sharp|epson|brother|lexmark|toshiba|imagerunner|crystal reports|reportlab|itext|'
                 rb'jasper|fpdf|tcpdf|nitro|foxit phantom|abbyy|omnipage|paperport|mfp', re.I)
META = re.compile(rb'/(?:Producer|Creator)\s*\((.{0,300}?)\)|<(?:pdf:Producer|xmp:CreatorTool)>(.{0,300}?)</', re.S)
BOX = re.compile(rb'/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\]')


def classify(head, tail):
    blob = head + tail
    meta = b' '.join((a or b) for a, b in META.findall(blob))
    dims = []
    for m in BOX.findall(blob):
        try:
            x0, y0, x1, y1 = map(float, m)
            dims.append(max(abs(x1 - x0), abs(y1 - y0)))
        except ValueError:
            pass
    big = max(dims) if dims else 0
    if meta and CAD.search(meta):
        return 'cad', 'producer'
    if big >= 1190:
        return 'cad', 'page>=A3'
    if meta and DOC.search(meta):
        return 'document', 'producer'
    if big > 0:
        return 'document', 'page<A3'
    return 'unknown', ''


def s3_class(key):
    if not key.startswith('cad-disk-extract/'):
        return 'unknown', 'no_object'          # pointer (content held by another archive / Disk-1/2)
    try:
        head = s3.get_object(Bucket=B, Key=key, Range='bytes=0-65535')['Body'].read()
        tail = s3.get_object(Bucket=B, Key=key, Range='bytes=-65536')['Body'].read() if len(head) == 65536 else b''
        return classify(head, tail)
    except Exception as e:
        return 'unknown', 'read_error'


def local_class(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(65536)
            f.seek(0, 2); n = f.tell()
            tail = b''
            if n > 65536:
                f.seek(max(0, n - 65536)); tail = f.read()
        return classify(head, tail)
    except Exception:
        return 'unknown', 'read_error'


def known(shas):
    out = {}
    shas = list(shas)
    for i in range(0, len(shas), 900):
        q = shas[i:i + 900]
        for sha, c in db.execute(f'SELECT sha, cls FROM cls WHERE sha IN ({",".join("?" * len(q))})', q):
            out[sha] = c
    return out


def save(rows):
    db.executemany('INSERT OR REPLACE INTO cls VALUES (?,?,?)', rows)
    db.commit()


def z4_pdfs():
    """[(sha, stored_key)] for every PDF path in every finished archive (manifest cache per archive)."""
    ids = set()
    tok = None
    while True:
        kw = dict(Bucket=B, Prefix=f'{Z4}/_state/manifests/')
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        ids.update(o['Key'].rsplit('/', 1)[-1].split('.')[0] for o in r.get('Contents', []))
        if not r.get('IsTruncated'):
            break
        tok = r['NextContinuationToken']
    out = []
    for jid in ids:
        cf = f'{C}/{jid}.json'
        if not os.path.exists(cf):
            body = gzip.decompress(s3.get_object(Bucket=B, Key=f'{Z4}/_state/manifests/{jid}.jsonl.gz')['Body'].read())
            rows = []
            for line in body.splitlines():
                if line:
                    e = json.loads(line)
                    if e['path'].lower().endswith('.pdf') and e['size'] > 0:
                        rows.append([e['sha256'], e['key'], e.get('pdf_class')])
            json.dump(rows, open(cf, 'w'))
        out += [r if len(r) == 3 else r + [None] for r in json.load(open(cf))]
    return out, len(ids)


import array as _array, bisect as _bisect
_IDX = _array.array('Q')


def in_disk12(sha):
    if not len(_IDX):
        try:
            _IDX.frombytes(open('/work/idx/disk12_sha64.bin', 'rb').read())
        except Exception:
            return False
    h = int(sha[:16], 16); i = _bisect.bisect_left(_IDX, h)
    return i < len(_IDX) and _IDX[i] == h


def tally(pairs, cmap, with_new=False):
    raw = collections.Counter(cmap.get(sha, 'pending') for sha, _ in pairs)
    shas = {s for s, _ in pairs}
    uniq = collections.Counter(cmap.get(sha, 'pending') for sha in shas)
    out = {c: {'raw': raw.get(c, 0), 'unique': uniq.get(c, 0)} for c in ('cad', 'document', 'unknown', 'pending')}
    if with_new:   # content not already stored by Disk-1/Disk-2
        new_sh = {s for s in shas if not in_disk12(s)}
        nraw = collections.Counter(cmap.get(sha, 'pending') for sha, _ in pairs if sha in new_sh)
        nuni = collections.Counter(cmap.get(sha, 'pending') for sha in new_sh)
        for c in out:
            out[c].update(new_raw=nraw.get(c, 0), new_unique=nuni.get(c, 0))
    return out


def z4_round():
    rows, n_arch = z4_pdfs()
    pairs = [(sha, key) for sha, key, _ in rows]
    first, given = {}, {}
    for sha, key, cls in rows:
        if cls:
            given[sha] = cls
        if key.startswith('cad-disk-extract/') or sha not in first:
            if sha not in first or not first[sha].startswith('cad-disk-extract/'):
                first[sha] = key
    cmap = known(first)
    new_given = [(sha, c, 'worker') for sha, c in given.items() if sha not in cmap]
    if new_given:
        save(new_given); cmap.update({sha: c for sha, c, _ in new_given})
    todo = [(sha, key) for sha, key in first.items() if sha not in cmap]
    for i in range(0, len(todo), 8000):
        chunk = todo[i:i + 8000]
        with ThreadPoolExecutor(256) as ex:
            res = list(ex.map(lambda sk: s3_class(sk[1]), chunk))
        save([(sk[0], c, w) for sk, (c, w) in zip(chunk, res)])
        cmap.update({sk[0]: c for sk, (c, w) in zip(chunk, res)})
    out = {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'archives_counted': n_arch,
           'pdf_paths': len(pairs), 'pdf_unique': len(first), 'classes': tally(pairs, cmap, with_new=True),
           'rule': 'cad = CAD/plot producer or page >= A3; document = office/scanner producer or smaller page; unknown = no readable metadata'}
    s3.put_object(Bucket=B, Key=f'{Z4}/_state/stats/pdf_classes.json', Body=json.dumps(out).encode(), ContentType='application/json')
    return out


def z2_round():
    out = {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    for name, tsv, root in (('drawing_set', '/work/out/json/source_sha256.tsv', '/work/in/src'),
                            ('extracted', '/work/out/json/extracted_sha256.tsv', '/work/out/extracted')):
        if not os.path.exists(tsv):
            continue
        pairs = []
        for line in open(tsv, errors='replace'):
            p = line.rstrip('\n').split('\t', 1)
            if len(p) == 2 and p[1].lower().endswith('.pdf'):
                pairs.append((p[0], os.path.join(root, p[1])))
        first = {}
        for sha, path in pairs:
            first.setdefault(sha, path)
        cmap = known(first)
        todo = [(s, p) for s, p in first.items() if s not in cmap]
        with ThreadPoolExecutor(32) as ex:
            res = list(ex.map(lambda sp: local_class(sp[1]), todo))
        save([(sp[0], c, w) for sp, (c, w) in zip(todo, res)])
        cmap.update({sp[0]: c for sp, (c, w) in zip(todo, res)})
        out[name] = {'pdf_paths': len(pairs), 'pdf_unique': len(first), 'classes': tally(pairs, cmap)}
    s3.put_object(Bucket=B, Key=f'{Z2}/_state/stats/pdf_classes.json', Body=json.dumps(out).encode(), ContentType='application/json')
    return out


if __name__ == '__main__':
    while True:
        t0 = time.time()
        try:
            a = z4_round()
            z2_round()
            print(time.strftime('%H:%M:%S'), 'z4 pdf paths', a['pdf_paths'], 'unique', a['pdf_unique'], a['classes'], 'in', round(time.time() - t0), 's', flush=True)
        except Exception as e:
            print(time.strftime('%H:%M:%S'), 'error', repr(e)[:300], flush=True)
        time.sleep(max(10, 120 - (time.time() - t0)))
__EOF__
pgrep -fa "pdf_classify|pdf_disk12" | cut -c1-80
