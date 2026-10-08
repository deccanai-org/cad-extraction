#!/usr/bin/env python3
"""find_inputs.py - discover every ifcXML input (ISO 10303-28 IFC2x3 'iso_10303_28'/'uos', IFC4 'ifcXML', XML inside
.ifcZIP/.zip) in Zenitude data-3 and data-4.  Runs on an agent box (instance role: read bim + annotationprod, write
bim cad-disk-extract/*).  Read-only on all data; writes only below s3://bim/<OUT>/.

    find_inputs.py [phase ...]    phases: results manifests sniff report   (default: all, in that order)

results    every IFC pipeline result of data-3 (zenitude-data-3/_state/conv/ifc/results/) and data-4
           (zentitude-data-4/_state/conv/ifc/results/): rows whose reason is ifcxml_unsupported / not_step21 or whose
           format / schema says ifcxml  -> results_hits.json
manifests  every manifest of data-3 (5,992) and data-4 (1,499): rows whose path ends in .xml / .ifcxml / .ifczip /
           .ifcxml.gz / .ifcxml.zip (any case; archive members are rows of their own)  -> xml_rows_<ds>.jsonl.gz +
           per-dataset row totals (completeness proof against the scan summaries)
sniff      per distinct sha256 of those rows (+ the result hits): key resolved (stored key > src: > data-3 / data-4
           sha marker > data-4 disk12 dedup candidate), first 64 KB read (ranged GET) and the XML root / namespaces /
           ISO 10303-28 configuration classified; zip contents: every member listed and every XML member sniffed
           -> sniff.jsonl.gz
report     candidates.json (every distinct ifcXML content: sha, size, key, schema, container, member, paths) +
           summary.json (counts by class / root element; completeness numbers)
"""
import os, sys, re, io, json, gzip, zlib, time, zipfile, hashlib, collections, traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import boto3
from botocore.config import Config

B = 'bim-proprietary-data'
CB = 'annotationprod'
D3 = 'cad-disk-extract/zenitude-data-3'
D4 = 'cad-disk-extract/zentitude-data-4'
OUT = os.environ.get('FIND_OUT', 'cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml/find')
W = os.path.abspath(os.environ.get('FIND_WORK', 'find'))
NPROC = int(os.environ.get('FIND_PROCS', '14'))
NTHR = int(os.environ.get('FIND_THREADS', '32'))
EXTS = ('.xml', '.ifcxml', '.ifczip', '.ifcxml.gz', '.ifcxml.zip')
NEEDLES = (b'.xml"', b'.ifcxml"', b'.ifczip"', b'.ifcxml.gz"', b'.ifcxml.zip"')
_c = {}


def s3():
    if 'c' not in _c:
        _c['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(
            retries={'max_attempts': 30, 'mode': 'standard'}, max_pool_connections=96, read_timeout=300))
    return _c['c']


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def lst(bucket, prefix):
    out = []
    for pg in s3().get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        out.extend(pg.get('Contents', []))
    return out


def get_bytes(bucket, key, rng=None):
    kw = {'Bucket': bucket, 'Key': key}
    if rng:
        kw['Range'] = rng
    return s3().get_object(**kw)['Body'].read()


def get_text(bucket, key):
    try:
        return get_bytes(bucket, key).decode('utf-8', 'replace').strip()
    except Exception:
        return None


def put(path, key):
    s3().upload_file(path, B, f'{OUT}/{key}')


def put_json(obj, name):
    p = os.path.join(W, name)
    with open(p, 'w') as f:
        json.dump(obj, f, indent=1, default=str)
    put(p, name)


# ------------------------------------------------------------------------------------------------ results
def _result(args):
    ds, key = args
    try:
        r = json.loads(get_bytes(B, key))
    except Exception as e:
        return ds, key, None, str(e)[:200]
    return ds, key, r, None


