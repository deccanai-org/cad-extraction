#!/usr/bin/env python3
"""Synthetic unit tests for shellfix.repair_shell (pure python, no kernel).  run: python3 test_shellfix.py"""
import sys, os, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shellfix import repair_shell, piece_closed, _signed_volume


def box(x0, y0, z0, x1, y1, z1, base=0):
    """closed, outward box: vertex ids base..base+7, 6 quads"""
    P = {}
    k = base
    for z in (z0, z1):
        for y in (y0, y1):
            for x in (x0, x1):
                P[k] = (float(x), float(y), float(z)); k += 1
    b = base
    F = [[[b + 0, b + 2, b + 3, b + 1]], [[b + 4, b + 5, b + 7, b + 6]], [[b + 0, b + 1, b + 5, b + 4]],
         [[b + 2, b + 6, b + 7, b + 3]], [[b + 0, b + 4, b + 6, b + 2]], [[b + 1, b + 3, b + 7, b + 5]]]
    return F, P


def vol(faces, piece, P):
    return _signed_volume(faces, piece, P)


def check(name, cond):
    print(('ok   ' if cond else 'FAIL ') + name)
    return cond


ok = True
# 1 clean box: unchanged
F, P = box(0, 0, 0, 10, 20, 30)
pcs, info = repair_shell(copy.deepcopy(F), P)
ok &= check('clean box unchanged', not info and len(pcs) == 1 and len(pcs[0]) == 6)

# 2 one face flipped -> re-oriented, volume +6000
F2 = copy.deepcopy(F); F2[3] = [F2[3][0][::-1]]
pcs, info = repair_shell(F2, P)
ok &= check('flipped face re-oriented', info.get('faces_reoriented') == 1 and abs(vol(F2, pcs[0], P) - 6000) < 1e-6)

# 3 whole box inward -> reversed outward
F3 = [[lp[::-1] for lp in f] for f in F]
pcs, info = repair_shell(F3, P)
ok &= check('inward box reversed', info.get('pieces_reversed_outward') == 1 and abs(vol(F3, pcs[0], P) - 6000) < 1e-6)

# 4 double-sided box (every face twice, opposite) -> one copy kept, closed, +6000
F4 = copy.deepcopy(F) + [[lp[::-1] for lp in f] for f in F]
pcs, info = repair_shell(F4, P)
ok &= check('double-sided collapsed', info.get('double_sided_collapsed') == 6 and len(pcs) == 1 and len(pcs[0]) == 6
            and piece_closed(F4, pcs[0]) and abs(vol(F4, pcs[0], P) - 6000) < 1e-6)

# 5 two boxes sharing a wall (internal wall twice) -> wall removed, one closed piece, volume 2 x 6000
Fa, Pa = box(0, 0, 0, 10, 20, 30)
Fb, Pb = box(10, 0, 0, 20, 20, 30, base=8)
P5 = dict(Pa); P5.update(Pb)
# weld shared vertices of b onto a (x=10 plane)
ren = {}
for kb, qb in Pb.items():
    for ka, qa in Pa.items():
        if qa == qb:
            ren[kb] = ka
Fb = [[[ren.get(v, v) for v in lp] for lp in f] for f in Fb]
F5 = Fa + Fb
pcs, info = repair_shell(F5, P5)
ok &= check('internal wall removed', info.get('internal_walls_removed') == 1 and len(pcs) == 1 and piece_closed(F5, pcs[0])
            and abs(vol(F5, pcs[0], P5) - 12000) < 1e-6)

# 6 two disjoint boxes in one shell -> two pieces
Fc, Pc = box(100, 0, 0, 110, 20, 30, base=8)
P6 = dict(Pa); P6.update(Pc)
F6 = copy.deepcopy(Fa) + Fc
pcs, info = repair_shell(F6, P6)
ok &= check('disjoint pieces split', len(pcs) == 2 and all(piece_closed(F6, p) for p in pcs))

