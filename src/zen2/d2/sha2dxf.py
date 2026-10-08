#!/usr/bin/env python3
"""sha2dxf.py - EXPERIMENTAL partial decoder: Smart 3D / SmartSketch .sha sheet graphics -> DXF (mm, sheet origin
lower-left, layers = Smart 3D layer names).

Format findings (reverse-engineered on this data set; checked against the Smart 3D PDF plots of the same sheets):
  * 'Sheet<N>', 'PSMcluster0', 'StyleCluster', 'Unclustered Dynamic Attributes' streams: magic 44 f5 90 6c, u32 count,
    then records [u16 type][u32 length][payload]; bit 0x8000 of the type is a flag (same layout).
  * payload header (18 bytes): u32 object id, u32 owner id, u32 layer id, u16 flags, u32 style index.
  * layers: PSMcluster0 type 129 records (id -> UTF-16 name, e.g. STRUCT, LIGHT, Default).
  * styles: StyleCluster records keyed by u16 index @14: type 46/48 line style (width m @34 / @42),
    type 45 text style (font-record index u16 @40), type 44 font record (height m @42, UTF-16 face name at the end).
  * type 61 = placed sub-document (drawing view, border sheet, key plan, picture): u32 JSite id @156, 7 doubles @164:
    a b c d tx ty s (child p -> parent s*[a c; b d]*p + [tx ty]); JSite<id> storage holds its own Sheet streams.
  * geometry (doubles in metres; drawing views in model metres): 24 line (x1 y1 x2 y2 @18, 50-byte form),
    89 circle (cx cy r), 97/99 circular arc (cx cy r a0 a1, radians), 126 elliptical arc (p0 p1 cx cy mx my ratio),
    77 text: runs [u16 len + UTF-16], then x y cos sin (anchor) and a justification byte
    (high nibble 0/1/2 = left/centre/right, low nibble 1 = top, 5 = middle, 0 = baseline);
    XML bodies <intstgxml stream=S select=XPATH/> are title-block fields resolved from TaggedTxtData.
NOT decoded (documented in the status file): fill styles of 132 polygons, 19 paths, B-splines (93), symbol/linetype
geometry (123 groups, 24 66-byte form), dimensions/labels (206, 250, 277, 280), colours, pictures (static DIB JSites).
"""
import collections, math, re, struct, sys
import xml.etree.ElementTree as ET
import olefile
import ezdxf

CODE_VERSION = 'd2-sha2dxf-2026-09-30-exp4'
LW = [0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211]
PRINTABLE = re.compile(r'^[\x20-\x7e -ÿ⌀∅]+$')


def recs(b):
    k = 8
    out = []
    while k + 6 <= len(b):
        t, ln = struct.unpack_from('<HI', b, k)
        if ln > len(b) - k - 6:
            break
        out.append((t, b[k + 6:k + 6 + ln]))
        k += 6 + ln
    return out


def lw_of(w_mm):
    return min(LW, key=lambda v: abs(v / 100.0 - w_mm))


class Xf:
    def __init__(self, a=1, b=0, c=0, d=1, tx=0, ty=0, s=1):
        self.m = (a * s, b * s, c * s, d * s, tx, ty)

    def compose(self, child):
        A, B, C, D, E, F = self.m
        a, b, c, d, e, f = child.m
        x = Xf()
        x.m = (A * a + C * b, B * a + D * b, A * c + C * d, B * c + D * d, A * e + C * f + E, B * e + D * f + F)
        return x

    def pt(self, x, y):
        a, b, c, d, e, f = self.m
        return (a * x + c * y + e, b * x + d * y + f)

    def vec(self, x, y):
        a, b, c, d, e, f = self.m
        return (a * x + c * y, b * x + d * y)

    @property
    def scale(self):
        a, b, c, d, e, f = self.m
        return math.sqrt(abs(a * d - b * c))

    @property
    def rot(self):
        return math.atan2(self.m[1], self.m[0])