def phase_results():
    jobs = []
    for ds, root in (('d3', D3), ('d4', D4)):
        ks = [o['Key'] for o in lst(B, f'{root}/_state/conv/ifc/results/') if o['Key'].endswith('.json')]
        log('results', ds, len(ks))
        jobs += [(ds, k) for k in ks]
    hits = []
    n = collections.Counter()
    reasons = collections.Counter()
    errs = []
    with ThreadPoolExecutor(NTHR) as ex:
        for ds, key, r, err in ex.map(_result, jobs):
            n[ds] += 1
            if r is None:
                errs.append([ds, key, err])
                continue
            reason = r.get('reason')
            reasons[(ds, r.get('status'), reason)] += 1
            blob = json.dumps({k: r.get(k) for k in ('reason', 'format', 'schema_in', 'kind', 'unzipped', 'zip_members',
                                                      'detail')}, default=str).lower()
            if reason in ('ifcxml_unsupported', 'not_step21') or 'ifcxml' in blob or r.get('format') == 'ifcxml':
                hits.append({'ds': ds, 'result_key': key, 'sha256': r.get('sha256') or key.rsplit('/', 1)[-1][:-5],
                             'status': r.get('status'), 'reason': reason, 'format': r.get('format'), 'kind': r.get('kind'),
                             'input_key': r.get('input_key'), 'in_bytes': r.get('in_bytes'), 'unzipped': r.get('unzipped'),
                             'zip_members': r.get('zip_members'), 'detail': r.get('detail'),
                             'paths_sample': r.get('paths_sample')})
    rep = {'results_read': dict(n), 'errors': errs[:50], 'n_errors': len(errs), 'hits': len(hits),
           'hits_by': dict(collections.Counter('%s %s %s' % (h['ds'], h['reason'], h['format']) for h in hits)),
           'reasons': {'%s|%s|%s' % k: v for k, v in sorted(reasons.items(), key=lambda x: -x[1])}}
    put_json({'summary': rep, 'hits': hits}, 'results_hits.json')
    log('results done', json.dumps(rep['hits_by']), 'read', dict(n), 'errors', len(errs))


# ------------------------------------------------------------------------------------------------ manifests
def scan_manifest(args):
    ds, key = args
    jid = key.rsplit('/', 1)[-1].split('.')[0]
    for att in range(5):
        try:
            body = s3().get_object(Bucket=B, Key=key)['Body']
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            carry = b''
            nrows = 0
            hits = []
            done = False
            while not done:
                raw = body.read(8 << 20)
                parts = []
                if not raw:
                    parts.append(d.flush())
                    done = True
                while raw:
                    parts.append(d.decompress(raw))
                    if d.eof and d.unused_data:
                        raw = d.unused_data
                        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    else:
                        raw = b''
                data = carry + b''.join(parts)
                if not done:
                    cut = data.rfind(b'\n')
                    if cut < 0:
                        carry = data
                        continue
                    carry = data[cut + 1:]
                    data = data[:cut + 1]
                else:
                    carry = b''
                    if data and not data.endswith(b'\n'):
                        data += b'\n'
                nrows += data.count(b'\n')
                low = data.lower()
                seen = set()
                for nd in NEEDLES:
                    i = low.find(nd)
                    while i >= 0:
                        a = data.rfind(b'\n', 0, i) + 1
                        z = data.find(b'\n', i)
                        if z < 0:
                            z = len(data)
                        if a not in seen:
                            seen.add(a)
                            try:
                                e = json.loads(data[a:z])
                                if (e.get('path') or '').lower().endswith(EXTS):
                                    e['job'] = jid
                                    e['ds'] = ds
                                    hits.append(e)
                            except Exception:
                                pass
                        i = low.find(nd, z)
            return ds, jid, nrows, hits, None
        except Exception as ex:
            if att == 4:
                return ds, jid, -1, [], '%s: %s' % (type(ex).__name__, str(ex)[:200])
            time.sleep(3 * (att + 1))


