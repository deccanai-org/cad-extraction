#!/usr/bin/env python3
"""pdf2dxf.py - vector PDF page -> ezdxf R2018 ASCII DXF (paper mm, y up) + raster validation.

Geometry (PyMuPDF page.get_drawings(extended=True), in content-stream order = draw order):
  lines            -> LWPOLYLINE (one per connected run; closed when the run returns to its start) / LINE (single segment)
  cubic Beziers    -> SPLINE, degree 3, clamped knots with multiplicity 3 at joints (mathematically identical to the PDF curve)
  re / qu          -> closed LWPOLYLINE
  fills            -> solid HATCH (odd-parity); boundaries = polyline paths, or edge paths with line + exact spline edges
  clip paths       -> geometry is clipped against the active clip rectangle (exact for rectangular clips; non-rectangular
                      clips use their bounding box and are counted in stats as clip_nonrect)
  images           -> IMAGE entity + PNG side file (page-<n>_img<k>.png, alpha from SMask), placed with the PDF image matrix
Text (page.get_text('rawdict')): TEXT per span at the baseline origin, rotation from the line direction, height = font
  size x cap-height ratio of the embedded font, width factor calibrated so the string advance equals the PDF advance.
Layers: S_<RRGGBB>_W<width mm> (stroke), F_<RRGGBB> (fill), T_<RRGGBB> (text), IMAGES; entities are BYLAYER.
Units: 1 PDF pt = 25.4/72 mm; origin = lower-left corner of the page; $INSUNITS = 4 (mm).
"""
import io, math, os, re, sys, json, time
import numpy as np
import pymupdf
import ezdxf
from ezdxf import colors as ezcolors

PT = 25.4 / 72.0
LW = [0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211]
CODE_VERSION = 'd2-pdf2dxf-2026-09-30c'

# Rendering-only font substitutes (metric-compatible Liberation fonts under the Windows/AutoCAD file names the DXF
# styles reference). The DXF itself references arial.ttf / arialbd.ttf / arialn.ttf / romans.shx / romant.shx ...
FONT_DIR = '/work/2d/fonts'
_SUBST = {'arial.ttf': 'LiberationSans-Regular.ttf', 'arialbd.ttf': 'LiberationSans-Bold.ttf',
          'ariali.ttf': 'LiberationSans-Italic.ttf', 'arialbi.ttf': 'LiberationSans-BoldItalic.ttf',
          'arialn.ttf': 'LiberationSansNarrow-Regular.ttf', 'arialnb.ttf': 'LiberationSansNarrow-Bold.ttf',
          'times.ttf': 'LiberationSerif-Regular.ttf', 'timesbd.ttf': 'LiberationSerif-Bold.ttf',
          'timesi.ttf': 'LiberationSerif-Italic.ttf', 'timesbi.ttf': 'LiberationSerif-BoldItalic.ttf',
          'cour.ttf': 'LiberationMono-Regular.ttf', 'courbd.ttf': 'LiberationMono-Bold.ttf',
          'calibri.ttf': 'LiberationSans-Regular.ttf', 'calibrib.ttf': 'LiberationSans-Bold.ttf',
          'romans__.ttf': 'LiberationSans-Regular.ttf', 'romant__.ttf': 'LiberationSerif-Regular.ttf',
          'romand__.ttf': 'LiberationSans-Regular.ttf', 'romanc__.ttf': 'LiberationSerif-Regular.ttf'}


def setup_fonts():
    lib = '/usr/share/fonts/truetype/liberation'
    os.makedirs(FONT_DIR, exist_ok=True)
    for k, v in _SUBST.items():
        dst = os.path.join(FONT_DIR, k)
        if not os.path.exists(dst) and os.path.exists(os.path.join(lib, v)):
            try:
                os.symlink(os.path.join(lib, v), dst)
            except FileExistsError:
                pass
    from ezdxf.fonts import fonts
    for k in ('ROMANT', 'ROMAND', 'ROMANC'):
        fonts.SHX_FONTS[k] = fonts.SHX_FONTS[k + '.SHX'] = k.lower() + '__.ttf'
    ezdxf.options.support_dirs = [FONT_DIR]
    fonts.font_manager.build([FONT_DIR, '/usr/share/fonts'], support_dirs=False)


setup_fonts()


def lw_of(w_mm):
    return min(LW, key=lambda v: abs(v / 100.0 - w_mm))


