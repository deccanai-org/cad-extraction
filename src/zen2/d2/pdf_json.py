#!/usr/bin/env python3
"""pdf_json.py [NPROC] - json/drawings/<relpath>.json for every source PDF: metadata, CAD/document class, and per page
the paper size, page kind, title-block fields, text spans (mm, y up: origin, bbox, size, rotation, font, colour),
annotations (review comments), conversion stats, the dxf_from_pdf key and its raster-validation scores."""
import json, math, os, sys
import multiprocessing as mp

sys.path.insert(0, '/work/2d')
SRC = '/work/in/src/'
OUT = '/work/2d/out/json/drawings/'
B = 's3://annotationprod/cad-disk-extract/zenitude-data-2/'
PT = 25.4 / 72.0


def work(r):
    import pymupdf
    import build_index as BI
    rel = r['canonical_relpath']
    doc = {'source_relpath': rel, 'sha256': r['sha256'], 'same_content_relpaths': r['relpaths'],
           'source': B + 'source/' + rel, 'size': r.get('size'), 'status': r.get('status'),
           'reason': r.get('reason'), 'producer': r.get('producer'), 'creator': r.get('creator'),
           'doc_class': r.get('doc_class'), 'doc_class_reason': r.get('doc_class_reason'),
           'page_count': r.get('page_count'), 'converter': r.get('converter'), 'pages': []}
    if r.get('status') != 'unreadable':
        try:
            d = pymupdf.open(SRC + rel)
            ids = BI.pdf_page_ids(SRC + rel)
        except Exception as e:
            d, ids = None, []
            doc['error'] = str(e)[:200]
        for pr in r.get('pages', []):
            n = pr['page']
            pg = {k: pr.get(k) for k in ('page', 'w_mm', 'h_mm', 'rotation', 'kind', 'image_coverage', 'stats',
                                          'annotations', 'validation', 'error', 'note')}
            pg['dxf_from_pdf'] = (B + 'dxf_from_pdf/' + pr['dxf']) if pr.get('dxf') else None
            pg['png'] = B + 'png/%s/page-%d.png' % (rel, n)
            pg['title_block'] = ids[n - 1] if n - 1 < len(ids) else {}
            spans = []
            if d is not None:
                p = d[n - 1]
                H = p.rect.height
                for b in p.get_text('dict').get('blocks', []):
                    for ln in b.get('lines', []):
                        dx, dy = ln['dir']
                        for sp in ln['spans']:
                            if not sp['text'].strip():
                                continue
                            x0, y0, x1, y1 = sp['bbox']
                            spans.append({'text': sp['text'], 'origin_mm': [round(sp['origin'][0] * PT, 3),
                                                                            round((H - sp['origin'][1]) * PT, 3)],
                                          'bbox_mm': [round(x0 * PT, 3), round((H - y1) * PT, 3), round(x1 * PT, 3),
                                                      round((H - y0) * PT, 3)],
                                          'size_mm': round(sp['size'] * PT, 3),
                                          'rotation_deg': round(math.degrees(math.atan2(-dy, dx)), 2),
                                          'font': sp['font'], 'color': '%06X' % sp.get('color', 0)})
            pg['text_spans'] = spans
            doc['pages'].append(pg)
    for rel2 in r['relpaths']:
        d2 = dict(doc)
        d2['source_relpath'] = rel2
        d2['source'] = B + 'source/' + rel2
        d2['pages'] = []
        for pg in doc['pages']:
            q = dict(pg)
            if q.get('dxf_from_pdf'):
                q['dxf_from_pdf'] = B + 'dxf_from_pdf/%s/page-%d.dxf' % (rel2, q['page'])
            q['png'] = B + 'png/%s/page-%d.png' % (rel2, q['page'])
            d2['pages'].append(q)
        fn = OUT + rel2 + '.json'
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        with open(fn, 'w') as f:
            json.dump(d2, f, indent=1, ensure_ascii=False, default=str)
    return len(r['relpaths'])


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    recs = {}
    for l in open('/work/2d/state/pdf_results.jsonl'):
        r = json.loads(l)
        recs[r['sha256']] = r
    with mp.get_context('fork').Pool(n) as pool:
        tot = sum(pool.imap_unordered(work, list(recs.values()), chunksize=4))
    print('json files', tot)


if __name__ == '__main__':
    main()
