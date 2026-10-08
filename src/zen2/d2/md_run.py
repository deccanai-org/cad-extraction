#!/usr/bin/env python3
"""md_run.py [NPROC] [--types sha,pcf] [--limit N] - Smart 3D model drawings (model_drawings/) -> 2D outputs.

  .sha  -> model_drawings_json/<name>.json          (title block / tagged text / OLE properties, sha2json)
        -> model_drawings_dxf/<name>.dxf             (EXPERIMENTAL geometry-only vector decode, sha2dxf)
        -> model_drawings_dxf/<name>.texts.json      (decoded text strings + anchors; font/height not decoded)
        -> model_drawings_dxf/<name>.png             (ezdxf render of the DXF, 100 dpi)
  .pcf  -> model_drawings_iso_from_pcf/<name>.dxf/.png (isometric generated from the PCF, pcf2iso)
<name> = object key basename without .zip / extension (oid prefix kept, unique).
Results: /work/md/state/results_<type>.jsonl ; status part 'model_drawings' in _state/d2_2d_status.json.
"""
import collections, glob, gzip, io, json, os, sys, time, traceback, zipfile
import multiprocessing as mp

sys.path.insert(0, '/work/2d')
BK = 'annotationprod'
P = 'cad-disk-extract/zenitude-data-2/'
ST = '/work/md/state/'
TMP = '/work/md/tmp/'
os.makedirs(ST, exist_ok=True)
os.makedirs(TMP, exist_ok=True)
_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3
        from botocore.config import Config
        _s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=64,
                                                                          retries={'max_attempts': 8, 'mode': 'adaptive'}))
    return _s3


def load_index():
    idx = []
    keys = [o['Key'] for page in s3().get_paginator('list_objects_v2').paginate(Bucket=BK, Prefix=P + 'model_drawings/_index/')
            for o in page.get('Contents', [])]
    for k in keys:
        if not k.endswith('.jsonl.gz'):
            continue
        b = s3().get_object(Bucket=BK, Key=k)['Body'].read()
        for l in gzip.decompress(b).decode('utf-8').splitlines():
            if l.strip():
                idx.append(json.loads(l))
    return idx


def out_name(key):
    b = key.rsplit('/', 1)[-1]
    if b.lower().endswith('.zip'):
        b = b[:-4]
    for ext in ('.sha', '.pcf'):
        if b.lower().endswith(ext):
            b = b[:-len(ext)]
    return b


def fetch(key):
    data = s3().get_object(Bucket=BK, Key=key)['Body'].read()
    if key.lower().endswith('.zip'):
        z = zipfile.ZipFile(io.BytesIO(data))
        names = [n for n in z.namelist() if not n.endswith('/')]
        data = z.read(names[0])
    return data


def put(key, body, ctype):
    s3().put_object(Bucket=BK, Key=key, Body=body, ContentType=ctype)


def sheet_size(doc):
    """(x0, y0, W, H) of the render box: the standard sheet (A3..A0 from the origin) that contains the drawing, else
    the drawing extents."""
    from ezdxf import bbox
    try:
        e = bbox.extents(doc.modelspace(), fast=True)
        x0, y0, x1, y1 = e.extmin.x, e.extmin.y, e.extmax.x, e.extmax.y
    except Exception:
        return 0.0, 0.0, 841.0, 594.0
    if x0 > -5 and y0 > -5:
        for W, H in ((420, 297), (594, 420), (841, 594), (1189, 841)):
            if x1 <= W + 5 and y1 <= H + 5:
                return 0.0, 0.0, float(W), float(H)
    w, h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    return x0 - 0.02 * w, y0 - 0.02 * h, w * 1.04, h * 1.04


def render_box_png(dxf_path, box, dpi=100, max_px=5000):
    """ezdxf drawing add-on render of the box (mm) to PNG; dpi reduced so the long side stays <= max_px."""
    import pymupdf, ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend, layout
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy, LineweightPolicy, ImagePolicy
    from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
    from ezdxf.math import BoundingBox2d
    x0, y0, W, H = box
    dpi = min(dpi, max_px / (max(W, H) / 25.4))
    doc = ezdxf.readfile(dxf_path)
    be = PyMuPdfBackend()
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR,
                        lineweight_policy=LineweightPolicy.ABSOLUTE, lineweight_scaling=1.0, min_lineweight=2.0,
                        image_policy=ImagePolicy.DISPLAY)
    Frontend(RenderContext(doc), be, config=cfg).draw_layout(doc.modelspace(), finalize=True)
    pg = layout.Page(W, H, layout.Units.mm, margins=layout.Margins.all(0))
    pdf = be.get_pdf_bytes(pg, settings=layout.Settings(fit_page=False, scale=1.0),
                           render_box=BoundingBox2d([(x0, y0), (x0 + W, y0 + H)]))
    d = pymupdf.open('pdf', pdf)
    p = d[0]
    z = dpi / 72.0 * (W / (25.4 / 72)) / p.rect.width
    return d[0].get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False).tobytes('png'), round(dpi, 2)