def hexcol(c):
    if c is None:
        return None
    if isinstance(c, int):
        return '%06X' % c
    if len(c) == 1:
        c = (c[0], c[0], c[0])
    elif len(c) == 4:  # CMYK -> RGB
        k = c[3]
        c = ((1 - c[0]) * (1 - k), (1 - c[1]) * (1 - k), (1 - c[2]) * (1 - k))
    return '%02X%02X%02X' % tuple(max(0, min(255, int(round(v * 255)))) for v in c[:3])


# ---------------------------------------------------------------- clipping helpers (page coords, y down)
def clip_seg(p, q, r):
    """Liang-Barsky: clip segment p-q to rect r=(x0,y0,x1,y1); returns (p',q') or None."""
    x0, y0 = p
    dx, dy = q[0] - x0, q[1] - y0
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0 - r[0]), (dx, r[2] - x0), (-dy, y0 - r[1]), (dy, r[3] - y0)):
        if pp == 0:
            if qq < 0:
                return None
        else:
            t = qq / pp
            if pp < 0:
                if t > t1:
                    return None
                if t > t0:
                    t0 = t
            else:
                if t < t0:
                    return None
                if t < t1:
                    t1 = t
    return (x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy)


def clip_poly(pts, r):
    """Sutherland-Hodgman polygon clip against rect r (convex)."""
    def clip_edge(pts, inside, inter):
        out = []
        n = len(pts)
        for i in range(n):
            a, b = pts[i - 1], pts[i]
            ia, ib = inside(a), inside(b)
            if ib:
                if not ia:
                    out.append(inter(a, b))
                out.append(b)
            elif ia:
                out.append(inter(a, b))
        return out

    def ix(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / ((b[0] - a[0]) or 1e-12))

    def iy(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / ((b[1] - a[1]) or 1e-12), y)

    for inside, inter in ((lambda p: p[0] >= r[0], ix(r[0])), (lambda p: p[0] <= r[2], ix(r[2])),
                          (lambda p: p[1] >= r[1], iy(r[1])), (lambda p: p[1] <= r[3], iy(r[3]))):
        if not pts:
            break
        pts = clip_edge(pts, inside, inter)
    return pts


def bez_pts(p0, p1, p2, p3, n):
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def bez_n(p0, p1, p2, p3, tol_pt=0.03):
    L = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
    return max(2, min(128, int(math.ceil(math.sqrt(L / tol_pt) * 0.6)) + 1))


def inside_rect(b, r):
    return b[0] >= r[0] - 1e-6 and b[1] >= r[1] - 1e-6 and b[2] <= r[2] + 1e-6 and b[3] <= r[3] + 1e-6


def disjoint(b, r):
    return b[2] < r[0] or b[0] > r[2] or b[3] < r[1] or b[1] > r[3]


