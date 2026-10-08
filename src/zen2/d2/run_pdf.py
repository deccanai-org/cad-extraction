#!/usr/bin/env python3
"""run_pdf.py [NPROC] [--limit N] [--only SHA,...] - convert every DISTINCT source PDF (by sha256) page -> DXF and
validate each page against the existing 150-dpi pdftoppm PNG.

Outputs (local, then synced by sync_pdf.sh):
  /work/2d/out/dxf_from_pdf/<canonical relpath>/page-<n>.dxf (+ page-<n>_img<k>.png image side files)
  /work/2d/state/pdf_results.jsonl  one record per distinct PDF (pages, scores, stats, failures)
  /work/2d/out/qa/<sha>-p<n>.png    diff thumbnails for pages below the 0.9 threshold
"""
import collections, json, os, re, signal, sys, time, traceback
import multiprocessing as mp

sys.path.insert(0, '/work/2d')
SRC = '/work/in/src/'
PNG = '/work/out/png/'
OUT = '/work/2d/out/dxf_from_pdf/'
QA = '/work/2d/out/qa/'
RES = '/work/2d/state/pdf_results.jsonl'
THRESH = 0.9

CAD = re.compile(r'autocad|autodesk|acad|dwg|tekla|microstation|bentley|revit|navisworks|smartplant|smart ?3d|intergraph|'
                 r'hexagon|smartsketch|isogen|aveva|pdms|cadworx|bricscad|pdfplot|plant 3d', re.I)
DOC = re.compile(r'microsoft|word|excel|powerpoint|libreoffice|openoffice|quartz|skia|chrome|scan|canon|xerox|ricoh|'
                 r'konica|kyocera|epson|reportlab|itext|nitro|abbyy', re.I)


def classify_doc(meta, doc):
    prod = ' '.join(filter(None, [meta.get('producer'), meta.get('creator')]))
    big = max((max(p.rect.width, p.rect.height) for p in doc), default=0)
    if CAD.search(prod):
        return 'cad', 'producer/creator is a CAD plot driver: ' + prod[:80]
    if big >= 1190:
        return 'cad', 'page >= A3 (%.0f pt); producer %s' % (big, prod[:60] or '-')
    if DOC.search(prod):
        return 'document', 'office/scanner producer: ' + prod[:80]
    return 'document', 'page < A3'


def load_jobs():
    groups = collections.OrderedDict()
    for l in open('/work/out/json/source_sha256.tsv'):
        h, p = l.rstrip('\n').split('\t', 1)
        if p.lower().endswith('.pdf') and not p.startswith('PLC 17072025/'):
            groups.setdefault(h, []).append(p)
    return groups


def ref_png(rel, n):
    d = PNG + rel
    for c in ('page-%d.png' % n, 'page-%02d.png' % n, 'page-%03d.png' % n):
        if os.path.exists(os.path.join(d, c)):
            return os.path.join(d, c)
    return None


class Timeout(Exception):
    pass


def _alarm(sig, frm):
    raise Timeout()


