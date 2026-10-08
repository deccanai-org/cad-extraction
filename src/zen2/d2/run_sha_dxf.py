#!/usr/bin/env python3
"""run_sha_dxf.py [NPROC] - EXPERIMENTAL geometry-only .sha -> DXF for every distinct .sha, validated against the PDF
plot of the same drawing number/sheet (closest folder): precision = share of decoded ink on PDF ink (1-px tolerance),
recall = share of PDF ink reproduced (text, fills, symbols are not decoded -> recall is expected to be low)."""
import collections, json, os, sys, time, traceback, re
import multiprocessing as mp
sys.path.insert(0, '/work/2d')
SRC = '/work/in/src/'
OUT = '/work/2d/out/dxf_from_sha/'
RES = '/work/2d/state/sha_dxf_results.jsonl'
PNG = '/work/out/png/'


def load():
    g = collections.OrderedDict()
    pdfs = []
    for l in open('/work/out/json/source_sha256.tsv'):
        h, p = l.rstrip('\n').split('\t', 1)
        if p.startswith('PLC 17072025/'):
            continue
        if p.lower().endswith('.sha'):
            g.setdefault(h, []).append(p)
        elif p.lower().endswith('.pdf'):
            pdfs.append(p)
    return g, pdfs


FIELDS = {}


def pair_pdf(rel, fields, pdfs, page_ids):
    base = fields.get('drawing_number') or ''
    m = re.match(r'(P16093-\d\d-\d\d-\d\d-\d{4})', base)
    if not m:
        return None
    base = m.group(1)
    sheet = fields.get('sheet_no') or 1
    best = None
    for p in pdfs:
        ids = page_ids.get(p)
        if not ids:
            continue
        for i, pid in enumerate(ids):
            if pid.get('dn') == base and (pid.get('sheet') or 1) == sheet:
                cp = len(os.path.commonprefix([os.path.dirname(rel), os.path.dirname(p)]))
                rev_ok = str(pid.get('rev', '')).lstrip('0') == str(fields.get('revision', '')).lstrip('0')
                key = (rev_ok, cp)
                if best is None or key > best[0]:
                    best = (key, p, i + 1)
    return best


def vector_match(dec, pg):
    """decoded line endpoints vs PDF line endpoints (mm): share within 0.2 mm as decoded (identity) and after a
    fitted similarity (scale + offset; PDF plots can be print-scaled), plus the fitted scale."""
    import numpy as np
    from scipy.spatial import cKDTree
    H = pg.rect.height
    k = 25.4 / 72
    P = []
    for d in pg.get_drawings():
        for it in d['items']:
            if it[0] == 'l':
                P.append((it[1].x * k, (H - it[1].y) * k))
                P.append((it[2].x * k, (H - it[2].y) * k))
    D = [(x * 1000, y * 1000) for kind, dd, lay, w in dec.ents if kind == 'line' for x, y in dd]
    if len(P) < 10 or len(D) < 10:
        return {'vector_points_pdf': len(P), 'vector_points_sha': len(D)}
    P = np.array(P)
    D = np.array(D)
    kd = cKDTree(P)
    d0, _ = kd.query(D)
    s, t = 1.0, np.zeros(2)
    for thr in (5.0, 2.0, 0.5, 0.2):
        X = D * s + t
        dist, idx = kd.query(X)
        m = dist < thr
        if m.sum() < 10:
            break
        A, Bm = D[m], P[idx[m]]
        ma, mb = A.mean(0), Bm.mean(0)
        va = ((A - ma) ** 2).sum()
        s = float(((A - ma) * (Bm - mb)).sum() / va) if va > 0 else 1.0
        t = mb - s * ma
    d1, _ = kd.query(D * s + t)
    return {'vector_points_sha': int(len(D)), 'vector_points_pdf': int(len(P)),
            'vector_precision_0p2mm_as_decoded': round(float((d0 < 0.2).mean()), 4),
            'vector_precision_0p2mm_fitted': round(float((d1 < 0.2).mean()), 4),
            'fitted_scale': round(s, 5), 'fitted_offset_mm': [round(float(t[0]), 2), round(float(t[1]), 2)]}