def rect_isect(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


# ---------------------------------------------------------------- font helpers
FONT_CACHE = {}


def font_map(name, flags):
    n = (name or '').split('+')[-1].lower().replace(' ', '')
    bold = bool(flags & 16) or 'bold' in n or ',bd' in n
    ital = bool(flags & 2) or 'italic' in n or 'oblique' in n
    m = re.match(r'roman([sdtc])', n)
    if m:
        return 'ROMAN' + m.group(1).upper(), 'roman%s.shx' % m.group(1)
    if 'narrow' in n:
        return ('ARIALN_B', 'arialnb.ttf') if bold else ('ARIALN', 'arialn.ttf')
    if n.startswith('times'):
        f = 'timesbi.ttf' if bold and ital else 'timesbd.ttf' if bold else 'timesi.ttf' if ital else 'times.ttf'
        return f.split('.')[0].upper(), f
    if n.startswith('cour'):
        f = 'courbd.ttf' if bold else 'cour.ttf'
        return f.split('.')[0].upper(), f
    if n.startswith('calibri'):
        f = 'calibrib.ttf' if bold else 'calibri.ttf'
        return f.split('.')[0].upper(), f
    f = 'arialbi.ttf' if bold and ital else 'arialbd.ttf' if bold else 'ariali.ttf' if ital else 'arial.ttf'
    return f.split('.')[0].upper(), f


def cap_ratio_of_pdf_font(doc, page, fontname, cache):
    """cap height / em of the embedded font (fontTools); None if unknown."""
    key = fontname
    if key in cache:
        return cache[key]
    val = None
    try:
        from fontTools.ttLib import TTFont
        for f in page.get_fonts(full=True):
            if f[3].split('+')[-1] == fontname.split('+')[-1] or f[3] == fontname:
                ext, buf = doc.extract_font(f[0])[1], doc.extract_font(f[0])[3]
                if not buf:
                    break
                tt = TTFont(io.BytesIO(buf), lazy=True)
                upm = tt['head'].unitsPerEm
                if 'OS/2' in tt and getattr(tt['OS/2'], 'sCapHeight', 0):
                    val = tt['OS/2'].sCapHeight / upm
                elif 'glyf' in tt:
                    g = tt['glyf']
                    cmap = tt.getBestCmap() or {}
                    ys = []
                    for ch in 'HEIKLMNTZ':
                        gn = cmap.get(ord(ch))
                        if gn and gn in g.keys():
                            gl = g[gn]
                            if hasattr(gl, 'yMax') and gl.numberOfContours:
                                ys.append(gl.yMax)
                    if ys:
                        val = max(ys) / upm
                break
    except Exception:
        val = None
    if val is not None and not (0.4 < val < 1.0):
        val = None
    cache[key] = val
    return val


DEFAULT_CAP = {'arial': 0.716, 'roman': 0.72, 'times': 0.662, 'cour': 0.571, 'calibri': 0.644}


def ezfont(fontfile, h):
    from ezdxf.fonts import fonts
    k = fontfile
    if k not in FONT_CACHE:
        try:
            FONT_CACHE[k] = fonts.make_font(fontfile, cap_height=1.0, width_factor=1.0)
        except Exception:
            FONT_CACHE[k] = None
    return FONT_CACHE[k]


# ---------------------------------------------------------------- converter
_BAKED = {}


def baked_doc(doc):
    """copy of doc with annotations/widgets flattened into page content (so review comments become geometry/text)."""
    k = id(doc)
    if k not in _BAKED:
        d2 = pymupdf.open('pdf', doc.tobytes())
        d2.bake(annots=True, widgets=True)
        _BAKED.clear()
        _BAKED[k] = (doc, d2)
    return _BAKED[k][1]


def annot_info(page):
    out = []
    for a in page.annots() or []:
        try:
            out.append({'type': a.type[1], 'content': (a.info.get('content') or '')[:1000],
                        'subject': a.info.get('subject') or '',
                        'rect_mm': [round(a.rect.x0 * PT, 1), round((page.rect.y1 - a.rect.y1) * PT, 1),
                                    round(a.rect.x1 * PT, 1), round((page.rect.y1 - a.rect.y0) * PT, 1)]})
        except Exception as e:
            out.append({'error': str(e)[:80]})
    return out


class PageConverter:
    def __init__(self, doc, pno, dxf_path):
        self.doc = doc
        self.page = doc[pno]
        self.orig_page = self.page
        self.prefix = ''
        self.annots = []
        if self.page.first_annot is not None:
            self.annots = annot_info(self.page)
            self.doc = baked_doc(doc)
            self.page = self.doc[pno]
        self.pno = pno
        self.dxf_path = dxf_path
        r = self.page.rect
        self.rx0, self.ry0, self.rx1, self.ry1 = r.x0, r.y0, r.x1, r.y1
        self.W_mm = r.width * PT
        self.H_mm = r.height * PT
        self.stats = dict(paths=0, lwpolyline=0, line=0, spline=0, hatch=0, text=0, image=0, clip=0, clip_nonrect=0,
                          clipped_paths=0, dropped_outside_clip=0, dashes=0, flattened_beziers_in_clip=0,
                          transparent=0, rawtext_skipped=0, beziers=0, segments=0,
                          annotations_baked=len(self.annots))
        self.layers = {}
        self.fcache = {}

    def T(self, p):
        return ((p[0] - self.rx0) * PT, (self.ry1 - p[1]) * PT)

    # -- layers
    def layer(self, kind, col, w_mm=None):
        name = self.prefix + '%s_%s' % (kind, col) + ('_W%.3f' % w_mm if w_mm is not None else '')
        if name not in self.layers:
            lay = self.dxf.layers.add(name)
            rgb = tuple(int(col[i:i + 2], 16) for i in (0, 2, 4))
            lay.rgb = rgb
            lay.color = 7 if rgb in ((0, 0, 0), (255, 255, 255)) else 8
            if w_mm is not None:
                lay.dxf.lineweight = lw_of(w_mm)
            self.layers[name] = lay
        return name

    def linetype(self, dashes):
        m = re.match(r'\[\s*([^\]]*)\]\s*([-\d.]+)', dashes or '')
        if not m or not m.group(1).strip():
            return None
        vals = [float(v) * PT for v in m.group(1).split()]
        if not vals or sum(vals) <= 0:
            return None
        if len(vals) % 2:
            vals = vals * 2
        name = 'PDF_DASH_' + '_'.join('%.2f' % v for v in vals).replace('.', 'p')
        if name not in self.dxf.linetypes:
            pattern = [sum(vals)]
            for i, v in enumerate(vals):
                pattern.append(v if i % 2 == 0 else -v)
            self.dxf.linetypes.add(name, pattern=pattern, description='PDF dash ' + m.group(0))
        return name

    # -- geometry: split path items into subpaths of segments
    @staticmethod
    def subpaths(items):
        subs = []
        cur = []
        last = None
        for it in items:
            op = it[0]
            if op == 'l':
                a, b = (it[1].x, it[1].y), (it[2].x, it[2].y)
                if last is None or math.dist(last, a) > 1e-4:
                    if cur:
                        subs.append(cur)
                    cur = []
                cur.append(('l', a, b))
                last = b
            elif op == 'c':
                a, c1, c2, b = [(q.x, q.y) for q in it[1:5]]
                if last is None or math.dist(last, a) > 1e-4:
                    if cur:
                        subs.append(cur)
                    cur = []
                cur.append(('c', a, c1, c2, b))
                last = b
            elif op == 're':
                rr = it[1]
                if cur:
                    subs.append(cur)
                cur = []
                pts = [(rr.x0, rr.y0), (rr.x1, rr.y0), (rr.x1, rr.y1), (rr.x0, rr.y1)]
                subs.append([('l', pts[i], pts[(i + 1) % 4]) for i in range(4)])
                last = None
            elif op == 'qu':
                qd = it[1]
                if cur:
                    subs.append(cur)
                cur = []
                pts = [(qd.ul.x, qd.ul.y), (qd.ur.x, qd.ur.y), (qd.lr.x, qd.lr.y), (qd.ll.x, qd.ll.y)]
                subs.append([('l', pts[i], pts[(i + 1) % 4]) for i in range(4)])
                last = None
        if cur:
            subs.append(cur)
        return subs

    @staticmethod
    def sub_bbox(sub):
        xs = [p[0] for s in sub for p in s[1:]]
        ys = [p[1] for s in sub for p in s[1:]]
        return (min(xs), min(ys), max(xs), max(ys))

    def clip_stroke_sub(self, sub, r):
        """returns list of segment-runs (each run = list of segments) clipped to r."""
        runs = []
        cur = []
        last = None

        def push(seg):
            nonlocal cur, last
            a = seg[1]
            if last is None or math.dist(last, a) > 1e-6:
                if cur:
                    runs.append(cur)
                cur = []
            cur.append(seg)
            last = seg[-1]

        for s in sub:
            if s[0] == 'l':
                c = clip_seg(s[1], s[2], r)
                if c:
                    push(('l', c[0], c[1]))
            else:
                bb = (min(p[0] for p in s[1:]), min(p[1] for p in s[1:]), max(p[0] for p in s[1:]), max(p[1] for p in s[1:]))
                if inside_rect(bb, r):
                    push(s)
                elif disjoint(bb, r):
                    continue
                else:
                    self.stats['flattened_beziers_in_clip'] += 1
                    pts = [s[1]] + bez_pts(s[1], s[2], s[3], s[4], bez_n(s[1], s[2], s[3], s[4]))
                    for i in range(len(pts) - 1):
                        c = clip_seg(pts[i], pts[i + 1], r)
                        if c:
                            push(('l', c[0], c[1]))
        if cur:
            runs.append(cur)
        return runs

    def emit_stroke_run(self, msp, run, attribs):
        """run: connected list of segments; lines -> LWPOLYLINE, bezier chains -> SPLINE."""
        closed_run = len(run) > 1 and math.dist(run[0][1], run[-1][-1]) < 1e-4
        # group consecutive same-kind segments
        groups = []
        for s in run:
            if groups and groups[-1][0] == s[0]:
                groups[-1][1].append(s)
            else:
                groups.append((s[0], [s]))
        for kind, segs in groups:
            if kind == 'l':
                pts = [self.T(segs[0][1])] + [self.T(s[2]) for s in segs]
                self.stats['segments'] += len(segs)
                if len(groups) == 1 and closed_run and len(pts) > 3:
                    msp.add_lwpolyline(pts[:-1], close=True, dxfattribs=attribs)
                    self.stats['lwpolyline'] += 1
                elif len(pts) == 2:
                    msp.add_line(pts[0], pts[1], dxfattribs=attribs)
                    self.stats['line'] += 1
                else:
                    msp.add_lwpolyline(pts, close=False, dxfattribs=attribs)
                    self.stats['lwpolyline'] += 1
            else:
                cps = [self.T(segs[0][1])]
                for s in segs:
                    cps += [self.T(s[2]), self.T(s[3]), self.T(s[4])]
                n = len(segs)
                knots = [0.0] * 4 + [float(i) for i in range(1, n) for _ in range(3)] + [float(n)] * 4
                sp = msp.add_open_spline(cps, degree=3, knots=knots, dxfattribs=attribs)
                if closed_run and len(groups) == 1:
                    sp.closed = False  # geometry already returns to start; keep as clamped open spline
                self.stats['spline'] += 1
                self.stats['beziers'] += n

    def emit_fill(self, msp, subs, attribs, clip):
        hatch = msp.add_hatch(dxfattribs=attribs)
        hatch.set_solid_fill(color=256, style=0)
        npaths = 0
        for sub in subs:
            has_c = any(s[0] == 'c' for s in sub)
            if clip is not None and not inside_rect(self.sub_bbox(sub), clip):
                # flatten + polygon clip
                pts = [sub[0][1]]
                for s in sub:
                    if s[0] == 'l':
                        pts.append(s[2])
                    else:
                        pts += bez_pts(s[1], s[2], s[3], s[4], bez_n(s[1], s[2], s[3], s[4]))
                pts = clip_poly(pts, clip)
                if len(pts) >= 3:
                    hatch.paths.add_polyline_path([self.T(p) for p in pts], is_closed=True)
                    npaths += 1
                continue
            if not has_c:
                pts = [self.T(sub[0][1])] + [self.T(s[2]) for s in sub]
                if len(pts) > 1 and math.dist(pts[0], pts[-1]) < 1e-6:
                    pts = pts[:-1]
                if len(pts) >= 2:
                    hatch.paths.add_polyline_path(pts, is_closed=True)
                    npaths += 1
            else:
                ep = hatch.paths.add_edge_path()
                for s in sub:
                    if s[0] == 'l':
                        ep.add_line(self.T(s[1]), self.T(s[2]))
                    else:
                        ep.add_spline(control_points=[self.T(s[1]), self.T(s[2]), self.T(s[3]), self.T(s[4])],
                                      knot_values=[0, 0, 0, 0, 1, 1, 1, 1], degree=3)
                end, start = sub[-1][-1], sub[0][1]
                if math.dist(end, start) > 1e-6:
                    ep.add_line(self.T(end), self.T(start))
                npaths += 1
        if npaths == 0:
            msp.delete_entity(hatch)
            return None
        self.stats['hatch'] += 1
        return hatch

    def convert(self, img_prefix):
        doc = ezdxf.new('R2018', setup=False, units=4)
        self.dxf = doc
        msp = doc.modelspace()
        doc.header['$MEASUREMENT'] = 1
        doc.header['$LIMMIN'] = (0, 0)
        doc.header['$LIMMAX'] = (self.W_mm, self.H_mm)
        doc.header['$EXTMIN'] = (0, 0, 0)
        doc.header['$EXTMAX'] = (self.W_mm, self.H_mm, 0)
        doc.header['$LWDISPLAY'] = 1
        page = self.page
        # ---- vector paths
        drawings = page.get_drawings(extended=True)
        n0 = len(drawings)
        if self.annots:
            # baked page = original content first, then the annotation appearance streams -> ANNOT_ layers
            orig = self.orig_page.get_drawings(extended=True)
            n0 = len(orig)
            same = n0 <= len(drawings) and all(
                a.get('type') == b.get('type') and a.get('rect') == b.get('rect') for a, b in zip(orig[:200], drawings[:200]))
            if not same:
                n0 = len(drawings)
                self.stats['annot_split_failed'] = 1
            self.stats['annot_paths'] = len(drawings) - n0
        stack = []  # (level, rect or None)
        for di, d in enumerate(drawings):
            self.prefix = 'ANNOT_' if di >= n0 else ''
            typ = d.get('type')
            lvl = d.get('level', 0)
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            if typ in ('clip', 'group'):
                r = None
                if typ == 'clip':
                    self.stats['clip'] += 1
                    sc = d.get('scissor')
                    r = (sc.x0, sc.y0, sc.x1, sc.y1) if sc is not None else None
                    its = d.get('items') or []
                    rect_like = (len(its) == 1 and its[0][0] == 're') or (
                        len(its) == 1 and its[0][0] == 'qu' and its[0][1].is_rectangular)
                    if not rect_like:
                        # 4 axis-aligned lines forming a rect also count
                        ok = False
                        if len(its) in (4, 5) and all(i[0] == 'l' for i in its):
                            ok = all(abs(i[1].x - i[2].x) < 1e-3 or abs(i[1].y - i[2].y) < 1e-3 for i in its)
                        if not ok:
                            self.stats['clip_nonrect'] += 1
                prev = stack[-1][1] if stack else None
                stack.append((lvl, rect_isect(prev, r) if r is not None else prev))
                continue
            clip = stack[-1][1] if stack else None
            self.stats['paths'] += 1
            items = d.get('items') or []
            if not items:
                continue
            prect = d.get('rect')
            pb = (prect.x0, prect.y0, prect.x1, prect.y1) if prect is not None else None
            if clip is not None and pb is not None:
                if clip[2] <= clip[0] or clip[3] <= clip[1] or disjoint(pb, clip):
                    self.stats['dropped_outside_clip'] += 1
                    continue
                if inside_rect(pb, clip):
                    clip_eff = None
                else:
                    clip_eff = clip
                    self.stats['clipped_paths'] += 1
            else:
                clip_eff = None
            subs = self.subpaths(items)
            if not subs:
                continue
            if d.get('closePath'):
                for sub in subs:
                    if math.dist(sub[0][1], sub[-1][-1]) > 1e-4:
                        sub.append(('l', sub[-1][-1], sub[0][1]))
            # fill first (PDF paints fill before stroke)
            if typ in ('f', 'fs') and d.get('fill') is not None:
                col = hexcol(d['fill'])
                at = {'layer': self.layer('F', col)}
                op = d.get('fill_opacity')
                hatch = self.emit_fill(msp, subs, at, clip_eff)
                if hatch is not None and op is not None and op < 0.999:
                    hatch.transparency = max(0.0, min(1.0, 1 - op))
                    self.stats['transparent'] += 1
            if typ in ('s', 'fs') and d.get('color') is not None:
                col = hexcol(d['color'])
                w_mm = (d.get('width') or 0.0) * PT
                at = {'layer': self.layer('S', col, round(w_mm, 3))}
                lt = self.linetype(d.get('dashes'))
                if lt:
                    at['linetype'] = lt
                    self.stats['dashes'] += 1
                op = d.get('stroke_opacity')
                n0 = len(msp)
                for sub in subs:
                    runs = self.clip_stroke_sub(sub, clip_eff) if clip_eff is not None else [sub]
                    for run in runs:
                        self.emit_stroke_run(msp, run, at)
                if op is not None and op < 0.999:
                    self.stats['transparent'] += 1
                    for e in list(msp)[n0:]:
                        e.transparency = max(0.0, min(1.0, 1 - op))
        self.prefix = ''
        # ---- images
        self.emit_images(msp, img_prefix)
        # ---- text
        self.emit_text(msp)
        doc.header.custom_vars.append('D2_CONVERTER', CODE_VERSION)
        return doc

    def emit_images(self, msp, img_prefix):
        page, doc = self.page, self.doc
        try:
            infos = page.get_image_info(xrefs=True)
        except Exception:
            infos = []
        cache = {}
        k = 0
        n_img0 = len(infos)
        if self.annots:
            try:
                n_img0 = len(self.orig_page.get_image_info())
            except Exception:
                pass
        for ii, info in enumerate(infos):
            xref = info.get('xref', 0)
            tr = info.get('transform')
            if tr is None:
                continue
            m = pymupdf.Matrix(tr)
            try:
                if xref and xref in cache:
                    fn, w, h = cache[xref]
                else:
                    pix = None
                    if xref:
                        pix = pymupdf.Pixmap(doc, xref)
                        try:
                            sm = doc.extract_image(xref).get('smask', 0)
                        except Exception:
                            sm = 0
                        if pix.colorspace is not None and pix.colorspace.n not in (1, 3):
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        if sm:
                            try:
                                mask = pymupdf.Pixmap(doc, sm)
                                if pix.alpha:
                                    pix = pymupdf.Pixmap(pix, 0)
                                pix = pymupdf.Pixmap(pix, mask)
                            except Exception:
                                pass
                    if pix is None:
                        continue
                    k += 1
                    fn = '%s_img%d.png' % (img_prefix, k)
                    pix.save(os.path.join(os.path.dirname(self.dxf_path), fn))
                    w, h = pix.width, pix.height
                    if xref:
                        cache[xref] = (fn, w, h)
                ptl = pymupdf.Point(0, 0) * m
                ptr = pymupdf.Point(1, 0) * m
                pbl = pymupdf.Point(0, 1) * m
                TL, TR, BL = self.T((ptl.x, ptl.y)), self.T((ptr.x, ptr.y)), self.T((pbl.x, pbl.y))
                idef = self.dxf.add_image_def(filename=fn, size_in_pixel=(w, h))
                img = msp.add_image(idef, insert=BL, size_in_units=(1, 1), rotation=0,
                                    dxfattribs={'layer': 'ANNOT_IMAGES' if ii >= n_img0 else 'IMAGES'})
                img.dxf.u_pixel = ((TR[0] - TL[0]) / w, (TR[1] - TL[1]) / w, 0)
                img.dxf.v_pixel = ((TL[0] - BL[0]) / h, (TL[1] - BL[1]) / h, 0)
                img.reset_boundary_path()
                self.stats['image'] += 1
            except Exception as e:
                self.stats.setdefault('image_errors', []).append(str(e)[:80])

    def emit_text(self, msp):
        page, doc = self.page, self.doc
        flags = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_MEDIABOX_CLIP
        try:
            td = page.get_text('rawdict', flags=flags)
        except Exception:
            return
        styles = {}
        orig_keys = None
        if self.annots:
            orig_keys = set()
            try:
                for b0 in self.orig_page.get_text('dict', flags=flags).get('blocks', []):
                    for l0 in b0.get('lines', []):
                        for s0 in l0['spans']:
                            orig_keys.add((s0['text'].strip(), round(s0['origin'][0], 1), round(s0['origin'][1], 1)))
            except Exception:
                orig_keys = None
        for b in td.get('blocks', []):
            if b.get('type') != 0:
                continue
            for ln in b['lines']:
                dx, dy = ln['dir']
                ang = math.degrees(math.atan2(-dy, dx))
                for sp in ln['spans']:
                    chars = sp.get('chars') or []
                    text = ''.join(c['c'] for c in chars)
                    if not text.strip():
                        continue
                    self.prefix = '' if orig_keys is None or (text.strip(), round(sp['origin'][0], 1), round(sp['origin'][1], 1)) in orig_keys else 'ANNOT_'
                    if sp.get('alpha', 255) == 0:
                        self.stats['rawtext_skipped'] += 1
                        continue
                    size = sp['size']
                    sname, ffile = font_map(sp['font'], sp.get('flags', 0))
                    if sname not in styles:
                        if sname not in self.dxf.styles:
                            self.dxf.styles.add(sname, font=ffile)
                        styles[sname] = True
                    cr = cap_ratio_of_pdf_font(doc, page, sp['font'], self.fcache)
                    if cr is None:
                        base = next((v for k, v in DEFAULT_CAP.items() if ffile.startswith(k)), 0.716)
                        cr = base
                    h = size * cr
                    o = chars[0]['origin']
                    # advance along the writing direction
                    last = chars[-1]
                    bx = last['bbox']
                    if abs(dy) < 1e-3:
                        adv_last = abs(bx[2] - bx[0])
                    elif abs(dx) < 1e-3:
                        adv_last = abs(bx[3] - bx[1])
                    else:
                        adv_last = None
                    L = (last['origin'][0] - o[0]) * dx + (last['origin'][1] - o[1]) * dy
                    if adv_last is None:
                        adv_last = (L / (len(chars) - 1)) if len(chars) > 1 else size * 0.5
                    L = (L + adv_last) * PT
                    col = hexcol(sp.get('color', 0))
                    ins = self.T(o)
                    t = msp.add_text(text, height=h * PT, rotation=ang,
                                     dxfattribs={'layer': self.layer('T', col), 'style': sname, 'insert': ins})
                    f = ezfont(ffile, 1.0)
                    if f is not None and L > 0:
                        try:
                            wref = f.text_width(text) * h * PT
                            if wref > 0:
                                wf = L / wref
                                if 0.2 < wf < 5 and abs(wf - 1) > 0.002:
                                    t.dxf.width = round(wf, 4)
                        except Exception:
                            pass
                    self.stats['text'] += 1


# ---------------------------------------------------------------- page classification
def classify_page(page):
    """vector | raster | empty (cheap)."""
    area = page.rect.width * page.rect.height
    try:
        ninfo = page.get_image_info()
    except Exception:
        ninfo = []
    img_area = 0.0
    for i in ninfo:
        b = pymupdf.Rect(i['bbox']) & page.rect
        img_area += max(0, b.width) * max(0, b.height)
    return img_area / area if area else 0.0


# ---------------------------------------------------------------- validation
def render_dxf(dxf_path, w_mm, h_mm, dpi=150):
    from ezdxf.addons.drawing import RenderContext, Frontend, layout
    from ezdxf.addons.drawing.config import (Configuration, BackgroundPolicy, ColorPolicy, LineweightPolicy,
                                             ImagePolicy)
    from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
    from ezdxf.math import BoundingBox2d
    cwd = os.getcwd()
    os.chdir(os.path.dirname(os.path.abspath(dxf_path)))
    try:
        doc = ezdxf.readfile(os.path.basename(dxf_path))
        ctx = RenderContext(doc)
        be = PyMuPdfBackend()
        cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR,
                            lineweight_policy=LineweightPolicy.ABSOLUTE, lineweight_scaling=1.0, min_lineweight=2.0,
                            image_policy=ImagePolicy.DISPLAY)
        Frontend(ctx, be, config=cfg).draw_layout(doc.modelspace(), finalize=True)
        pg = layout.Page(w_mm, h_mm, layout.Units.mm, margins=layout.Margins.all(0))
        pdf = be.get_pdf_bytes(pg, settings=layout.Settings(fit_page=False, scale=1.0),
                               render_box=BoundingBox2d([(0, 0), (w_mm, h_mm)]))
    finally:
        os.chdir(cwd)
    # rasterise on the same pixel grid as pdftoppm -r dpi (pixel = pt * dpi / 72, origin top-left)
    d = pymupdf.open('pdf', pdf)
    p = d[0]
    z = dpi / 72.0 * (w_mm / PT) / p.rect.width
    pix = p.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
    return pix.tobytes('png')