def work(args):
    sha, rels = args
    import pymupdf
    import pdf2dxf as P
    signal.signal(signal.SIGALRM, _alarm)
    rel = rels[0]
    t0 = time.time()
    out = {'sha256': sha, 'canonical_relpath': rel, 'relpaths': rels, 'size': os.path.getsize(SRC + rel),
           'converter': P.CODE_VERSION, 'pages': []}
    try:
        doc = pymupdf.open(SRC + rel)
        if doc.page_count == 0:
            raise RuntimeError('no pages')
    except Exception as e:
        with open(SRC + rel, 'rb') as f:
            b = f.read()
        if not any(b):
            why = 'source file is %d zero bytes (no PDF header; corrupted copy on the disk)' % len(b)
        elif not b.startswith(b'%PDF'):
            why = 'no %%PDF header (starts %r)' % b[:8]
        else:
            why = 'PyMuPDF cannot open: %s' % str(e)[:160]
        out.update(status='unreadable', reason=why, seconds=round(time.time() - t0, 1))
        return out
    meta = doc.metadata or {}
    out['producer'] = meta.get('producer', '')
    out['creator'] = meta.get('creator', '')
    out['page_count'] = doc.page_count
    out['doc_class'], out['doc_class_reason'] = classify_doc(meta, doc)
    od = OUT + rel
    os.makedirs(od, exist_ok=True)
    for pno in range(doc.page_count):
        rec = {'page': pno + 1}
        tp = time.time()
        try:
            signal.alarm(3000)
            page = doc[pno]
            rec['w_mm'] = round(page.rect.width * P.PT, 2)
            rec['h_mm'] = round(page.rect.height * P.PT, 2)
            rec['rotation'] = page.rotation
            cov = P.classify_page(page)
            rec['image_coverage'] = round(cov, 3)
            dxfp = os.path.join(od, 'page-%d.dxf' % (pno + 1))
            c = P.PageConverter(doc, pno, dxfp)
            dd = c.convert('page-%d' % (pno + 1))
            st = {k: v for k, v in c.stats.items() if v}
            rec['stats'] = st
            if getattr(c, 'annots', None):
                rec['annotations'] = c.annots
                rec['annotation_note'] = 'PDF annotations (review comments) flattened into the page before conversion'
            if st.get('paths', 0) < 20 and st.get('text', 0) < 5 and cov > 0.5:
                rec['kind'] = 'raster'
                rec['note'] = 'scanned/raster-only page: no DXF written'
                for fn in os.listdir(od):
                    if fn.startswith('page-%d_img' % (pno + 1)):
                        os.remove(os.path.join(od, fn))
                out['pages'].append(rec)
                continue
            rec['kind'] = 'vector+raster' if cov > 0.5 else 'vector'
            dd.saveas(dxfp)
            rec['dxf'] = os.path.relpath(dxfp, OUT)
            rec['dxf_bytes'] = os.path.getsize(dxfp)
            rec['images'] = sorted(fn for fn in os.listdir(od) if fn.startswith('page-%d_img' % (pno + 1)))
            rec['t_convert'] = round(time.time() - tp, 1)
            # validation
            ref = ref_png(rel, pno + 1)
            if ref is None:
                rec['validation'] = {'status': 'no reference PNG'}
            else:
                tv = time.time()
                png = P.render_dxf(dxfp, c.W_mm, c.H_mm, dpi=150)
                A = P.ink_mask(ref)
                Bm = P.ink_mask(png)
                res, sh = P.compare(A, Bm)
                res['status'] = 'ok' if res['iou_tol1px'] >= THRESH else 'flagged'
                res['reference_png'] = os.path.relpath(ref, PNG)
                res['t_validate'] = round(time.time() - tv, 1)
                rec['validation'] = res
                if res['iou_tol1px'] < THRESH:
                    os.makedirs(QA, exist_ok=True)
                    P.diff_image(A, sh, os.path.join(QA, '%s-p%d.png' % (sha[:16], pno + 1)), scale=0.35)
        except Timeout:
            rec['kind'] = rec.get('kind', 'failed')
            rec['error'] = 'timeout (3000 s) during conversion/validation'
        except Exception as e:
            rec['kind'] = rec.get('kind', 'failed')
            rec['error'] = '%s: %s' % (type(e).__name__, str(e)[:200])
            rec['traceback'] = traceback.format_exc()[-800:]
        finally:
            signal.alarm(0)
        rec['seconds'] = round(time.time() - tp, 1)
        out['pages'].append(rec)
    kinds = collections.Counter(p.get('kind') for p in out['pages'])
    out['status'] = 'failed' if kinds.get('failed') == len(out['pages']) else (
        'partial' if kinds.get('failed') else 'ok')
    out['seconds'] = round(time.time() - t0, 1)
    return out