def work(a):
    import sha2dxf as S
    import pdf2dxf as P
    import numpy as np
    h, rels, pair = a
    rel = rels[0]
    t0 = time.time()
    out = {'sha256': h, 'relpaths': rels, 'converter': S.CODE_VERSION}
    try:
        dec = S.Decoder(SRC + rel)
        dec.run()
        doc = dec.to_dxf(include_text=False)
        fn = OUT + rel + '.dxf'
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        doc.saveas(fn)
        tj = OUT + rel + '.texts.json'
        json.dump({'source_relpath': rel, 'converter': S.CODE_VERSION,
                   'note': 'decoded text strings with anchor point (sheet mm), rotation and justification; '
                           'font/height NOT decoded', 'texts': dec.texts()}, open(tj, 'w'), indent=1, ensure_ascii=False)
        out.update(status='ok', stats=dict(dec.stats), undecoded_record_types=dict(dec.unknown.most_common(30)),
                   dxf=os.path.relpath(fn, OUT), dxf_bytes=os.path.getsize(fn), texts=len(dec.texts()))
        if pair:
            _, pdf, page = pair
            ref = None
            for c in ('page-%d.png' % page, 'page-%02d.png' % page):
                if os.path.exists(PNG + pdf + '/' + c):
                    ref = PNG + pdf + '/' + c
            if ref:
                import pymupdf
                pg = pymupdf.open(SRC + pdf)[page - 1]
                png = P.render_dxf(fn, pg.rect.width * P.PT, pg.rect.height * P.PT)
                res, sh = P.compare(P.ink_mask(ref), P.ink_mask(png))
                res['paired_pdf'] = pdf
                res['paired_page'] = page
                res.update(vector_match(dec, pg))
                out['validation'] = res
        else:
            out['validation'] = {'status': 'no PDF plot of the same drawing/sheet found'}
    except Exception as e:
        out.update(status='failed', reason='%s: %s' % (type(e).__name__, str(e)[:200]), traceback=traceback.format_exc()[-600:])
    out['seconds'] = round(time.time() - t0, 1)
    return out


def main():
    import status, build_index as BI
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    g, pdfs = load()
    fields = {}
    for l in open('/work/2d/state/sha_results.jsonl'):
        r = json.loads(l)
        fields[r['sha256']] = r.get('fields', {})
    page_ids = {}
    seen = set()
    for p in pdfs:
        page_ids[p] = BI.pdf_page_ids(SRC + p)
    jobs = [(h, rels, pair_pdf(rels[0], fields.get(h, {}), pdfs, page_ids)) for h, rels in g.items()]
    res = []
    with mp.get_context('fork').Pool(n, maxtasksperchild=20) as pool:
        for r in pool.imap_unordered(work, jobs):
            res.append(r)
    with open(RES, 'w') as f:
        for r in res:
            f.write(json.dumps(r, default=str) + '\n')
    # duplicates -> hardlinks
    for r in res:
        if r.get('status') != 'ok':
            continue
        for rel in r['relpaths'][1:]:
            for ext in ('.dxf', '.texts.json'):
                src, dst = OUT + r['relpaths'][0] + ext, OUT + rel + ext
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if not os.path.exists(dst):
                    os.link(src, dst)
    v = [r['validation'] for r in res if 'precision_1px' in r.get('validation', {})]
    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if xs else None
    status.put_part('sha_dxf', {
        'stage': 'done (experimental, geometry only)', 'distinct_sha': len(g), 'dxf_ok': sum(r.get('status') == 'ok' for r in res),
        'failed': [{'relpath': r['relpaths'][0], 'reason': r.get('reason')} for r in res if r.get('status') != 'ok'],
        'validated_against_pdf': len(v),
        'precision_1px_median': med([x['precision_1px'] for x in v]), 'recall_1px_median': med([x['recall_1px'] for x in v]),
        'precision_1px_p10': sorted(x['precision_1px'] for x in v)[len(v) // 10] if v else None,
        'iou_tol1px_median': med([x['iou_tol1px'] for x in v]),
        'vector_precision_0p2mm_as_decoded_median': med([x['vector_precision_0p2mm_as_decoded'] for x in v if 'vector_precision_0p2mm_as_decoded' in x]),
        'vector_precision_0p2mm_fitted_median': med([x['vector_precision_0p2mm_fitted'] for x in v if 'vector_precision_0p2mm_fitted' in x]),
        'vector_precision_0p2mm_fitted_p10': (sorted(x['vector_precision_0p2mm_fitted'] for x in v if 'vector_precision_0p2mm_fitted' in x) or [None])[len([x for x in v if 'vector_precision_0p2mm_fitted' in x]) // 10],
        'plots_print_scaled (fitted scale off by >0.2%)': sum(1 for x in v if abs(x.get('fitted_scale', 1) - 1) > 0.002),
        'metrics': 'raster: ink at 150 dpi, 1-px tolerance, vs the paired PDF plot PNG; vector: decoded line endpoints within '
                   '0.2 mm of a PDF line endpoint (as decoded, and after fitting scale+offset because some plots are '
                   'print-scaled or come from a commented/re-plotted copy)',
        'decoded': 'lines (24), circles (89), circular arcs (97/99), elliptical arcs (126), polygon outlines (132), placed views/sub-documents (61) '
                   'with their transforms, Smart 3D layer names, line widths (line styles 46/48); text strings + anchors '
                   'to <relpath>.texts.json',
        'not_decoded': 'text font/height (style indirection unresolved), fill styles (132) and paths (19), B-splines (93), symbol and '
                       'linetype geometry (123, 24/66-byte), dimensions/labels (206, 250, 277, 280), colours, pictures (static DIB)'})
    print('done', len(res))


if __name__ == '__main__':
    main()