def find_str(p, start=18):
    best = None
    for k in range(start, len(p) - 3):
        L = struct.unpack_from('<H', p, k)[0]
        if 1 <= L <= 4000 and k + 2 + 2 * L <= len(p):
            try:
                s = p[k + 2:k + 2 + 2 * L].decode('utf-16le')
            except UnicodeDecodeError:
                continue
            if PRINTABLE.match(s) and (best is None or L > best[1]):
                best = (k, L, s)
    return best


def find_pos(p, start):
    for k in range(start, len(p) - 31):
        x, y, c, s = struct.unpack_from('<4d', p, k)
        if -0.05 <= x <= 1.3 and -0.05 <= y <= 1.0 and abs(c * c + s * s - 1) < 1e-6 and (abs(x) > 1e-5 or abs(y) > 1e-5):
            return k, (x, y, c, s)
    return None


class Decoder:
    def __init__(self, path):
        self.o = olefile.OleFileIO(path)
        self.storages = set('/'.join(s) for s in self.o.listdir(streams=False, storages=True))
        self.streams = ['/'.join(s) for s in self.o.listdir(streams=True, storages=False)]
        self.stats = collections.Counter()
        self.unknown = collections.Counter()
        self.ents = []
        self.tagged = self._tagged()
        self._layers = {}
        self._styles = {}

    def _tagged(self):
        out = {}
        for n in self.streams:
            if n.startswith('TaggedTxtData/'):
                try:
                    out[n.split('/')[-1]] = ET.fromstring(self.o.openstream(n).read().decode('utf-8', 'replace').strip())
                except Exception:
                    pass
        return out

    def field(self, stream, select):
        r = self.tagged.get(stream)
        if r is None:
            return ''
        path = select.strip('/').split('/')
        if path and path[0] == r.tag:
            path = path[1:]
        attr = None
        if path and path[-1].startswith('@'):
            attr = path.pop()[1:]
        try:
            e = r.find('./' + '/'.join(path)) if path else r
        except Exception:
            return ''
        if e is None:
            return ''
        return (e.get(attr) or '').strip() if attr else (e.text or '').strip()

    def layers(self, storage):
        if storage not in self._layers:
            d = {}
            n = (storage + '/' if storage else '') + 'PSMcluster0'
            if n in self.streams:
                for t, p in recs(self.o.openstream(n).read()):
                    if t == 129 and len(p) >= 26:
                        m = re.search(rb'((?:[\x20-\x7e]\x00){1,64})', p[18:])
                        if m:
                            d[struct.unpack_from('<I', p, 0)[0]] = m.group(1).decode('utf-16le')
            self._layers[storage] = d
        return self._layers[storage]

    def styles(self, storage):
        if storage not in self._styles:
            d = {}
            n = (storage + '/' if storage else '') + 'StyleCluster'
            if n in self.streams:
                for t, p in recs(self.o.openstream(n).read()):
                    if len(p) >= 16:
                        d[struct.unpack_from('<H', p, 14)[0]] = (t, p)
            self._styles[storage] = d
        return self._styles[storage]

    def line_width(self, storage, sid):
        st = self.styles(storage).get(sid)
        if not st:
            return None
        t, p = st
        try:
            if t == 46 and len(p) >= 42:
                return struct.unpack_from('<d', p, 34)[0]
            if t == 48 and len(p) >= 50:
                return struct.unpack_from('<d', p, 42)[0]
        except struct.error:
            pass
        return None

    def font(self, storage, idx, depth=0):
        """style/font index -> (face, height m)"""
        st = self.styles(storage).get(idx)
        if not st or depth > 3:
            return None
        t, p = st
        if t == 44 and len(p) >= 50:
            h = struct.unpack_from('<d', p, 42)[0]
            m = re.findall(rb'((?:[\x20-\x7e]\x00){2,40})', p[50:])
            return (m[-1].decode('utf-16le') if m else 'Arial', h)
        if t == 45 and len(p) >= 42:
            return self.font(storage, struct.unpack_from('<H', p, 40)[0], depth + 1)
        return None

    def sheet_streams(self, storage):
        out = []
        for n in self.streams:
            parts = n.split('/')
            if '/'.join(parts[:-1]) == storage and parts[-1].startswith('Sheet') and self.o.get_size(n) > 8:
                out.append(n)
        return out

    def run(self, storage='', xf=None, depth=0):
        xf = xf or Xf()
        if depth > 8:
            return
        for n in self.sheet_streams(storage):
            b = self.o.openstream(n).read()
            if not b.startswith(b'\x44\xf5\x90\x6c'):
                continue
            for t, p in recs(b):
                try:
                    self.record(storage, xf, depth, t, p)
                except (struct.error, ValueError, ZeroDivisionError):
                    self.stats['record_errors'] += 1

    def attrs(self, storage, p):
        lid = struct.unpack_from('<I', p, 8)[0]
        sid = struct.unpack_from('<I', p, 14)[0]
        name = self.layers(storage).get(lid) or 'L%d' % lid
        name = re.sub(r'[<>/\\":;?*|=`]', '_', name)[:60] or 'Default'
        return name, sid

    def record(self, storage, xf, depth, t, p):
        base = t & 0x7fff
        L = len(p)
        if base == 61 and L >= 220:
            jid = struct.unpack_from('<I', p, 156)[0]
            a, b_, c, d, tx, ty, s = struct.unpack_from('<7d', p, 164)
            child = (storage + '/' if storage else '') + 'JSite%d' % jid
            if child in self.storages:
                self.stats['sub_documents'] += 1
                self.run(child, xf.compose(Xf(a, b_, c, d, tx, ty, s)), depth + 1)
            return
        if L < 18:
            return
        lay, sid = self.attrs(storage, p)
        if base in (24, 89, 97, 99, 126):
            w = self.line_width(storage, sid)
            w_mm = w * 1000 if w is not None and 0 <= w < 0.01 else None
        if base == 24 and L == 50:
            x1, y1, x2, y2 = struct.unpack_from('<4d', p, 18)
            self.ents.append(('line', (xf.pt(x1, y1), xf.pt(x2, y2)), lay, w_mm))
            self.stats['line'] += 1
        elif base == 89 and L == 43:
            cx, cy, r = struct.unpack_from('<3d', p, 18)
            self.ents.append(('circle', (xf.pt(cx, cy), r * xf.scale), lay, w_mm))
            self.stats['circle'] += 1
        elif base in (97, 99) and L == 59:
            cx, cy, r, a0, a1 = struct.unpack_from('<5d', p, 18)
            self.ents.append(('arc', (xf.pt(cx, cy), r * xf.scale, a0 + xf.rot, a1 + xf.rot), lay, w_mm))
            self.stats['arc'] += 1
        elif base == 126 and L == 75:
            p0, p1, cx, cy, mx, my, ratio = struct.unpack_from('<7d', p, 18)
            self.ents.append(('ellipse', (xf.pt(cx, cy), xf.vec(mx, my), ratio, p0, p1), lay, w_mm))
            self.stats['ellipse'] += 1
        elif base == 132 and L >= 24:
            n = struct.unpack_from('<I', p, 18)[0]
            if 2 <= n <= 10000 and 24 + 16 * n <= L:
                pts = [xf.pt(*struct.unpack_from('<2d', p, 24 + 16 * i)) for i in range(n)]
                self.ents.append(('poly', pts, lay, None))
                self.stats['polygon'] += 1
            else:
                self.unknown[base] += 1
        elif base == 77:
            self.text(storage, xf, p, lay, sid)
        else:
            self.unknown[base] += 1

    def text(self, storage, xf, p, lay, sid):
        r = find_str(p)
        if not r:
            self.stats['text_nostring'] += 1
            return
        k, L, s = r
        q = find_pos(p, k + 2 + 2 * L)
        if not q:
            self.stats['text_noposition'] += 1
            return
        off, (x, y, c, sn) = q
        just = p[off + 32] if off + 32 < len(p) else 1
        m = re.search(r'<intstgxml stream="([^"]+)" select="([^"]+)"', s)
        if m:
            s = self.field(m.group(1), m.group(2))
            self.stats['text_field'] += 1
            if not s:
                return
        elif s.startswith('<?xml'):
            s = re.sub(r'<[^>]+>', '', s).strip()
            if not s:
                return
        # font: run-level font index (u32 just before the string) or record style
        fnt = None
        if k >= 22:
            fi = struct.unpack_from('<I', p, k - 4)[0]
            if 0 < fi < 65536:
                fnt = self.font(storage, fi)
        fnt = fnt or self.font(storage, sid) or ('Arial', 0.0025)
        face, h = fnt
        ang = math.atan2(sn, c) + xf.rot
        self.ents.append(('text', (xf.pt(x, y), s, h * xf.scale, math.degrees(ang), just, face), lay, None))
        self.stats['text'] += 1

    def texts(self):
        out = []
        for kind, d, lay, w in self.ents:
            if kind == 'text':
                (x, y), txt, h, ang, just, face = d
                out.append({'text': txt, 'x_mm': round(x * 1000, 3), 'y_mm': round(y * 1000, 3), 'rotation_deg': round(ang, 3),
                            'anchor': {0: 'left', 1: 'centre', 2: 'right'}.get(just >> 4, str(just >> 4)) + '-' +
                                      {1: 'top', 5: 'middle', 0: 'baseline'}.get(just & 15, str(just & 15)),
                            'layer': lay, 'font_record': face})
        return out

    def render_png(self, box, dpi=100, max_px=5000):
        """fast raster of the decoded geometry (same primitives as the DXF) with PyMuPDF; box = (x0, y0, W, H) mm."""
        import pymupdf
        x0, y0, W, H = box
        dpi = min(dpi, max_px / (max(W, H) / 25.4))
        k = 72 / 25.4
        doc = pymupdf.open()
        pg = doc.new_page(width=W * k, height=H * k)
        sh = pg.new_shape()

        def T(x, y):
            return pymupdf.Point((x * 1000 - x0) * k, (y0 + H - y * 1000) * k)

        groups = collections.defaultdict(list)
        for kind, d, lay, w_mm in self.ents:
            if kind != 'text':
                groups[max(w_mm or 0.25, 0.18)].append((kind, d))
        for w_mm, items in groups.items():
            for kind, d in items:
                try:
                    if kind == 'line':
                        sh.draw_line(T(*d[0]), T(*d[1]))
                    elif kind == 'poly':
                        sh.draw_polyline([T(*q) for q in d])
                    elif kind == 'circle':
                        (cx, cy), r = d
                        if r > 0:
                            sh.draw_circle(T(cx, cy), r * 1000 * k)
                    elif kind == 'arc':
                        (cx, cy), r, a0, a1 = d
                        sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
                        n = max(4, int(sweep / 0.1))
                        sh.draw_polyline([T(cx + r * math.cos(a0 + sweep * i / n), cy + r * math.sin(a0 + sweep * i / n))
                                          for i in range(n + 1)])
                    elif kind == 'ellipse':
                        (cx, cy), (mx, my), ratio, p0, p1 = d
                        sweep = (p1 - p0) % (2 * math.pi) or 2 * math.pi
                        n = max(8, int(sweep / 0.1))
                        mnx, mny = -my * ratio, mx * ratio
                        sh.draw_polyline([T(cx + mx * math.cos(t) + mnx * math.sin(t), cy + my * math.cos(t) + mny * math.sin(t))
                                          for t in (p0 + sweep * i / n for i in range(n + 1))])
                except Exception:
                    pass
            sh.finish(width=w_mm * k, color=(0, 0, 0), closePath=False)
        sh.commit()
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False)
        return pix.tobytes('png'), round(dpi, 2)

    def to_dxf(self, include_text=False):
        doc = ezdxf.new('R2018', setup=False, units=4)
        doc.header['$MEASUREMENT'] = 1
        doc.header['$LWDISPLAY'] = 1
        msp = doc.modelspace()
        K = 1000.0
        styles = {}
        for kind, d, lay, w_mm in self.ents:
            if kind == 'text' and not include_text:
                continue
            if lay not in doc.layers:
                doc.layers.add(lay)
            at = {'layer': lay}
            if w_mm is not None:
                at['lineweight'] = lw_of(w_mm)
            if kind == 'line':
                (x1, y1), (x2, y2) = d
                msp.add_line((x1 * K, y1 * K), (x2 * K, y2 * K), dxfattribs=at)
            elif kind == 'poly':
                pts = [(x * K, y * K) for x, y in d]
                closed = len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-6
                msp.add_lwpolyline(pts[:-1] if closed else pts, close=closed, dxfattribs=at)
            elif kind == 'circle':
                (cx, cy), r = d
                if r > 0:
                    msp.add_circle((cx * K, cy * K), r * K, dxfattribs=at)
            elif kind == 'arc':
                (cx, cy), r, a0, a1 = d
                if r > 0:
                    msp.add_arc((cx * K, cy * K), r * K, math.degrees(a0), math.degrees(a1), dxfattribs=at)
            elif kind == 'ellipse':
                (cx, cy), (mx, my), ratio, p0, p1 = d
                if (mx or my) and 0 < abs(ratio) <= 1:
                    try:
                        msp.add_ellipse((cx * K, cy * K), (mx * K, my * K, 0), abs(ratio), p0, p1, dxfattribs=at)
                    except Exception:
                        self.stats['ellipse_bad'] += 1
            elif kind == 'text' and include_text:
                (x, y), s, h, ang, just, face = d
                sname = re.sub(r'[^A-Za-z0-9_]', '_', face.upper())[:30] or 'STANDARD'
                if sname not in styles:
                    fl = face.lower()
                    ff = ('%s.shx' % fl) if fl.startswith('roman') else ('arialbd.ttf' if 'bold' in fl else 'arial.ttf')
                    if sname not in doc.styles:
                        doc.styles.add(sname, font=ff)
                    styles[sname] = 1
                hj = (just >> 4) & 0xF
                vj = just & 0xF
                # SmartSketch anchor: h 0/1/2 = left/centre/right; v 1 = top, 5 = middle, 0 = baseline
                align = {(0, 1): 'TOP_LEFT', (1, 1): 'TOP_CENTER', (2, 1): 'TOP_RIGHT',
                         (0, 5): 'MIDDLE_LEFT', (1, 5): 'MIDDLE_CENTER', (2, 5): 'MIDDLE_RIGHT',
                         (0, 0): 'LEFT', (1, 0): 'CENTER', (2, 0): 'RIGHT'}.get((hj, vj), 'TOP_LEFT')
                for i, line in enumerate(s.replace('\r\n', '\n').split('\n')[:40]):
                    if not line.strip():
                        continue
                    dy = i * h * 1.5
                    a = math.radians(ang)
                    px, py = x * K + math.sin(a) * dy * K, y * K - math.cos(a) * dy * K
                    t = msp.add_text(line, height=max(h * K * 0.72, 0.1), rotation=ang,
                                     dxfattribs={'layer': lay, 'style': sname})
                    t.set_placement((px, py), align=ezdxf.enums.TextEntityAlignment[align])
        doc.header.custom_vars.append('D2_CONVERTER', CODE_VERSION)
        return doc


if __name__ == '__main__':
    dec = Decoder(sys.argv[1])
    dec.run()
    print(dict(dec.stats))
    print('unknown', dec.unknown.most_common(20))
    dec.to_dxf().saveas(sys.argv[2])