def phase_manifests():
    keys = []
    for ds, root in (('d3', D3), ('d4', D4)):
        ms = [(o['Key'], o['Size']) for o in lst(B, f'{root}/_state/manifests/') if o['Key'].endswith('.jsonl.gz')]
        log('manifests', ds, len(ms), 'bytes', sum(s for _, s in ms))
        keys += [(ds, k, s) for k, s in ms]
    keys.sort(key=lambda x: -x[2])
    rows = collections.Counter()
    nman = collections.Counter()
    errs = []
    outs = {ds: gzip.open(os.path.join(W, f'xml_rows_{ds}.jsonl.gz'), 'wt') for ds in ('d3', 'd4')}
    nh = collections.Counter()
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(NPROC) as ex:
        for ds, jid, n, hits, err in ex.map(scan_manifest, [(ds, k) for ds, k, _ in keys], chunksize=1):
            done += 1
            if err:
                errs.append([ds, jid, err])
            else:
                rows[ds] += n
                nman[ds] += 1
            for e in hits:
                outs[ds].write(json.dumps(e) + '\n')
            nh[ds] += len(hits)
            if done % 250 == 0 or done == len(keys):
                log(f'manifests {done}/{len(keys)} rows={dict(rows)} hits={dict(nh)} errors={len(errs)} {time.time() - t0:.0f}s')
    for f in outs.values():
        f.close()
    for ds in ('d3', 'd4'):
        put(os.path.join(W, f'xml_rows_{ds}.jsonl.gz'), f'xml_rows_{ds}.jsonl.gz')
    put_json({'manifests_listed': dict(collections.Counter(ds for ds, _, _ in keys)), 'manifests_scanned': dict(nman),
              'rows_scanned': dict(rows), 'hits': dict(nh), 'errors': errs, 'sec': round(time.time() - t0)},
             'manifest_scan.json')


# ------------------------------------------------------------------------------------------------ sniff
RX_ROOT = re.compile(r'<([A-Za-z_][\w.\-]*:)?([A-Za-z_][\w.\-]*)[\s>/]')


def classify_head(b):
    """first bytes of a file -> dict(kind, root, schema, ns, cfg)"""
    if b[:4] == b'PK\x03\x04':
        return {'kind': 'zip'}
    if b[:2] == b'\x1f\x8b':
        return {'kind': 'gzip'}
    enc = 'utf-8'
    if b[:2] in (b'\xff\xfe', b'\xfe\xff'):
        enc = 'utf-16'
    elif b[:3] == b'\xef\xbb\xbf':
        b = b[3:]
    h = b.decode(enc, 'replace')
    if enc == 'utf-8' and '\x00' in h[:200]:            # UTF-16 without BOM
        try:
            h = b.decode('utf-16-le' if b[1:2] == b'\x00' else 'utf-16-be', 'replace')
        except Exception:
            pass
    body = re.sub(r'<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>', '', h, flags=re.S).lstrip()
    if not body.startswith('<'):
        if 'ISO-10303-21' in h[:4096]:
            return {'kind': 'spf'}
        return {'kind': 'not_xml', 'head': h[:40]}
    m = RX_ROOT.search(body[:4096])
    root = m.group(2) if m else None
    ns = re.findall(r'xmlns(?::[\w.\-]+)?\s*=\s*["\']([^"\']*)["\']', h[:16384])
    cfg = re.findall(r'configuration\s*=\s*["\']([^"\']*)["\']', h[:16384])
    sl = re.findall(r'schemaLocation\s*=\s*["\']([^"\']*)["\']', h[:16384])
    low = ' '.join(ns + cfg + sl).lower()
    schema = None
    for c in cfg + ns + sl:
        cl = c.lower()
        if 'ifc4x3' in cl or 'ifc4_3' in cl:
            schema = 'IFC4X3'
        elif re.search(r'ifc4(?!\d)', cl) and 'ifc2x' not in cl:
            schema = 'IFC4'
        elif 'ifc2x3' in cl:
            schema = 'IFC2X3'
        elif 'ifc2x2' in cl:
            schema = 'IFC2X2'
        elif 'ifc2x_' in cl or cl.endswith('ifc2x'):
            schema = 'IFC2X'
        if schema:
            break
    r = {'kind': 'xml', 'root': root, 'schema': schema, 'ns': ns[:6], 'cfg': cfg[:2]}
    if root in ('iso_10303_28', 'uos') or (root or '').lower() == 'ifcxml':
        r['kind'] = 'ifcxml'
    elif 'iso_10303_28' in low or 'ifcxml' in low or 'buildingsmart' in low or 'iai-international' in low or \
            re.search(r'ifc2x|ifc4', low):
        r['kind'] = 'xml_ifc_namespace_other_root'
    elif root and root.lower().startswith('ifc'):
        r['kind'] = 'xml_ifc_root_no_namespace'
    return r


