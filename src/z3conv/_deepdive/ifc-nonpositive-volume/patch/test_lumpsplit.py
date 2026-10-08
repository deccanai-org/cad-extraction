#!/usr/bin/env python3
"""Synthetic unit tests for lumpsplit.decompose (no kernel). run: python3 test_lumpsplit.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lumpsplit as L


class Mesh:
    def __init__(self):
        self.xyz = {}; self.key = {}; self.faces = []

    def v(self, p):
        p = tuple(float(c) for c in p)
        if p not in self.key:
            self.key[p] = len(self.key) + 1; self.xyz[self.key[p]] = p
        return self.key[p]

    def quad(self, *ps):
        self.faces.append([[self.v(p) for p in ps]])

    def box(self, x0, y0, z0, x1, y1, z1, inward=False):
        c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]   # outward (CCW from outside)
        for q in quads:
            ps = [c[i] for i in q]
            self.quad(*(ps[::-1] if inward else ps))


def run(m):
    return L.decompose(m.faces, m.xyz)


def check(name, cond):
    print(('ok   ' if cond else 'FAIL ') + name)
    return cond


ok = True
m = Mesh(); m.box(0, 0, 0, 1, 1, 1)
c, i = run(m); ok &= check('single cube: 1 closed component, vol 1', len(c) == 1 and c[0]['closed'] and abs(c[0]['vol'] - 1) < 1e-9)

m = Mesh(); m.box(0, 0, 0, 1, 1, 1); m.box(5, 0, 0, 6, 1, 1)
c, i = run(m); ok &= check('two disjoint cubes -> 2 components', len(c) == 2 and all(x['closed'] for x in c))

m = Mesh(); m.box(0, 0, 0, 1, 1, 1); m.box(1, 0, 0, 2, 1, 1)
c, i = run(m)
ok &= check('two cubes sharing a face (face twice, opposite): internal pair dropped -> 1 closed solid vol 2',
            len(c) == 1 and c[0]['closed'] and abs(c[0]['vol'] - 2) < 1e-9 and i['cancelled_faces'] == 2)

m = Mesh(); m.box(0, 0, 0, 1, 1, 1); m.box(1, 1, 0, 2, 2, 1)
c, i = run(m)
ok &= check('two cubes sharing only an edge (4 uses): radial split -> 2 closed solids',
            len(c) == 2 and all(x['closed'] and abs(x['vol'] - 1) < 1e-9 for x in c) and i['radial_edges'] >= 1)

m = Mesh(); m.box(0, 0, 0, 4, 4, 4); m.box(1, 1, 1, 2, 2, 2, inward=True)
c, i = run(m)
ok &= check('cube with an inward inner cube (void): kept in one shell, vol 63',
            len(c) == 1 and abs(c[0]['vol'] - 63) < 1e-9 and i.get('voids_kept') == 1)

m = Mesh(); m.box(0, 0, 0, 4, 4, 4); m.box(1, 1, 1, 2, 2, 2)
c, i = run(m)
ok &= check('cube with an OUTWARD inner cube (nut inside a washer bbox): 2 separate positive solids', len(c) == 2)

m = Mesh(); m.quad((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)); m.quad((0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0))
c, i = run(m)
ok &= check('double-sided open square: cancellation rejected, left as written (1 component, 2 faces)',
            len(c) == 1 and len(c[0]['faces']) == 2 and i['cancel_rejected'] == 1 and i['cancelled_faces'] == 0)

m = Mesh(); m.box(0, 0, 0, 1, 1, 1); m.faces.pop()                                     # open box
m.box(5, 0, 0, 6, 1, 1)
c, i = run(m)
ok &= check('open box + closed box: closed one split off, open one kept as is',
            len(c) == 2 and sum(1 for x in c if not x['closed']) == 1)

m = Mesh(); m.box(0, 0, 0, 1, 1, 1, inward=True)
c, i = run(m)
ok &= check('single inside-out cube: untouched (never re-oriented)', len(c) == 1 and c[0]['vol'] < 0)
print('ALL OK' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
