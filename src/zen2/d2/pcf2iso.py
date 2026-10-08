#!/usr/bin/env python3
"""pcf2iso.py - Isogen PCF (piping component file) -> isometric drawing DXF (+ PNG via ezdxf drawing add-on).

Projection: true orthogonal isometric of the component centre-lines (East -> lower right 30 deg, North -> upper right
30 deg, Up -> vertical), fitted to an A3 landscape sheet (paper mm); symbols have fixed paper sizes:
  pipe line, elbow/bend (exact 3-D circular arc through the end points tangent to the centre-point legs, projected),
  tee/cross/olet branches, concentric/eccentric reducer, flange (face bar), blind flange, gasket, valve (bow-tie + stem),
  instrument, support (triangle + tag), weld dots (shop = filled, field = open), flow arrows, end connections.
Annotations: pipe lengths (from the PCF end points, mm) along each pipe, elevations (EL, m) at fittings/end points,
continuation labels, north arrow, component summary and a title block (pipeline reference, specs, source file).
"""
import math, os, re, sys, json, collections
import ezdxf
from ezdxf.enums import TextEntityAlignment

CODE_VERSION = 'd2-pcf2iso-2026-09-30b'
C30, S30 = math.cos(math.radians(30)), 0.5
SHEET_W, SHEET_H = 420.0, 297.0
AREA = (15.0, 62.0, 330.0, 287.0)   # drawing area x0 y0 x1 y1 (title block + notes below / right)

POINT_KEYS = {'END-POINT': 'ep', 'CENTRE-POINT': 'cp', 'BRANCH1-POINT': 'bp', 'BRANCH2-POINT': 'bp', 'CO-ORDS': 'co'}


def parse_pcf(text):
    head = {'_attrs': {}}
    comps = []
    materials = {}
    cur = None
    section = 'head'
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw[0] not in ' \t':
            toks = raw.split(None, 1)
            key = toks[0].upper()
            val = toks[1].strip() if len(toks) > 1 else ''
            if key == 'MATERIALS':
                section = 'mat'
                cur = None
                continue
            if section == 'mat':
                if key == 'ITEM-CODE':
                    cur = {'code': val}
                    materials[val] = cur
                continue
            if key in ('ISOGEN-FILES',) or key.startswith('UNITS-') or key in ('PIPELINE-REFERENCE', 'PROJECT-IDENTIFIER',
                                                                              'AREA', 'DATE-DMY', 'REVISION', 'BATCH-NAME'):
                head[key] = val
                cur = head['_attrs'] if key == 'PIPELINE-REFERENCE' else None
                section = 'head'
                continue
            cur = {'type': key, 'ep': [], 'cp': None, 'bp': [], 'co': None, 'attrs': {}}
            comps.append(cur)
            section = 'comp'
            continue
        if cur is None:
            continue
        toks = raw.split()
        key = toks[0].upper()
        if section == 'mat':
            cur[key] = ' '.join(toks[1:])
            continue
        if section == 'head':
            cur[key] = ' '.join(toks[1:])
            continue
        if key in POINT_KEYS:
            nums = []
            for t in toks[1:]:
                try:
                    nums.append(float(t))
                except ValueError:
                    break
            if len(nums) >= 3:
                p = (nums[0], nums[1], nums[2], nums[3] if len(nums) > 3 else None,
                     toks[1 + len(nums)] if len(toks) > 1 + len(nums) else '')
                k = POINT_KEYS[key]
                if k == 'ep':
                    cur['ep'].append(p)
                elif k == 'bp':
                    cur['bp'].append(p)
                else:
                    cur[k] = p
        else:
            cur['attrs'][key] = ' '.join(toks[1:])
    return head, comps, materials