D12MAP = {}


def load_d12(need):
    """data-4 disk12 dedup candidates (dry run: the data-4 stored object usually still exists) -> sha -> key"""
    ks = [o['Key'] for o in lst(B, f'{D4}/_state/dedup_disk12/candidates/') if o['Key'].endswith('.jsonl.gz')]

    def one(k):
        out = {}
        try:
            for line in gzip.decompress(get_bytes(B, k)).splitlines():
                i = line.find(b'"sha256": "')
                if i < 0:
                    continue
                h = line[i + 11:i + 75].decode()
                if h in need:
                    e = json.loads(line)
                    out.setdefault(h, e['key'])
        except Exception:
            pass
        return out
    with ThreadPoolExecutor(NTHR) as ex:
        for part in ex.map(one, ks):
            for h, k in part.items():
                D12MAP.setdefault(h, k)
    log('d12 candidates', len(ks), 'mapped', len(D12MAP))


def exists(key):
    try:
        s3().head_object(Bucket=B, Key=key)
        return True
    except Exception:
        return False


def resolve(sha, keys):
    """-> (key, how) for one content; keys = the manifest keys seen for it"""
    for k in keys:
        if k.startswith('cad-disk-extract/') and exists(k):
            return k, 'stored'
    for k in keys:
        if k.startswith('src:') and exists(k[4:]):
            return k[4:], 'source'
    for root, how in ((D3, 'd3_marker'), (D4, 'd4_marker')):
        t = get_text(B, f'{root}/_state/sha/{sha[:2]}/{sha}')
        if t and t.startswith('cad-disk-extract/') and exists(t):
            return t, how
    k = D12MAP.get(sha)
    if k and exists(k):
        return k, 'd4_disk12_candidate'
    return None, 'unresolved'


def sniff_zip(key, size, rec):
    if size > (4 << 30):
        rec['zip'] = 'too_big'
        return
    data = get_bytes(B, key)
    if hashlib.sha256(data).hexdigest() != rec['sha256']:
        rec['sha_mismatch'] = True
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e:
        rec['zip'] = 'bad_zip: %s' % str(e)[:100]
        return
    mem = []
    for i in z.infolist():
        if i.is_dir():
            continue
        m = {'name': i.filename, 'size': i.file_size}
        try:
            with z.open(i) as f:
                h = f.read(1 << 16)
            m.update(classify_head(h))
        except Exception as e:
            m['kind'] = 'member_error: %s' % str(e)[:80]
        mem.append(m)
    rec['members'] = mem[:200]
    rec['n_members'] = len(mem)
    ifx = [m for m in mem if m.get('kind') == 'ifcxml']
    if ifx:
        best = max(ifx, key=lambda m: m['size'])
        rec.update(kind='ifcxml_in_zip', member=best['name'], member_size=best['size'], root=best.get('root'),
                   schema=best.get('schema'))
    elif any(m.get('kind') == 'spf' for m in mem):
        rec['kind'] = 'zip_spf'
    elif any(m.get('kind', '').startswith('xml') for m in mem):
        rec['kind'] = 'zip_other_xml'
        rec['root'] = '+'.join(sorted({m.get('root') or '?' for m in mem if m.get('kind', '').startswith('xml')}))[:200]
    else:
        rec['kind'] = 'zip_other'


