#!/usr/bin/env python3
"""validate_heavy.py [NCHUNK] - validation for pages whose single-process render timed out: the page DXF is rendered
in NCHUNK entity ranges in parallel (ezdxf drawing add-on, same page grid), ink masks are OR-ed and compared with the
150-dpi PNG. Approximation vs the single render: opaque white fills only mask ink of their own chunk."""
import json, os, sys, time
import multiprocessing as mp
import numpy as np

sys.path.insert(0, '/work/2d')
OUT = '/work/2d/out/dxf_from_pdf/'
RES = '/work/2d/state/pdf_results.jsonl'


def render_chunk(a):
    dxfp, w_mm, h_mm, i, n = a
    import ezdxf, pymupdf
    import pdf2dxf as P
    from ezdxf.addons.drawing import RenderContext, Frontend, layout
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy, LineweightPolicy, ImagePolicy
    from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
    from ezdxf.math import BoundingBox2d
    cwd = os.getcwd()
    os.chdir(os.path.dirname(dxfp))
    doc = ezdxf.readfile(os.path.basename(dxfp))
    ents = list(doc.modelspace())
    k = len(ents)
    sub = ents[k * i // n: k * (i + 1) // n]
    be = PyMuPdfBackend()
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR,
                        lineweight_policy=LineweightPolicy.ABSOLUTE, lineweight_scaling=1.0, min_lineweight=2.0,
                        image_policy=ImagePolicy.DISPLAY)
    fe = Frontend(RenderContext(doc), be, config=cfg)
    fe.draw_entities(sub)
    be.finalize()
    pg = layout.Page(w_mm, h_mm, layout.Units.mm, margins=layout.Margins.all(0))
    pdf = be.get_pdf_bytes(pg, settings=layout.Settings(fit_page=False, scale=1.0),
                           render_box=BoundingBox2d([(0, 0), (w_mm, h_mm)]))
    os.chdir(cwd)
    d = pymupdf.open('pdf', pdf)
    p = d[0]
    z = 150 / 72.0 * (w_mm / P.PT) / p.rect.width
    pix = p.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
    m = P.ink_mask(pix.tobytes('png'))
    return i, np.packbits(m), m.shape


def main():
    import pdf2dxf as P
    import status
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    recs = {}
    for l in open(RES):
        r = json.loads(l)
        recs[r['sha256']] = r
    todo = [(r, p) for r in recs.values() for p in r.get('pages', []) if p.get('dxf') and 'timeout' in (p.get('error') or '')]
    print('pages to validate', len(todo), flush=True)
    with open(RES, 'a') as fo:
        for r, p in todo:
            t = time.time()
            dxfp = OUT + p['dxf']
            with mp.get_context('spawn').Pool(n) as pool:
                parts = pool.map(render_chunk, [(dxfp, p['w_mm'], p['h_mm'], i, n) for i in range(n)])
            m = None
            for i, bits, shape in parts:
                mm = np.unpackbits(bits)[:shape[0] * shape[1]].reshape(shape).astype(bool)
                m = mm if m is None else (m | mm)
            import glob
            cand = sorted(glob.glob('/work/out/png/' + glob.escape(r['canonical_relpath']) + '/page-*%d.png' % p['page']))
            ref = P.ink_mask(cand[0])
            res, sh = P.compare(ref, m)
            res['status'] = 'ok' if res['iou_tol1px'] >= 0.9 else 'flagged'
            res['method'] = 'chunked render (%d entity ranges, OR of ink masks)' % n
            res['t_validate'] = round(time.time() - t, 1)
            p['validation'] = res
            p['error_resolved'] = p.pop('error')
            print(r['canonical_relpath'][-50:], p['page'], res, flush=True)
            fo.write(json.dumps(r, default=str) + '\n')
            fo.flush()


if __name__ == '__main__':
    main()