def do_sha(rec):
    import sha2json, sha2dxf, pdf2dxf
    key = rec['_key']
    name = out_name(key)
    r = {'oid': rec.get('oid'), 'file_name': rec.get('file_name'), 'key': key, 'name': name, 'type': 'sha',
         'line_number': rec.get('line_number')}
    tmp = TMP + '%d_%s.sha' % (os.getpid(), abs(hash(name)) % 10 ** 9)
    try:
        data = fetch(key)
        with open(tmp, 'wb') as f:
            f.write(data)
        r['bytes'] = len(data)
        if not data.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
            r.update(status='not_ole2', head=data[:8].hex())
            return r
        j = sha2json.convert(tmp, rec.get('file_name') or name, '')
        j['source_key'] = 's3://%s/%s' % (BK, key)
        j['oid'] = rec.get('oid')
        j['line_number'] = rec.get('line_number')
        j.pop('source_relpath', None)
        put(P + 'model_drawings_json/%s.json' % name, json.dumps(j, default=str, ensure_ascii=False).encode(),
            'application/json')
        r['fields'] = {k: v for k, v in j['fields'].items() if v not in ('', None, [], {})}
        r['streams'] = len(j['streams'])
        dec = sha2dxf.Decoder(tmp)
        dec.run()
        doc = dec.to_dxf(include_text=False)
        box = sheet_size(doc)
        dx = TMP + '%d.dxf' % os.getpid()
        doc.saveas(dx)
        put(P + 'model_drawings_dxf/%s.dxf' % name, open(dx, 'rb').read(), 'application/dxf')
        put(P + 'model_drawings_dxf/%s.texts.json' % name,
            json.dumps({'source_key': 's3://%s/%s' % (BK, key), 'converter': sha2dxf.CODE_VERSION,
                        'note': 'decoded text strings with anchor point (sheet mm), rotation and justification; '
                                'font/height NOT decoded', 'texts': dec.texts()}, ensure_ascii=False).encode(),
            'application/json')
        n_ent = len(doc.modelspace())
        r.update(dxf_entities=n_ent, decode_stats=dict(dec.stats), undecoded=dict(dec.unknown.most_common(12)),
                 texts=len(dec.texts()), render_box_mm=[round(v, 1) for v in box])
        if n_ent:
            png, dpi = dec.render_png(box, dpi=100)
            put(P + 'model_drawings_dxf/%s.png' % name, png, 'image/png')
            r['png'] = True
            r['png_dpi'] = dpi
        r['status'] = 'ok'
    except Exception as e:
        r.update(status='failed', reason='%s: %s' % (type(e).__name__, str(e)[:200]), tb=traceback.format_exc()[-500:])
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return r


def do_pcf(rec):
    import pcf2iso
    key = rec['_key']
    name = out_name(key)
    r = {'oid': rec.get('oid'), 'file_name': rec.get('file_name'), 'key': key, 'name': name, 'type': 'pcf',
         'line_number': rec.get('line_number')}
    try:
        data = fetch(key)
        r['bytes'] = len(data)
        txt = data.decode('utf-8', 'replace') if data[:3] == b'\xef\xbb\xbf' else data.decode('latin-1')
        dx = TMP + '%d_iso.dxf' % os.getpid()
        pn = TMP + '%d_iso.png' % os.getpid()
        info = pcf2iso.convert(txt, rec.get('file_name') or name, dx, pn)
        put(P + 'model_drawings_iso_from_pcf/%s.dxf' % name, open(dx, 'rb').read(), 'application/dxf')
        put(P + 'model_drawings_iso_from_pcf/%s.png' % name, open(pn, 'rb').read(), 'image/png')
        r.update(info)
        r['status'] = 'ok' if info.get('components') else 'empty'
    except Exception as e:
        r.update(status='failed', reason='%s: %s' % (type(e).__name__, str(e)[:200]), tb=traceback.format_exc()[-500:])
    return r


def _init():
    global _s3
    _s3 = None


def work(rec):
    t = time.time()
    r = do_sha(rec) if rec['_type'] == 'sha' else do_pcf(rec)
    r['seconds'] = round(time.time() - t, 2)
    return r