def sniff_one(args):
    sha, size, keys = args
    rec = {'sha256': sha, 'size': size}
    try:
        key, how = resolve(sha, keys)
        rec['key'] = key
        rec['resolved'] = how
        if key is None:
            rec['kind'] = 'unresolved'
            return rec
        h = get_bytes(B, key, 'bytes=0-65535') if size > 65536 else get_bytes(B, key)
        c = classify_head(h)
        rec.update(c)
        if c['kind'] == 'zip':
            sniff_zip(key, size, rec)
        elif c['kind'] == 'gzip':
            data = get_bytes(B, key)
            try:
                inner = gzip.decompress(data)[:1 << 16]
                c2 = classify_head(inner)
                rec.update({k: v for k, v in c2.items() if k != 'kind'})
                rec['kind'] = 'gzip_' + c2['kind']
            except Exception as e:
                rec['kind'] = 'bad_gzip'
    except Exception as e:
        rec['kind'] = 'error'
        rec['error'] = '%s: %s' % (type(e).__name__, str(e)[:200])
    return rec


def phase_sniff():
    by = {}
    for ds in ('d3', 'd4'):
        p = os.path.join(W, f'xml_rows_{ds}.jsonl.gz')
        if not os.path.exists(p):
            s3().download_file(B, f'{OUT}/xml_rows_{ds}.jsonl.gz', p)
        with gzip.open(p, 'rt') as f:
            for line in f:
                e = json.loads(line)
                sha = e.get('sha256')
                if not sha or len(sha) != 64:
                    continue
                c = by.setdefault(sha, {'size': e.get('size') or 0, 'keys': set(), 'ds': set(), 'n': 0})
                c['keys'].add(e.get('key') or '')
                c['ds'].add(ds)
                c['n'] += 1
    try:
        rh = json.loads(get_bytes(B, f'{OUT}/results_hits.json'))['hits']
    except Exception:
        rh = []
    for h in rh:
        c = by.setdefault(h['sha256'], {'size': h.get('in_bytes') or 0, 'keys': set(), 'ds': set(), 'n': 0})
        if h.get('input_key'):
            c['keys'].add(h['input_key'])
        c['ds'].add(h['ds'])
    log('distinct contents to sniff', len(by))
    need = {s for s, c in by.items() if not any(k.startswith('cad-disk-extract/') for k in c['keys'])}
    load_d12(need)
    out = gzip.open(os.path.join(W, 'sniff.jsonl.gz'), 'wt')
    kinds = collections.Counter()
    t0 = time.time()
    n = 0
    items = sorted(by.items(), key=lambda x: -x[1]['size'])
    with ThreadPoolExecutor(NTHR) as ex:
        for rec in ex.map(sniff_one, [(s, c['size'], sorted(c['keys'])) for s, c in items]):
            c = by[rec['sha256']]
            rec['ds'] = sorted(c['ds'])
            rec['n_rows'] = c['n']
            out.write(json.dumps(rec, default=str) + '\n')
            kinds[rec.get('kind')] += 1
            n += 1
            if n % 1000 == 0:
                log(f'sniff {n}/{len(items)} {dict(kinds)} {time.time() - t0:.0f}s')
    out.close()
    put(os.path.join(W, 'sniff.jsonl.gz'), 'sniff.jsonl.gz')
    log('sniff done', dict(kinds))


# ------------------------------------------------------------------------------------------------ ifcheads
def _ifchead(row):
    rec = {'sha256': row['sha256'], 'size': row.get('size'), 'kind_in': row.get('kind'), 'key': row.get('input_key'),
           'action': row.get('action')}
    try:
        k = row.get('input_key')
        if not k:
            rec['kind'] = 'no_input_key'
            return rec
        h = get_bytes(B, k, 'bytes=0-65535')
        c = classify_head(h)
        rec.update(c)
        if c['kind'] == 'zip':
            sniff_zip(k, row.get('size') or 0, rec)
        elif c['kind'] == 'not_xml' and h.lstrip()[:12].startswith(b'ISO-10303-21'):
            rec['kind'] = 'spf'
    except Exception as e:
        rec['kind'] = 'error'
        rec['error'] = '%s: %s' % (type(e).__name__, str(e)[:200])
    return rec