class Iso:
    def __init__(self, head, comps, materials, name):
        self.head, self.comps, self.materials, self.name = head, comps, materials, name
        self.stats = collections.Counter()
        pts = []
        for c in comps:
            for p in c['ep'] + c['bp'] + ([c['cp']] if c['cp'] else []) + ([c['co']] if c['co'] else []):
                pts.append(p[:3])
        self.pts = pts
        if pts:
            self.o = tuple(min(p[i] for p in pts) for i in range(3))
        else:
            self.o = (0, 0, 0)
        proj = [self.p0(p) for p in pts] or [(0, 0)]
        xs = [p[0] for p in proj]
        ys = [p[1] for p in proj]
        bw, bh = max(max(xs) - min(xs), 1e-6), max(max(ys) - min(ys), 1e-6)
        aw, ah = AREA[2] - AREA[0], AREA[3] - AREA[1]
        self.s = min(aw / bw, ah / bh) * 0.92
        self.cx = (AREA[0] + AREA[2]) / 2 - self.s * (min(xs) + max(xs)) / 2
        self.cy = (AREA[1] + AREA[3]) / 2 - self.s * (min(ys) + max(ys)) / 2

    def p0(self, p):
        e, n, u = p[0] - self.o[0], p[1] - self.o[1], p[2] - self.o[2]
        return ((e + n) * C30, (n - e) * S30 + u)

    def P(self, p):
        x, y = self.p0(p)
        return (self.cx + self.s * x, self.cy + self.s * y)

    # ------------------------------------------------------------------ drawing helpers
    def setup(self):
        doc = ezdxf.new('R2018', setup=True, units=4)
        doc.header['$MEASUREMENT'] = 1
        doc.header['$LWDISPLAY'] = 1
        for name, col, lw in (('BORDER', 7, 50), ('TITLE', 7, 25), ('PIPE', 7, 50), ('FITTING', 7, 35), ('FLANGE', 7, 50),
                              ('VALVE', 7, 35), ('INSTRUMENT', 7, 25), ('SUPPORT', 3, 25), ('WELD', 1, 25),
                              ('DIMENSION', 5, 18), ('ELEVATION', 6, 18), ('TEXT', 7, 18), ('FLOW', 4, 18),
                              ('CONNECTION', 30, 25), ('NORTH', 7, 25)):
            doc.layers.add(name, color=col, lineweight=lw)
        if 'ISO' not in doc.styles:
            doc.styles.add('ISO', font='arial.ttf')
        self.doc = doc
        self.msp = doc.modelspace()
        return doc

    def line(self, a, b, layer):
        self.msp.add_line(a, b, dxfattribs={'layer': layer})

    def text(self, s, at, h=2.0, rot=0.0, layer='TEXT', align='MIDDLE_CENTER'):
        if rot > 90 or rot < -90:
            rot += 180 if rot < 0 else -180
        t = self.msp.add_text(s, height=h, rotation=rot, dxfattribs={'layer': layer, 'style': 'ISO'})
        t.set_placement(at, align=TextEntityAlignment[align])

    @staticmethod
    def dirn(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        return ((dx / L, dy / L), L) if L > 1e-9 else ((1.0, 0.0), 0.0)

    def tick(self, at, d, half, layer):
        n = (-d[1], d[0])
        self.line((at[0] - n[0] * half, at[1] - n[1] * half), (at[0] + n[0] * half, at[1] + n[1] * half), layer)

    # ------------------------------------------------------------------ components
    def draw(self):
        doc = self.setup()
        msp = self.msp
        # border + frame
        msp.add_lwpolyline([(5, 5), (SHEET_W - 5, 5), (SHEET_W - 5, SHEET_H - 5), (5, SHEET_H - 5)], close=True,
                           dxfattribs={'layer': 'BORDER'})
        els = []
        for c in self.comps:
            t = c['type']
            ep = [self.P(p) for p in c['ep']]
            try:
                if t == 'PIPE' and len(ep) >= 2:
                    self.line(ep[0], ep[1], 'PIPE')
                    d, L = self.dirn(ep[0], ep[1])
                    length = math.dist(c['ep'][0][:3], c['ep'][1][:3])
                    if L > 6:
                        mid = ((ep[0][0] + ep[1][0]) / 2 - d[1] * 2.2, (ep[0][1] + ep[1][1]) / 2 + d[0] * 2.2)
                        self.text('%d' % round(length), mid, 1.8, math.degrees(math.atan2(d[1], d[0])), 'DIMENSION')
                    self.stats['pipe'] += 1
                    self.stats['pipe_length_mm'] += length
                elif t in ('ELBOW', 'BEND', 'PIPE-BEND') and len(ep) >= 2:
                    self.elbow(c)
                    if c['cp']:
                        els.append(c['cp'])
                elif t in ('TEE', 'CROSS', 'TEE-STUB', 'TEE-SET-ON', 'OLET', 'Y-PIECE', 'LATERAL'):
                    cp = self.P(c['cp'] or c['co'] or (c['ep'][0] if c['ep'] else None))
                    for e in ep:
                        self.line(e, cp, 'FITTING')
                    for b in c['bp']:
                        self.line(cp, self.P(b), 'FITTING')
                    if t == 'OLET' or not ep:
                        msp.add_circle(cp, 0.9, dxfattribs={'layer': 'FITTING'})
                    if c['cp'] or c['co']:
                        els.append(c['cp'] or c['co'])
                    self.stats[t.lower()] += 1
                elif t.startswith('REDUCER') and len(ep) >= 2:
                    self.reducer(ep, c, ecc=('ECC' in t))
                elif t.startswith('FLANGE') and len(ep) >= 1:
                    self.flange(ep, c, blind=('BLIND' in t))
                elif t in ('GASKET',) and ep:
                    d, L = self.dirn(ep[0], ep[-1]) if len(ep) > 1 else ((1, 0), 0)
                    self.tick(ep[0], d, 1.6, 'FLANGE')
                    self.stats['gasket'] += 1
                elif t.startswith('VALVE') or t in ('INSTRUMENT', 'INSTRUMENT-ANGLE', 'INSTRUMENT-3WAY', 'FILTER', 'TRAP',
                                                    'STRAINER'):
                    self.valve(c, ep, instrument=not t.startswith('VALVE'))
                elif t == 'WELD':
                    at = ep[0] if ep else (self.P(c['co']) if c['co'] else None)
                    if at:
                        sk = (c['attrs'].get('SKEY') or '').upper()
                        field = sk.startswith('WF') or sk.startswith('FW') or 'FIELD' in (c['attrs'].get('WELD-TYPE', '')).upper()
                        if field:
                            msp.add_circle(at, 0.8, dxfattribs={'layer': 'WELD'})
                        else:
                            h = msp.add_hatch(color=1, dxfattribs={'layer': 'WELD'})
                            h.paths.add_edge_path().add_arc(at, 0.55, 0, 360)
                        self.stats['weld'] += 1
                elif t == 'SUPPORT' and c['co']:
                    self.support(c)
                elif t == 'FLOW-ARROW' and c['co']:
                    self.stats['flow_arrow'] += 1
                elif t.startswith('END-CONNECTION') and c['co']:
                    at = self.P(c['co'])
                    msp.add_circle(at, 1.2, dxfattribs={'layer': 'CONNECTION'})
                    ref = c['attrs'].get('PIPELINE-REFERENCE') or c['attrs'].get('CONNECTION-REFERENCE') or \
                        ('EQUIPMENT' if 'EQUIPMENT' in t else '')
                    lab = ('CONT. ' + ref) if ref else t.replace('END-CONNECTION-', 'END ')
                    self.text(lab[:40], (at[0] + 2.5, at[1] + 2.5), 1.8, 0, 'CONNECTION', 'LEFT')
                    x, y, z = c['co'][:3]
                    self.text('E %.0f N %.0f EL %+.3f' % (x, y, z / 1000.0), (at[0] + 2.5, at[1] - 0.5), 1.5, 0,
                              'ELEVATION', 'LEFT')
                    self.stats['end_connection'] += 1
                elif t == 'TAP-CONNECTION' and c['co']:
                    msp.add_circle(self.P(c['co']), 0.8, dxfattribs={'layer': 'CONNECTION'})
                elif len(ep) >= 2:   # generic in-line component (coupling, union, cap, misc)
                    self.line(ep[0], ep[1], 'FITTING')
                    d, L = self.dirn(ep[0], ep[1])
                    mid = ((ep[0][0] + ep[1][0]) / 2, (ep[0][1] + ep[1][1]) / 2)
                    n = (-d[1], d[0])
                    q = [(mid[0] + a * d[0] * 1.2 + b * n[0] * 1.0, mid[1] + a * d[1] * 1.2 + b * n[1] * 1.0)
                         for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                    msp.add_lwpolyline(q, close=True, dxfattribs={'layer': 'FITTING'})
                    self.stats['other_' + t.lower()] += 1
                elif t not in ('BOLT',):
                    self.stats['skipped_' + t.lower()] += 1
            except Exception as e:
                self.stats['errors'] += 1
        # elevations at fittings (deduplicated per elevation band)
        seen = set()
        placed = []
        for p in els:
            k = (round(p[2] / 50), round(p[0] / 500), round(p[1] / 500))
            if k in seen:
                continue
            seen.add(k)
            at = self.P(p)
            if any(math.dist(at, q) < 7.0 for q in placed):   # keep labels legible in dense areas
                continue
            placed.append(at)
            self.text('EL %+.3f' % (p[2] / 1000.0), (at[0] + 1.5, at[1] + 1.8), 1.6, 0, 'ELEVATION', 'LEFT')
        self.north()
        self.title_block()
        doc.header.custom_vars.append('D2_CONVERTER', CODE_VERSION)
        return doc

    def elbow(self, c):
        a, b = c['ep'][0][:3], c['ep'][1][:3]
        cp = c['cp'][:3] if c['cp'] else None
        pts = []
        if cp:
            u = [a[i] - cp[i] for i in range(3)]
            v = [b[i] - cp[i] for i in range(3)]
            lu, lv = math.sqrt(sum(x * x for x in u)), math.sqrt(sum(x * x for x in v))
            if lu > 1e-6 and lv > 1e-6:
                cosg = max(-1.0, min(1.0, sum(u[i] * v[i] for i in range(3)) / (lu * lv)))
                gamma = math.acos(cosg)            # angle between legs at the tangent intersection
                phi = math.pi - gamma              # turning (arc) angle
                w = math.cos(phi / 2)
                for k in range(17):
                    t = k / 16
                    b0, b1, b2 = (1 - t) ** 2, 2 * t * (1 - t) * w, t * t
                    den = b0 + b1 + b2
                    pts.append(tuple((b0 * a[i] + b1 * cp[i] + b2 * b[i]) / den for i in range(3)))
        if not pts:
            pts = [a, b]
        self.msp.add_lwpolyline([self.P(p) for p in pts], dxfattribs={'layer': 'FITTING'})
        self.stats['elbow'] += 1

    def reducer(self, ep, c, ecc):
        d, L = self.dirn(ep[0], ep[1])
        n = (-d[1], d[0])
        b1 = c['ep'][0][3] or 1
        b2 = c['ep'][1][3] or 1
        w1 = 1.6
        w2 = max(0.5, 1.6 * min(b2, b1 * 4) / b1) if b1 else 1.0
        L = max(L, 3.0)
        a0 = ep[0]
        a1 = (a0[0] + d[0] * L, a0[1] + d[1] * L)
        if ecc:
            q = [(a0[0] - n[0] * w1, a0[1] - n[1] * w1), (a0[0] + n[0] * w1, a0[1] + n[1] * w1),
                 (a1[0] + n[0] * (2 * w2 - w1), a1[1] + n[1] * (2 * w2 - w1)), (a1[0] - n[0] * w1, a1[1] - n[1] * w1)]
        else:
            q = [(a0[0] - n[0] * w1, a0[1] - n[1] * w1), (a0[0] + n[0] * w1, a0[1] + n[1] * w1),
                 (a1[0] + n[0] * w2, a1[1] + n[1] * w2), (a1[0] - n[0] * w2, a1[1] - n[1] * w2)]
        self.msp.add_lwpolyline(q, close=True, dxfattribs={'layer': 'FITTING'})
        self.stats['reducer'] += 1

    def flange(self, ep, c, blind):
        if len(ep) >= 2:
            self.line(ep[0], ep[1], 'FLANGE')
            d, L = self.dirn(ep[0], ep[1])
            face = 0
            for i, p in enumerate(c['ep']):
                if p[4] and p[4].upper() not in ('BW', 'SW', 'PL'):
                    face = i
            at = ep[face]
        else:
            d, at = (1.0, 0.0), ep[0]
        self.tick(at, d, 2.2, 'FLANGE')
        if blind:
            self.tick((at[0] + d[0] * 0.5, at[1] + d[1] * 0.5), d, 2.2, 'FLANGE')
        self.stats['flange'] += 1

    def valve(self, c, ep, instrument=False):
        if len(ep) >= 2:
            a, b = ep[0], ep[-1]
            mid = self.P(c['cp']) if c['cp'] else ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            d, L = self.dirn(a, b)
            self.line(a, b, 'VALVE')
        elif ep:
            mid, d = ep[0], (1.0, 0.0)
        else:
            return
        n = (-d[1], d[0])
        if instrument:
            self.msp.add_circle(mid, 1.8, dxfattribs={'layer': 'INSTRUMENT'})
            self.stats['instrument'] += 1
            return
        s = 2.0
        tri1 = [mid, (mid[0] - d[0] * s + n[0] * s * .8, mid[1] - d[1] * s + n[1] * s * .8),
                (mid[0] - d[0] * s - n[0] * s * .8, mid[1] - d[1] * s - n[1] * s * .8)]
        tri2 = [mid, (mid[0] + d[0] * s + n[0] * s * .8, mid[1] + d[1] * s + n[1] * s * .8),
                (mid[0] + d[0] * s - n[0] * s * .8, mid[1] + d[1] * s - n[1] * s * .8)]
        self.msp.add_lwpolyline(tri1, close=True, dxfattribs={'layer': 'VALVE'})
        self.msp.add_lwpolyline(tri2, close=True, dxfattribs={'layer': 'VALVE'})
        self.line(mid, (mid[0], mid[1] + 3.0), 'VALVE')
        self.line((mid[0] - 1.2, mid[1] + 3.0), (mid[0] + 1.2, mid[1] + 3.0), 'VALVE')
        sk = c['attrs'].get('SKEY', '')
        if sk:
            self.text(sk, (mid[0] + 2.5, mid[1] + 3.2), 1.4, 0, 'TEXT', 'LEFT')
        self.stats['valve'] += 1

    def support(self, c):
        at = self.P(c['co'])
        dirv = (c['attrs'].get('SUPPORT-DIRECTION') or 'DOWN').upper()
        v = {'DOWN': (0, -1), 'UP': (0, 1), 'EAST': (C30, -S30), 'WEST': (-C30, S30), 'NORTH': (C30, S30),
             'SOUTH': (-C30, -S30)}.get(dirv, (0, -1))
        n = (-v[1], v[0])
        tip = at
        base = (at[0] + v[0] * 2.4, at[1] + v[1] * 2.4)
        self.msp.add_lwpolyline([tip, (base[0] + n[0] * 1.4, base[1] + n[1] * 1.4), (base[0] - n[0] * 1.4, base[1] - n[1] * 1.4)],
                                close=True, dxfattribs={'layer': 'SUPPORT'})
        name = c['attrs'].get('NAME') or c['attrs'].get('SKEY') or 'S'
        self.text(name[:24], (base[0] + 1.8, base[1] - 0.8), 1.4, 0, 'SUPPORT', 'LEFT')
        self.stats['support'] += 1

    def north(self):
        x, y = 395.0, 270.0
        e = (x + C30 * 12, y + S30 * 12)
        self.line((x, y), e, 'NORTH')
        self.line(e, (e[0] - 2.6, e[1] - 0.2), 'NORTH')
        self.line(e, (e[0] - 1.1, e[1] - 2.4), 'NORTH')
        self.text('N', (e[0] + 2, e[1] + 1.5), 3.0, 0, 'NORTH')

    def title_block(self):
        m = self.msp
        x0, y0, x1, y1 = 240.0, 5.0, SHEET_W - 5, 55.0
        m.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={'layer': 'TITLE'})
        for yy in (45.0, 35.0, 25.0, 15.0):
            self.line((x0, yy), (x1, yy), 'TITLE')
        a = self.head.get('_attrs', {})
        ref = self.head.get('PIPELINE-REFERENCE', '')
        rows = [('PIPELINE', ref), ('PIPING SPEC', a.get('PIPING-SPEC', '')),
                ('INSULATION', a.get('INSULATION-SPEC', '')[:48]),
                ('SOURCE', 'Smart 3D PCF: %s' % self.name[:52]),
                ('DRAWING', 'ISOMETRIC (true-scale projection fitted to sheet, 1 : %d)' % max(1, round(1 / self.s)))]
        for i, (k, v) in enumerate(rows):
            yy = y1 - 5 - 10 * i
            self.text(k, (x0 + 2, yy), 2.2 if i == 0 else 1.8, 0, 'TITLE', 'MIDDLE_LEFT')
            self.text(str(v)[:60], (x0 + 30, yy), 2.6 if i == 0 else 1.8, 0, 'TITLE', 'MIDDLE_LEFT')
        # component summary
        sx, sy = 340.0, 250.0
        self.text('COMPONENTS', (sx, sy), 2.2, 0, 'TEXT', 'LEFT')
        keys = [k for k in ('pipe', 'elbow', 'tee', 'olet', 'reducer', 'flange', 'gasket', 'valve', 'instrument',
                            'support', 'weld', 'end_connection') if self.stats.get(k)]
        for i, k in enumerate(keys):
            self.text('%-14s %5d' % (k.upper().replace('_', ' '), self.stats[k]), (sx, sy - 4 - 3.2 * i), 1.8, 0, 'TEXT', 'LEFT')
        self.text('PIPE LENGTH %.1f m' % (self.stats.get('pipe_length_mm', 0) / 1000.0),
                  (sx, sy - 4 - 3.2 * len(keys) - 1), 1.8, 0, 'TEXT', 'LEFT')
        u = self.head.get('UNITS-CO-ORDS', 'MM')
        self.text('DIMENSIONS IN %s; EL IN m' % u, (sx, 70.0), 1.6, 0, 'TEXT', 'LEFT')


def render_png(dxf_path, png_path, dpi=150):
    from ezdxf.addons.drawing import RenderContext, Frontend, layout
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy, LineweightPolicy
    from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
    from ezdxf.math import BoundingBox2d
    doc = ezdxf.readfile(dxf_path)
    be = PyMuPdfBackend()
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR,
                        lineweight_policy=LineweightPolicy.ABSOLUTE, lineweight_scaling=1.0, min_lineweight=2.0)
    Frontend(RenderContext(doc), be, config=cfg).draw_layout(doc.modelspace(), finalize=True)
    pg = layout.Page(SHEET_W, SHEET_H, layout.Units.mm, margins=layout.Margins.all(0))
    png = be.get_pixmap_bytes(pg, fmt='png', settings=layout.Settings(fit_page=False, scale=1.0), dpi=dpi,
                              render_box=BoundingBox2d([(0, 0), (SHEET_W, SHEET_H)]))
    with open(png_path, 'wb') as f:
        f.write(png)


def convert(pcf_text, name, dxf_path, png_path=None):
    head, comps, mats = parse_pcf(pcf_text)
    iso = Iso(head, comps, mats, name)
    doc = iso.draw()
    os.makedirs(os.path.dirname(dxf_path) or '.', exist_ok=True)
    doc.saveas(dxf_path)
    if png_path:
        render_png(dxf_path, png_path)
    return {'pipeline_reference': head.get('PIPELINE-REFERENCE'), 'components': len(comps),
            'component_types': dict(collections.Counter(c['type'] for c in comps)), 'stats': dict(iso.stats),
            'scale_1_to': round(1 / iso.s) if iso.s else None}


if __name__ == '__main__':
    txt = open(sys.argv[1], encoding='latin-1').read()
    print(json.dumps(convert(txt, os.path.basename(sys.argv[1]), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None),
                     default=str)[:1500])