def summarize(res, totals):
    import status
    out = {'stage': 'running', 'totals_in_index': totals}
    for t in ('sha', 'pcf'):
        rs = [r for r in res.values() if r['type'] == t]
        c = collections.Counter(r['status'] for r in rs)
        d = {'done': len(rs), 'by_status': dict(c),
             'failures': [{'key': r['key'].rsplit('/', 1)[-1], 'reason': r.get('reason') or r['status']}
                          for r in rs if r['status'] not in ('ok',)][:100]}
        if t == 'sha':
            d['with_png'] = sum(1 for r in rs if r.get('png'))
            d['entities_total'] = sum(r.get('dxf_entities', 0) for r in rs)
            d['texts_total'] = sum(r.get('texts', 0) for r in rs)
            d['note'] = ('EXPERIMENTAL geometry-only vector decode (same decoder as P16093 dxf_from_sha): lines, arcs, '
                         'circles, elliptical arcs, polygon outlines, placed views, layers, line widths. NOT decoded: '
                         'text size/font (strings + anchors are in <name>.texts.json, no TEXT in the DXF), fills, '
                         'paths (type 19), B-splines, symbols, dimensions objects, colours, pictures. No reference plot '
                         'exists for these files, so they are not raster-validated.')
        else:
            d['components_total'] = sum(r.get('components', 0) for r in rs)
            d['note'] = 'isometric generated from the PCF (true-scale isometric of centre-lines fitted to A3) by pcf2iso.py'
        out[t] = d
    out['outputs'] = {'sha_json': 's3://annotationprod/' + P + 'model_drawings_json/',
                      'sha_dxf_png': 's3://annotationprod/' + P + 'model_drawings_dxf/',
                      'pcf_iso': 's3://annotationprod/' + P + 'model_drawings_iso_from_pcf/'}
    return out


def list_jobs(types):
    """object listing of model_drawings/<type>/ (the export writes .sha and/or .sha.zip, .pcf.zip); one job per name."""
    jobs = {}
    pg = s3().get_paginator('list_objects_v2')
    for t in types:
        for page in pg.paginate(Bucket=BK, Prefix=P + 'model_drawings/%s/' % t):
            for o in page.get('Contents', []):
                k = o['Key']
                nm = out_name(k)
                prev = jobs.get((t, nm))
                if prev is None or (prev['_key'].lower().endswith('.zip') and not k.lower().endswith('.zip')):
                    b = k.rsplit('/', 1)[-1]
                    oid, _, fname = b.partition('__')
                    if fname.lower().endswith('.zip'):
                        fname = fname[:-4]
                    jobs[(t, nm)] = {'_key': k, '_type': t, 'oid_prefix': oid, 'file_name': fname, 'size': o['Size']}
    return list(jobs.values())


def export_final():
    try:
        ks = [o['Key'] for o in s3().list_objects_v2(Bucket=BK, Prefix=P + '_state/model_drawings_status/').get('Contents', [])]
        return bool(ks) and all(json.loads(s3().get_object(Bucket=BK, Key=k)['Body'].read()).get('final') for k in ks)
    except Exception:
        return False