def phase_ifcheads():
    """every data-3 IFC pipeline input (contents_ifc: 3,956 distinct .ifc / .ifczip): is any of them XML?"""
    rows = [json.loads(l) for l in gzip.decompress(get_bytes(B, f'{D3}/_state/conv/scan/contents_ifc.jsonl.gz')).splitlines() if l.strip()]
    log('data-3 IFC contents', len(rows))
    out = []
    with ThreadPoolExecutor(NTHR) as ex:
        for rec in ex.map(_ifchead, rows):
            out.append(rec)
    kinds = collections.Counter(r.get('kind') for r in out)
    odd = [r for r in out if r.get('kind') not in ('spf', 'zip_spf')]
    put_json({'contents': len(rows), 'by_kind': dict(kinds), 'not_spf': odd[:200]}, 'ifcheads_d3.json')
    log('ifcheads', dict(kinds), 'not spf', len(odd))


# ------------------------------------------------------------------------------------------------ report
def phase_report():
    sn = [json.loads(l) for l in gzip.open(os.path.join(W, 'sniff.jsonl.gz'), 'rt')]
    paths = collections.defaultdict(list)
    jobs = {}
    try:
        jl = json.loads(get_bytes(CB, 'cad-disk-extract/_control/move/z3/jobs.json'))
        for j in (jl if isinstance(jl, list) else jl.get('jobs', [])):
            jobs[j.get('id')] = j.get('key') or j.get('dir') or j.get('src') or ''
    except Exception as e:
        log('no z3 jobs map', e)
    for ds in ('d3', 'd4'):
        with gzip.open(os.path.join(W, f'xml_rows_{ds}.jsonl.gz'), 'rt') as f:
            for line in f:
                e = json.loads(line)
                if len(paths[e.get('sha256')]) < 6:
                    a = jobs.get(e.get('job'), e.get('job'))
                    paths[e.get('sha256')].append('%s %s :: %s' % (ds, a, e.get('path')))
    cand = []
    kinds = collections.Counter()
    roots = collections.Counter()
    for r in sn:
        kinds[r.get('kind')] += 1
        if r.get('kind') in ('xml', 'zip_other_xml'):
            roots[r.get('root')] += 1
        if r.get('kind') in ('ifcxml', 'ifcxml_in_zip', 'gzip_ifcxml', 'xml_ifc_namespace_other_root',
                             'xml_ifc_root_no_namespace'):
            cand.append({k: r.get(k) for k in ('sha256', 'size', 'key', 'resolved', 'kind', 'root', 'schema', 'ns', 'cfg',
                                               'member', 'member_size', 'ds', 'n_rows')})
            cand[-1]['paths'] = paths.get(r['sha256'], [])
    cand.sort(key=lambda c: (c['kind'] != 'ifcxml' and c['kind'] != 'ifcxml_in_zip', -c['size']))
    summ = {'distinct_contents_sniffed': len(sn), 'by_kind': dict(kinds.most_common()),
            'xml_roots_top': dict(roots.most_common(60)), 'candidates': len(cand),
            'candidates_by_kind': dict(collections.Counter(c['kind'] for c in cand)),
            'candidates_by_ds': dict(collections.Counter('+'.join(c['ds']) for c in cand)),
            'unresolved': [r['sha256'] for r in sn if r.get('kind') == 'unresolved'][:100],
            'errors': [(r['sha256'], r.get('error')) for r in sn if r.get('kind') == 'error'][:50]}
    put_json(cand, 'candidates.json')
    put_json(summ, 'summary.json')
    log('report', json.dumps(summ)[:3000])


if __name__ == '__main__':
    os.makedirs(W, exist_ok=True)
    phases = sys.argv[1:] or ['results', 'manifests', 'sniff', 'report']
    for ph in phases:
        t = time.time()
        log('== phase', ph)
        try:
            {'results': phase_results, 'manifests': phase_manifests, 'sniff': phase_sniff, 'report': phase_report,
             'ifcheads': phase_ifcheads}[ph]()
        except Exception:
            traceback.print_exc()
            log('phase failed', ph)
        log('== phase', ph, 'done', round(time.time() - t), 's')
    log('FIND_ALLDONE')