def ink_mask(png_bytes_or_path, thr=235):
    from PIL import Image
    im = Image.open(io.BytesIO(png_bytes_or_path) if isinstance(png_bytes_or_path, (bytes, bytearray)) else png_bytes_or_path)
    im = im.convert('L')
    return np.asarray(im) < thr


def compare(ref, out, search=6):
    import cv2
    H, W = ref.shape
    o = np.zeros_like(ref)
    hh, ww = min(H, out.shape[0]), min(W, out.shape[1])
    o[:hh, :ww] = out[:hh, :ww]
    out = o
    # coarse shift by phase correlation on 1/4 scale, then local refine
    a = cv2.resize(ref.astype(np.float32), (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    b = cv2.resize(out.astype(np.float32), (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    try:
        (sx, sy), resp = cv2.phaseCorrelate(a, b)
        sx, sy = int(round(-sx * 4)), int(round(-sy * 4))
        if abs(sx) > 60 or abs(sy) > 60:
            sx, sy = 0, 0
    except Exception:
        sx, sy = 0, 0
    k = np.ones((3, 3), np.uint8)
    best = None
    ref_u8 = ref.astype(np.uint8)
    for dy in range(sy - 2, sy + 3):
        for dx in range(sx - 2, sx + 3):
            sh = np.roll(np.roll(out, dy, 0), dx, 1)
            inter = np.count_nonzero(ref & sh)
            union = np.count_nonzero(ref | sh)
            iou = inter / union if union else 1.0
            if best is None or iou > best[0]:
                best = (iou, dx, dy, sh)
    iou, dx, dy, sh = best
    dref = cv2.dilate(ref_u8, k).astype(bool)
    dout = cv2.dilate(sh.astype(np.uint8), k).astype(bool)
    na, nb = np.count_nonzero(ref), np.count_nonzero(sh)
    tpa = np.count_nonzero(ref & dout)
    tpb = np.count_nonzero(sh & dref)
    fn, fp = na - tpa, nb - tpb
    tp = (tpa + tpb) / 2.0
    iou_tol = tp / (tp + fn + fp) if (tp + fn + fp) else 1.0
    return dict(iou_tol1px=round(iou_tol, 4), iou_strict=round(iou, 4),
                recall_1px=round(tpa / na, 4) if na else 1.0, precision_1px=round(tpb / nb, 4) if nb else 1.0,
                ink_ref=int(na), ink_dxf=int(nb), shift_px=(int(dx), int(dy))), sh


def diff_image(ref, sh, path, scale=0.5):
    """RGB diff: black = both, red = PDF only (missing in DXF), blue = DXF only."""
    from PIL import Image
    H, W = ref.shape
    img = np.full((H, W, 3), 255, np.uint8)
    img[ref & sh] = (0, 0, 0)
    img[ref & ~sh] = (230, 0, 0)
    img[~ref & sh] = (0, 90, 255)
    im = Image.fromarray(img)
    if scale != 1:
        im = im.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    im.save(path)