def main():
    import status, zlib
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 24
    types = ['sha', 'pcf']
    if '--types' in sys.argv:
        types = sys.argv[sys.argv.index('--types') + 1].split(',')
    limit = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
    shard, nshard = 0, 1
    if '--shard' in sys.argv:
        a, b = sys.argv[sys.argv.index('--shard') + 1].split('/')
        shard, nshard = int(a), int(b)
    part = 'model_drawings' + ('' if nshard == 1 else '_shard%d' % shard)
    res = {}
    for t in types:
        fn = ST + 'results_%s.jsonl' % t
        if os.path.exists(fn):
            for l in open(fn):
                try:
                    x = json.loads(l)
                    res[x['key']] = x
                except Exception:
                    pass
    fo = {t: open(ST + 'results_%s.jsonl' % t, 'a') for t in types}
    last = 0
    totals = {}
    while not export_final():
        print(time.strftime('%H:%M:%S'), 'waiting for the model_drawings export to be final', flush=True)
        time.sleep(60)
    idx = load_index()
    totals = dict(collections.Counter((r.get('file_type') or '').lower() for r in idx))
    jobs = []
    for r in idx:
        t = (r.get('file_type') or '').lower()
        if t not in types or not r.get('objects'):
            continue
        keys = [o['key'] for o in r['objects'] if '/%s/0001ade2__' % t not in o['key']]
        if not keys:
            continue
        r['_key'] = next((k for k in keys if not k.lower().endswith('.zip')), keys[0])
        r['_type'] = t
        jobs.append(r)
    import socket
    host = socket.gethostname()
    if '--retry-failed' in sys.argv:
        prev = {}
        for page in s3().get_paginator('list_objects_v2').paginate(Bucket=BK, Prefix=P + '_state/d2_md_results/'):
            for o in page.get('Contents', []):
                for l in gzip.decompress(s3().get_object(Bucket=BK, Key=o['Key'])['Body'].read()).decode().splitlines():
                    if l.strip():
                        x = json.loads(l)
                        prev[x['key']] = x
        byk = {j['_key']: j for j in jobs}
        todo = [byk[k] for k, x in prev.items() if x.get('status') == 'failed' and k in byk]
        print('retrying', len(todo), flush=True)
        out = []
        with mp.get_context('fork').Pool(n, initializer=_init) as pool:
            for r in pool.imap_unordered(work, todo, chunksize=2):
                out.append(r)
                res[r['key']] = r
        s3().put_object(Bucket=BK, Key=P + '_state/d2_md_results/zz-retry-%s-%d.jsonl.gz' % (host, int(time.time())),
                        Body=gzip.compress('\n'.join(json.dumps(r, default=str, ensure_ascii=False) for r in out).encode()))
        print('retried', collections.Counter(r['status'] for r in out), flush=True)
        return
    NCH = 256
    chunks = collections.defaultdict(list)
    for j in jobs:
        chunks[zlib.crc32(out_name(j['_key']).encode()) % NCH].append(j)
    print(time.strftime('%H:%M:%S'), 'index', len(idx), totals, 'jobs', len(jobs), 'chunks', len(chunks), flush=True)
    order = sorted(chunks)
    if nshard > 1:
        order = [c for c in order if c % nshard == shard] + [c for c in order if c % nshard != shard]
    done_here = 0
    with mp.get_context('fork').Pool(n, initializer=_init, maxtasksperchild=200) as pool:
        for ch in order:
            if limit and done_here >= limit:
                break
            ck = P + '_state/d2_md_claims/chunk-%03d' % ch
            try:
                if limit:
                    raise RuntimeError('sample mode: no claim')
                s3().put_object(Bucket=BK, Key=ck, Body=json.dumps({'host': host, 'at': time.time()}).encode(),
                                IfNoneMatch='*')
            except Exception as e:
                if 'PreconditionFailed' in str(e) or '412' in str(e):
                    # take over stale claims (claimed > 40 min ago and never finished, e.g. a restarted worker)
                    try:
                        s3().head_object(Bucket=BK, Key=ck + '.done')
                        continue
                    except Exception:
                        pass
                    try:
                        c = json.loads(s3().get_object(Bucket=BK, Key=ck)['Body'].read())
                    except Exception:
                        continue
                    if time.time() - c.get('at', time.time()) < 2400 and not (c.get('host') == host and '--takeover-own' in sys.argv):
                        continue
                    s3().put_object(Bucket=BK, Key=ck, Body=json.dumps({'host': host, 'at': time.time(), 'takeover': c}).encode())
                elif not limit:
                    raise
            todo = [j for j in chunks[ch] if j['_key'] not in res or res[j['_key']].get('status') == 'failed']
            if limit:
                todo = todo[:limit - done_here]
            out = []
            for r in pool.imap_unordered(work, todo, chunksize=2):
                res[r['key']] = r
                out.append(r)
                done_here += 1
                fo[r['type']].write(json.dumps(r, default=str, ensure_ascii=False) + '\n')
                fo[r['type']].flush()
                if time.time() - last > 60:
                    sm = summarize(res, totals)
                    sm['host'] = host
                    status.put_part(part + '_' + host, sm)
                    last = time.time()
            if limit:
                continue
            s3().put_object(Bucket=BK, Key=P + '_state/d2_md_results/chunk-%03d.jsonl.gz' % ch,
                            Body=gzip.compress('\n'.join(json.dumps(r, default=str, ensure_ascii=False) for r in out).encode()))
            s3().put_object(Bucket=BK, Key=ck + '.done', Body=json.dumps({'host': host, 'at': time.time(), 'n': len(out)}).encode())
    s = summarize(res, totals)
    s['stage'] = ('no unclaimed chunks left' if not limit else 'sample done')
    s['host'] = host
    status.put_part(part + '_' + host, s)
    print('done', len(res), flush=True)


if __name__ == '__main__':
    main()