def summarize(results, total_files, total_pages_est):
    import status
    pages = [p for r in results for p in r.get('pages', [])]
    scores = [p['validation']['iou_tol1px'] for p in pages if 'iou_tol1px' in p.get('validation', {})]
    strict = [p['validation']['iou_strict'] for p in pages if 'iou_strict' in p.get('validation', {})]
    kinds = collections.Counter(p.get('kind') for p in pages)
    fails = [{'relpath': r['canonical_relpath'], 'sha256': r['sha256'], 'reason': r.get('reason')}
             for r in results if r.get('status') == 'unreadable']
    fails += [{'relpath': r['canonical_relpath'], 'page': p['page'], 'reason': p.get('error')}
              for r in results for p in r.get('pages', []) if p.get('error')]
    flagged = [{'relpath': r['canonical_relpath'], 'page': p['page'], 'iou_tol1px': p['validation']['iou_tol1px'],
                'iou_strict': p['validation']['iou_strict']}
               for r in results for p in r.get('pages', []) if p.get('validation', {}).get('status') == 'flagged']
    hist = collections.Counter()
    for s in scores:
        hist['>=0.99' if s >= 0.99 else '0.95-0.99' if s >= 0.95 else '0.90-0.95' if s >= 0.9 else '<0.90'] += 1
    return {
        'stage': 'running' if len(results) < total_files else 'done',
        'distinct_pdfs_total': total_files, 'distinct_pdfs_done': len(results),
        'relpaths_total': sum(len(r['relpaths']) for r in results),
        'pages_done': len(pages), 'pages_by_kind': dict(kinds),
        'dxf_written': sum(1 for p in pages if p.get('dxf')),
        'validated_pages': len(scores),
        'iou_tol1px': {'min': min(scores) if scores else None, 'mean': round(sum(scores) / len(scores), 4) if scores else None,
                       'histogram': dict(hist), 'below_0.9': len(flagged)},
        'iou_strict_mean': round(sum(strict) / len(strict), 4) if strict else None,
        'metric': 'ink = gray<235 at 150 dpi on the pdftoppm grid; iou_tol1px = Jaccard with 1-px (0.17 mm) match '
                  'tolerance (TP averaged over both directions); iou_strict = exact-pixel IoU after best global shift',
        'failures': fails[:200], 'flagged_pages': flagged[:300],
    }


def main():
    import status
    nproc = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 24
    limit = None
    only = None
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    if '--only' in sys.argv:
        only = set(sys.argv[sys.argv.index('--only') + 1].split(','))
    groups = load_jobs()
    done = {}
    if os.path.exists(RES):
        for l in open(RES):
            try:
                r = json.loads(l)
                done[r['sha256']] = r
            except Exception:
                pass
    redo = '--redo' in sys.argv
    todo = [(h, rels) for h, rels in groups.items() if (redo or h not in done) and (only is None or h in only)]
    todo.sort(key=lambda j: -os.path.getsize(SRC + j[1][0]))
    if limit:
        todo = todo[:limit]
    total = len(groups) if only is None and limit is None else len(set(h for h, _ in todo) | set(done))
    print('jobs', len(todo), 'already done', len(done), flush=True)
    last = 0
    with mp.get_context('fork').Pool(nproc, maxtasksperchild=8) as pool, open(RES, 'a') as fo:
        for r in pool.imap_unordered(work, todo):
            fo.write(json.dumps(r, default=str) + '\n')
            fo.flush()
            done[r['sha256']] = r
            if time.time() - last > 30:
                status.put_part('pdf', summarize(list(done.values()), total, 0))
                last = time.time()
    results = list(done.values())
    s = summarize(results, total, 0)
    s['stage'] = 'converted+validated (sync pending)'
    status.put_part('pdf', s)
    print('done', len(results), flush=True)


if __name__ == '__main__':
    main()