# 7 hollow square tube with end caps whose inner loop has the SAME sense as the outer loop (SDS/2 HSS)
P7 = {}
def ring(z, r, base):
    pts = [(-r, -r), (r, -r), (r, r), (-r, r)]
    for i, (x, y) in enumerate(pts):
        P7[base + i] = (float(x), float(y), float(z))
    return [base + i for i in range(4)]
o0, i0, o1, i1 = ring(0, 10, 0), ring(0, 8, 4), ring(100, 10, 8), ring(100, 8, 12)
F7 = []
for k in range(4):
    a, b = k, (k + 1) % 4
    F7.append([[o0[a], o0[b], o1[b], o1[a]]])          # outer walls, outward
    F7.append([[i0[b], i0[a], i1[a], i1[b]]])          # inner walls, facing the axis (outward of the material)
F7.append([o0[::-1], i0[::-1]])                         # bottom cap: outer loop CW from below = outward -z; inner loop SAME sense (defect)
F7.append([o1, i1])                                     # top cap: same defect
pcs, info = repair_shell(F7, P7)
v7 = vol(F7, pcs[0], P7)
ok &= check('same-sense inner loops reversed, hollow volume', info.get('inner_loops_reversed') == 2 and len(pcs) == 1
            and piece_closed(F7, pcs[0]) and abs(v7 - (400 - 256) * 100) < 1e-6)

# 8 box with a T-junction (one edge of a face split by a vertex the neighbour does not have)
F8, P8 = box(0, 0, 0, 10, 20, 30)
P8[99] = (5.0, 0.0, 0.0)                                # midpoint of edge 0-1
F8[0] = [[0, 2, 3, 1, 99]]                              # bottom face has the extra vertex, front face (0,1,5,4) does not
pcs, info = repair_shell(F8, P8)
ok &= check('T-junction split', info.get('tjunction_vertices_inserted') == 1 and len(pcs) == 1 and piece_closed(F8, pcs[0]))

# 9 box missing one face (1/6 of the area -> > 10% of the faces around it): stays open, written as surface
F9 = copy.deepcopy(F[:5])
pcs, info = repair_shell(F9, P)
ok &= check('open box not closed (surface)', not any(piece_closed(F9, p) for p in pcs) and not info.get('gap_faces_added'))

# 10 a long bar missing its small end cap (< 10%): cap added, closed
F10, P10 = box(0, 0, 0, 10, 10, 300)
del F10[0]                                              # bottom cap z=0 (10x10 = 100 of 12200)
pcs, info = repair_shell(F10, P10)
ok &= check('small missing cap filled', info.get('gap_faces_added') == 1 and len(pcs) == 1 and piece_closed(F10, pcs[0])
            and abs(vol(F10, pcs[0], P10) - 30000) < 1e-6)

# 11 lone zero-thickness face next to a box: box closed, lone face left as open remainder (surface), not twinned
F11, P11 = box(0, 0, 0, 10, 20, 30)
P11.update({50: (100.0, 0.0, 0.0), 51: (110.0, 0.0, 0.0), 52: (110.0, 10.0, 0.0), 53: (100.0, 10.0, 0.0)})
F11.append([[50, 51, 52, 53]])
pcs, info = repair_shell(F11, P11)
ok &= check('lone face kept as open remainder', len(pcs) == 2 and piece_closed(F11, pcs[0]) and not piece_closed(F11, pcs[1])
            and not info.get('gap_faces_added'))

# 12 micro edge (< 0.025 mm) collapsed: box with a sliver vertex 0.01 mm from a corner
F12, P12 = box(0, 0, 0, 10, 20, 30)
P12[77] = (0.0, 0.0, 0.01)
F12[2] = [[0, 1, 5, 4, 77]]                             # front face (0,1,5,4) gets vertex 77 between 4 and 0
F12[4] = [[77, 4, 6, 2, 0]]                             # left face (0,4,6,2) too -> 77 is a real vertex, edge 0-77 0.01 mm
pcs, info = repair_shell(F12, P12)
ok &= check('micro edge collapsed', info.get('micro_edges_collapsed') == 1 and len(pcs) == 1 and piece_closed(F12, pcs[0]))

print('ALL OK' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
