#!/usr/bin/env python3
"""Reader for the delivered faceted STEP (ifc2step6 output: AP214, FACETED_BREP / BREP_WITH_VOIDS of POLY_LOOP faces,
optional MAPPED_ITEM instancing). Returns, per PRODUCT id (= IFC GlobalId), the solids as lists of polygon faces in
model millimetres, and mass properties computed exactly for those polyhedra (divergence theorem)."""
import re, sys, json
import numpy as np

_ENT = re.compile(r'^#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;\s*$', re.S)


def _split_args(s):
    """top-level comma split of a STEP argument list (keeps nested parentheses and strings)"""
    out, depth, cur, q = [], 0, [], False
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            cur.append(c)
            if c == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    cur.append("'")
                    i += 1
                else:
                    q = False
        elif c == "'":
            q = True
            cur.append(c)
        elif c == '(':
            depth += 1
            cur.append(c)
        elif c == ')':
            depth -= 1
            cur.append(c)
        elif c == ',' and depth == 0:
            out.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    if cur:
        out.append(''.join(cur).strip())
    return out


def _refs(s):
    return [int(x) for x in re.findall(r'#(\d+)', s)]


def _str(s):
    s = s.strip()
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1].replace("''", "'")
        s = re.sub(r'\\X\\([0-9A-F]{2})', lambda m: chr(int(m.group(1), 16)), s)
        s = re.sub(r'\\X2\\([0-9A-F]+)\\X0\\', lambda m: ''.join(chr(int(m.group(1)[i:i + 4], 16)) for i in range(0, len(m.group(1)), 4)), s)
    return s


def read(path):
    ents = {}
    buf = []
    with open(path, 'r', encoding='latin-1') as fh:
        data = False
        for line in fh:
            if not data:
                if line.startswith('DATA;'):
                    data = True
                continue
            buf.append(line.rstrip('\n'))
            if line.rstrip().endswith(';'):
                stmt = ''.join(buf)
                buf = []
                m = _ENT.match(stmt)
                if m:
                    ents[int(m.group(1))] = (m.group(2), m.group(3))
    return ents


class Model:
    def __init__(self, path):
        self.e = read(path)
        self._pts = {}
        self.by_type = {}
        for k, (t, a) in self.e.items():
            self.by_type.setdefault(t, []).append(k)

    def pt(self, k):
        if k not in self._pts:
            t, a = self.e[k]
            c = re.search(r'\(([^()]*)\)\s*$', a).group(1)
            self._pts[k] = np.array([float(v) for v in c.split(',')])
        return self._pts[k]

    def axis2(self, k):
        t, a = self.e[k]
        args = _split_args(a)
        o = self.pt(_refs(args[1])[0])
        z = self.dir(_refs(args[2])[0]) if args[2] != '$' else np.array([0.0, 0.0, 1.0])
        x = self.dir(_refs(args[3])[0]) if len(args) > 3 and args[3] != '$' else np.array([1.0, 0.0, 0.0])
        x = x - np.dot(x, z) * z
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        m = np.eye(4)
        m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, y, z, o
        return m

    def dir(self, k):
        t, a = self.e[k]
        c = re.search(r'\(([^()]*)\)\s*$', a).group(1)
        v = np.array([float(x) for x in c.split(',')])
        return v / np.linalg.norm(v)

    def loop(self, k):
        t, a = self.e[k]
        return [self.pt(r) for r in _refs(a)]

    def face(self, k):
        """-> list of loops (each a list of points), the first the outer; loop orientation applied"""
        t, a = self.e[k]
        args = _split_args(a)
        loops = []
        for b in _refs(args[1]):
            bt, ba = self.e[b]
            bargs = _split_args(ba)
            pts = self.loop(_refs(bargs[1])[0])
            if bargs[2].strip() == '.F.':
                pts = pts[::-1]
            loops.append((bt == 'FACE_OUTER_BOUND', pts))
        if t in ('FACE_SURFACE', 'ADVANCED_FACE') and len(args) > 3 and args[3].strip() == '.F.':
            loops = [(o, p[::-1]) for o, p in loops]
        loops.sort(key=lambda x: not x[0])
        return [p for _, p in loops]

    def shell(self, k, flip=False):
        t, a = self.e[k]
        if t == 'ORIENTED_CLOSED_SHELL':
            args = _split_args(a)
            return self.shell(_refs(args[2])[0], flip ^ (args[3].strip() == '.F.'))
        args = _split_args(a)
        faces = [self.face(f) for f in _refs(args[1])]
        if flip:
            faces = [[lp[::-1] for lp in fc] for fc in faces]
        return faces

    def item(self, k, T):
        """solids of a representation item -> list of {'outer': faces, 'voids': [faces]} transformed by T"""
        t, a = self.e[k]
        args = _split_args(a)
        tf = lambda faces: [[[(T @ np.append(p, 1.0))[:3] for p in lp] for lp in fc] for fc in faces]
        if t == 'FACETED_BREP' or t == 'MANIFOLD_SOLID_BREP':
            return [{'outer': tf(self.shell(_refs(args[1])[0])), 'voids': []}]
        if t == 'BREP_WITH_VOIDS':
            outer = self.shell(_refs(args[1])[0])
            voids = [self.shell(v) for v in _refs(args[2])]
            return [{'outer': tf(outer), 'voids': [tf(v) for v in voids]}]
        if t == 'MAPPED_ITEM':
            src, tgt = _refs(args[1])[0], _refs(args[2])[0]
            st, sa = self.e[src]
            sargs = _split_args(sa)
            origin = self.axis2(_refs(sargs[0])[0])
            rep = _refs(sargs[1])[0]
            target = self.axis2(tgt)
            M = T @ target @ np.linalg.inv(origin)
            return self.rep(rep, M)
        if t in ('SHELL_BASED_SURFACE_MODEL',):
            out = []
            for s in _refs(args[1]):
                out.append({'outer': tf(self.shell(s)), 'voids': [], 'open': True})
            return out
        if t == 'AXIS2_PLACEMENT_3D':
            return []
        raise ValueError('item ' + t)

    def rep(self, k, T=None):
        T = np.eye(4) if T is None else T
        t, a = self.e[k]
        args = _split_args(a)
        out = []
        for it in _refs(args[1]):
            out += self.item(it, T)
        return out

    def products(self):
        """{product_id: {'name', 'description', 'solids': [...]}}"""
        prod = {}
        for k in self.by_type.get('PRODUCT', []):
            args = _split_args(self.e[k][1])
            prod[k] = {'id': _str(args[0]), 'name': _str(args[1]), 'description': _str(args[2])}
        pdf = {}
        for k in self.by_type.get('PRODUCT_DEFINITION_FORMATION', []) + self.by_type.get('PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE', []):
            args = _split_args(self.e[k][1])
            pdf[k] = _refs(args[2])[0]
        pd = {}
        for k in self.by_type.get('PRODUCT_DEFINITION', []):
            args = _split_args(self.e[k][1])
            pd[k] = pdf.get(_refs(args[2])[0])
        pds = {}
        for k in self.by_type.get('PRODUCT_DEFINITION_SHAPE', []):
            args = _split_args(self.e[k][1])
            pds[k] = pd.get(_refs(args[2])[0])
        out = {}
        for k in self.by_type.get('SHAPE_DEFINITION_REPRESENTATION', []):
            args = _split_args(self.e[k][1])
            p = pds.get(_refs(args[0])[0])
            if p is None:
                continue
            info = prod[p]
            solids = self.rep(_refs(args[1])[0])
            out.setdefault(info['id'], {'name': info['name'], 'description': info['description'], 'solids': []})['solids'] += solids
        return out


