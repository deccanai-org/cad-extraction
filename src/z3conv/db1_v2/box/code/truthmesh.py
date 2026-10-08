"""Representation-independent bolt truth: tessellate each IfcMechanicalFastener (world mm), project onto a plane
(group csys), cluster the projected vertices -> bolt centres (x, y) in that frame + axial extent per bolt."""
import numpy as np, ifcopenshell, ifcopenshell.geom
_st = None
def mesh(e):
    global _st
    if _st is None:
        _st = ifcopenshell.geom.settings(); _st.set(_st.USE_WORLD_COORDS, True)
    sh = ifcopenshell.geom.create_shape(_st, e)
    V = np.array(sh.geometry.verts).reshape(-1, 3) * 1000.0
    return V
def centres(V, O, x, y, d, cell=None):
    """cluster projected vertices; a bolt's head/nut hexagons + shank project to discs around the centre"""
    z = np.cross(x, y); R = V - O
    P = np.stack([R @ x, R @ y], 1); Z = R @ z
    cell = cell or max(d, 5.0)
    lab = -np.ones(len(P), int); cs = []
    order = np.argsort(P[:, 0])
    for i in order:
        if lab[i] >= 0: continue
        sel = np.nonzero((np.abs(P[:, 0] - P[i, 0]) < 2.5 * cell) & (np.abs(P[:, 1] - P[i, 1]) < 2.5 * cell) & (lab < 0))[0]
        sel = sel[np.linalg.norm(P[sel] - P[i], axis=1) < 2.5 * cell]
        lab[sel] = len(cs); cs.append(sel)
    out = []
    for sel in cs:
        q = P[sel]; c = (q.min(0) + q.max(0)) / 2
        out.append((c[0], c[1], float(Z[sel].min()), float(Z[sel].max()), len(sel)))
    return out

def check(V, O, x, y, P, d, tol=1.0):
    """two-way check of decoded bolt centres P [(u, v)] against the fastener mesh V: every decoded centre has shank material
    on its axis (>= 6 vertices within d/2 + tol), every mesh vertex lies within the head/nut envelope (1.1 d) of some centre.
    -> (n_ok_centres, n_centres, frac_vertices_explained)"""
    z = np.cross(x, y); R = V - O; Q = np.stack([R @ x, R @ y], 1)
    P = np.asarray(P, float).reshape(-1, 2)
    D = np.linalg.norm(Q[:, None, :] - P[None, :, :], axis=2)
    okc = int(((D <= d / 2 + tol).sum(0) >= 6).sum())
    expl = float((D.min(1) <= 1.1 * d + tol).mean()) if len(Q) else 0.0
    return okc, len(P), expl