# ------------------------------------------------------------------------------------------------ mass properties
def _face_terms(fc):
    """volume (6x) and first-moment (24x) contributions of one planar face with holes, via fan triangles per loop"""
    v6, m24 = 0.0, np.zeros(3)
    for lp in fc:
        p0 = lp[0]
        for i in range(1, len(lp) - 1):
            a, b = lp[i], lp[i + 1]
            d = np.dot(p0, np.cross(a, b))
            v6 += d
            m24 += d * (p0 + a + b)
    return v6, m24


def mass(solids):
    """exact volume, centroid and bbox of polyhedral solids (voids subtracted)"""
    V6, M24 = 0.0, np.zeros(3)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    # work relative to a local origin: models can sit hundreds of metres from the global origin, where the triple
    # products of the divergence formula would lose millimetres to rounding
    ref = None
    for s in solids:
        for fc in s['outer']:
            ref = np.asarray(fc[0][0], float)
            break
        if ref is not None:
            break
    if ref is None:
        return 0.0, np.zeros(3), lo, hi
    shift = lambda faces: [[[np.asarray(p, float) - ref for p in lp] for lp in fc] for fc in faces]
    solids = [{'outer': shift(s['outer']), 'voids': [shift(v) for v in s.get('voids', [])]} for s in solids]
    for s in solids:
        sv6, sm = 0.0, np.zeros(3)
        for fc in s['outer']:
            a, b = _face_terms(fc)
            sv6 += a
            sm += b
            for lp in fc:
                arr = np.asarray(lp)
                lo, hi = np.minimum(lo, arr.min(0)), np.maximum(hi, arr.max(0))
        sgn = 1.0 if sv6 >= 0 else -1.0
        V6 += sgn * sv6
        M24 += sgn * sm
        for vd in s.get('voids', []):
            vv6, vm = 0.0, np.zeros(3)
            for fc in vd:
                a, b = _face_terms(fc)
                vv6 += a
                vm += b
            vs = 1.0 if vv6 >= 0 else -1.0
            V6 -= vs * vv6
            M24 -= vs * vm
    vol = V6 / 6.0
    cen = (M24 / 24.0) / vol if abs(vol) > 1e-12 else np.zeros(3)
    return vol, cen + ref, lo + ref, hi + ref


if __name__ == '__main__':
    m = Model(sys.argv[1])
    P = m.products()
    for pid, d in list(P.items())[:5]:
        v, c, lo, hi = mass(d['solids'])
        print(pid, d['name'][:40], d['description'], round(v, 1), np.round(c, 2), np.round(lo, 1), np.round(hi, 1))
    print(len(P), 'products')
