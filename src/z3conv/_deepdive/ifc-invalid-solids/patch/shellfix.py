"""shellfix - kernel-free repair of one faceted closed shell before it is written as STEP FACETED_BREP(s).

repair_shell(faces, P) -> (pieces, info)
  faces  list of faces; a face is a list of loops (outer loop first); a loop is a list of vertex ids (ints shared between
         faces: the StepWriter point cache dedups at --prec decimals).  Inner loops wound like their outer loop are
         reversed IN PLACE (step 0), T-junction vertices are inserted in place and gap-closing faces are APPENDED
         (step 2b) - the caller writes every face from this list (indices >= the original count are new faces).
  P      vertex id -> (x, y, z)
  pieces list of pieces; a piece is a list of (face_index, reversed) -> write each piece as its own FACETED_BREP
         (reversed: write every loop of that face in reverse order, plane normal negated)
  info   Counter of what was done; empty <=> the shell is returned unchanged as one piece

Defects found in Zenitude-data-3 IFC sources (SDS/2 exports mostly) that OpenCASCADE does not heal on STEP read:
  0. inner loops (holes: IfcFaceBound) wound the same way as the outer loop (SDS/2 HSS / pipe end caps, plates with
     holes) - ISO 10303-42 requires the opposite sense; OCC reads such a tube as 'valid' with a 5x volume
                                                                         => reverse the inner loop
  1. double-sided meshes: every triangle written twice with opposite winding (SDS/2 'PartLibFastener' bolts)
     -> edges used 4x, volume 0                                         => keep one copy of each pair
  2. internal walls: chains of closed cells sharing a face (SDS/2 weld prism chains)
     -> the shared face appears twice (opposite winding), its edges 4x  => drop both copies (cells merge, volume kept)
  2b. small gaps in an otherwise closed mesh (SDS/2 library fasteners: T-junctions, single missing facets)
                                                                         => insert the T-junction vertex into the edge;
     fill the remaining small boundary loops with a planar face (fan of triangles on the loop's own vertices if not
     planar) - only holes < 10% of the area of the faces around them, so genuinely open surfaces stay open (they are
     then written as surfaces, see piece_closed)
  3. faces wound against their neighbours (single flipped faces)       => re-orient by walking manifold edges
  4. whole pieces wound inward (negative volume)                       => reverse the piece
  5. several disjoint closed pieces in one shell (bolt head + nut + washer; grating bars; weld runs)
                                                                         => one FACETED_BREP per closed piece
  Debris left over after the closed pieces are found (faces of total area < 1e-4 of the shell: zero-area slivers) is
  dropped; any larger leftover is written exactly as it came, as one extra piece.
  A closed piece wound inward in the source that lies strictly inside another piece is a void: it stays inward and is
  written in the same FACETED_BREP as its container.
No vertex moves by more than weld_tol (0.025 mm): vertices joined by a shorter edge are merged first (OCC merges them on
read anyway); otherwise face polygons are kept (loop order reversed, a duplicated face dropped, a collinear T-junction
vertex inserted, a small gap face added).  Pieces that
are not closed orientable 2-manifolds after steps 1-2 are written exactly as they came, together, as one extra piece.
"""
import collections

__all__ = ['repair_shell', 'piece_closed']


def _normal(loop, P):
    nx = ny = nz = 0.0
    q = [P[p] for p in loop]
    n = len(q)
    for i in range(n):
        x1, y1, z1 = q[i]; x2, y2, z2 = q[(i + 1) % n]
        nx += (y1 - y2) * (z1 + z2); ny += (z1 - z2) * (x1 + x2); nz += (x1 - x2) * (y1 + y2)
    return nx, ny, nz


def orient_inner_loops(faces, P):
    """step 0, in place: every inner loop gets the sense opposite to its face's outer loop; returns loops reversed"""
    n = 0
    for f in faces:
        if len(f) < 2:
            continue
        no = _normal(f[0], P)
        for k in range(1, len(f)):
            ni = _normal(f[k], P)
            if no[0] * ni[0] + no[1] * ni[1] + no[2] * ni[2] > 0:
                f[k] = f[k][::-1]; n += 1
    return n


def _edge_use(faces, idx):
    eu = collections.defaultdict(list)
    for fi in idx:
        for lp in faces[fi]:
            n = len(lp)
            for k in range(n):
                a, b = lp[k], lp[(k + 1) % n]
                if a != b:
                    eu[(a, b) if a < b else (b, a)].append((fi, a < b))
    return eu


def _bad_edges(faces, idx):
    if not idx:
        return 1 << 30
    return sum(1 for v in _edge_use(faces, idx).values() if len(v) != 2)


def _canon(loop):
    i = loop.index(min(loop))
    return tuple(loop[i:] + loop[:i])


def _signed_volume(faces, piece, P):
    """piece: [(fi, rev)]; divergence theorem about a local origin (precision on georeferenced coordinates)"""
    o = P[faces[piece[0][0]][0][0]]
    ox, oy, oz = o[0], o[1], o[2]
    v = 0.0
    for fi, rev in piece:
        for lp in faces[fi]:
            q = [P[p] for p in (lp[::-1] if rev else lp)]
            ax, ay, az = q[0][0] - ox, q[0][1] - oy, q[0][2] - oz
            for k in range(1, len(q) - 1):
                bx, by, bz = q[k][0] - ox, q[k][1] - oy, q[k][2] - oz
                cx, cy, cz = q[k + 1][0] - ox, q[k + 1][1] - oy, q[k + 1][2] - oz
                v += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
    return v / 6.0


def _bbox(faces, idx, P):
    q = [P[p] for fi in idx for lp in faces[fi] for p in lp]
    return [min(x[0] for x in q), min(x[1] for x in q), min(x[2] for x in q),
            max(x[0] for x in q), max(x[1] for x in q), max(x[2] for x in q)]


def _inside(a, b):
    return all(a[d] > b[d] and a[d + 3] < b[d + 3] for d in range(3))


def _components(idx, eu):
    par = {fi: fi for fi in idx}

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for v in eu.values():
        if len(v) == 2:
            ra, rb = find(v[0][0]), find(v[1][0])
            if ra != rb:
                par[ra] = rb
    g = collections.defaultdict(list)
    for fi in idx:
        g[find(fi)].append(fi)
    return sorted(g.values(), key=lambda c: c[0])


def _dist_to_seg(q, a, b):
    abx, aby, abz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    l2 = abx * abx + aby * aby + abz * abz
    if l2 <= 0:
        return 1e30, 0.0
    t = ((q[0] - a[0]) * abx + (q[1] - a[1]) * aby + (q[2] - a[2]) * abz) / l2
    dx, dy, dz = a[0] + t * abx - q[0], a[1] + t * aby - q[1], a[2] + t * abz - q[2]
    return (dx * dx + dy * dy + dz * dz) ** 0.5, t


def _area(loop, P):
    n = _normal(loop, P)
    return 0.5 * (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) ** 0.5


def close_gaps(faces, keep, eu, P, info, tol=0.03, max_hole_share=0.10):
    """(a) T-junctions: a vertex lying on a boundary edge of another face is inserted into that edge (collinear point,
    polygon unchanged); (b) remaining boundary loops are filled with one planar face (or a fan of triangles over the
    loop's own vertices when it is not planar) - only a hole smaller than max_hole_share of the faces around it
    (a missing facet or cap, not the open side of a surface) and never a copy of an existing face.
    Appends new faces to `faces`; returns the new keep list, or None (nothing done / not closable)."""
    bnd = [(k, v[0]) for k, v in eu.items() if len(v) == 1]
    bv = set(x for k, _ in bnd for x in k)
    inserted = 0
    # (a) T-junctions, bucketed on a grid so large shells stay linear
    cell = 50.0
    grid = collections.defaultdict(list)
    for v in bv:
        q = P[v]; grid[(int(q[0] // cell), int(q[1] // cell), int(q[2] // cell))].append(v)
    ins = collections.defaultdict(list)          # (face, a, b) -> [(t, v)]
    for (k, (fi, fwd)) in bnd:
        a, b = (k[0], k[1]) if fwd else (k[1], k[0])
        A, B = P[a], P[b]
        lo = [int(min(A[d], B[d]) // cell) for d in range(3)]; hi = [int(max(A[d], B[d]) // cell) for d in range(3)]
        if (hi[0] - lo[0] + 1) * (hi[1] - lo[1] + 1) * (hi[2] - lo[2] + 1) > 4096:
            continue
        for gx in range(lo[0], hi[0] + 1):
            for gy in range(lo[1], hi[1] + 1):
                for gz in range(lo[2], hi[2] + 1):
                    for v in grid.get((gx, gy, gz), ()):
                        if v == a or v == b:
                            continue
                        d, t = _dist_to_seg(P[v], A, B)
                        if d <= tol and 1e-6 < t < 1 - 1e-6:
                            ins[(fi, a, b)].append((t, v))
    for (fi, a, b), lst in ins.items():
        lst.sort()
        mid = [v for _, v in lst]
        for li, lp in enumerate(faces[fi]):
            n = len(lp)
            for k in range(n):
                if lp[k] == a and lp[(k + 1) % n] == b:
                    faces[fi][li] = lp[:k + 1] + mid + lp[k + 1:]
                    inserted += len(mid)
                    break
            else:
                continue
            break
    if inserted:
        info['tjunction_vertices_inserted'] = inserted
        eu = _edge_use(faces, keep)
    done = list(keep) if inserted else None
    # (b) boundary loops -> faces.  The boundary graph (directed against the faces) is split into simple cycles; a
    # vertex where the boundary pinches (two gaps touching) is handled by cutting the cycle where the walk returns.
    out = collections.defaultdict(list)
    nb = 0
    for k, v in eu.items():
        if len(v) == 1:
            fi, fwd = v[0]
            a, b = (k[0], k[1]) if fwd else (k[1], k[0])
            out[b].append(a); nb += 1                # the filling face runs against its neighbour
    new = []
    if out:
        indeg = collections.Counter(x for y in out.values() for x in y)
        if any(len(out.get(x, ())) != indeg[x] for x in set(out) | set(indeg)):
            return done                             # boundary is not a union of closed loops
        holes = []
        for s0 in list(out):                        # Hierholzer-style walk; a revisited vertex closes a simple cycle
            while out[s0]:
                path = [s0]; pos = {s0: 0}; cur = s0
                while out[cur]:
                    nx = out[cur].pop()
                    if nx in pos:
                        i = pos[nx]; cyc = path[i:]
                        if len(cyc) < 3:
                            return done             # 2-cycle: two faces meeting edge to edge, not a hole
                        holes.append(cyc)
                        for x in cyc[1:]:
                            del pos[x]
                        path = path[:i + 1]
                    else:
                        pos[nx] = len(path); path.append(nx)
                    cur = nx
        # a hole is filled only inside a piece it is a small part of: the faces around it (linked through shared
        # edges) must have >= 1/max_hole_share times its area, and it must not repeat an existing face (a lone
        # zero-thickness face would otherwise be "closed" by its own twin)
        par = {fi: fi for fi in keep}

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]; x = par[x]
            return x
        for v in eu.values():
            for k in range(1, len(v)):
                ra, rb = find(v[0][0]), find(v[k][0])
                if ra != rb:
                    par[ra] = rb
        carea = collections.Counter()
        for fi in keep:
            carea[find(fi)] += _area(faces[fi][0], P)
        fsets = set(frozenset(faces[fi][0]) for fi in keep)
        fill = []
        for lp in holes:
            a, b = lp[0], lp[1]                     # a boundary edge of the hole -> the face next to it
            v = eu.get((a, b) if a < b else (b, a))
            if not v:
                continue
            if frozenset(lp) in fsets or _area(lp, P) > max_hole_share * carea[find(v[0][0])]:
                continue
            fill.append(lp)
        holes = fill
        for lp in holes:
            n = _normal(lp, P); nl = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) ** 0.5
            c = P[lp[0]]
            dev = max(abs((P[p][0] - c[0]) * n[0] + (P[p][1] - c[1]) * n[1] + (P[p][2] - c[2]) * n[2]) / nl for p in lp) if nl > 0 else 1e30
            if dev <= tol:
                new.append([lp])
            else:
                new += [[[lp[0], lp[k], lp[k + 1]]] for k in range(1, len(lp) - 1)]
    if not inserted and not new:
        return None
    if new:
        info['gap_faces_added'] = len(new)
    base = len(faces)
    faces.extend(new)
    return list(keep) + list(range(base, base + len(new)))


def piece_closed(faces, piece):
    """True if the piece ([(fi, reversed)]) is a closed, consistently wound 2-manifold (every edge used exactly twice,
    once in each direction) - i.e. it can be written as a FACETED_BREP; otherwise write it as an open shell surface"""
    eu = collections.defaultdict(list)
    for fi, rev in piece:
        for lp in faces[fi]:
            n = len(lp)
            for k in range(n):
                a, b = (lp[(k + 1) % n], lp[k]) if rev else (lp[k], lp[(k + 1) % n])
                if a != b:
                    eu[(a, b) if a < b else (b, a)].append(a < b)
    return bool(eu) and all(len(v) == 2 and v[0] != v[1] for v in eu.values())


def collapse_micro_edges(faces, P, tol):
    """edges shorter than tol (default 0.025 mm = 2.5 steps of the 0.01 mm output grid of --prec 2; the file declares
    a 0.01 mm uncertainty and OpenCASCADE's shape healing merges vertices that close on read) join their two
    vertices - otherwise OCC is left with 2-point / self-intersecting / imbricated wires on micro facets (SDS/2 fastener
    threads). In place; returns (#vertices merged, set of faces that became degenerate)."""
    t2 = tol * tol
    alias = {}

    def root(v):
        while v in alias:
            v = alias[v]
        return v
    for f in faces:
        for lp in f:
            n = len(lp)
            for k in range(n):
                a, b = root(lp[k]), root(lp[(k + 1) % n])
                if a != b:
                    qa, qb = P[a], P[b]
                    if (qa[0] - qb[0]) ** 2 + (qa[1] - qb[1]) ** 2 + (qa[2] - qb[2]) ** 2 < t2:
                        alias[max(a, b)] = min(a, b)
    if not alias:
        return 0, set()
    dead = set()
    for fi, f in enumerate(faces):
        nf = []
        for li, lp in enumerate(f):
            q = []
            for v in lp:
                v = root(v)
                if not q or q[-1] != v:
                    q.append(v)
            while len(q) > 1 and q[0] == q[-1]:
                q.pop()
            if len(set(q)) < 3:
                if li == 0:
                    nf = None; break
                continue
            nf.append(q)
        if nf is None:
            dead.add(fi); f[:] = [f[0]]           # keep the slot (indices are shared with the caller)
        else:
            f[:] = nf
    return len(alias), dead


def repair_shell(faces, P, split=True, weld_tol=0.025):
    info = collections.Counter()
    n0 = len(faces)
    unchanged = [[(fi, False) for fi in range(n0)]]
    if n0 < 4:
        return unchanged, info
    nm, dead = collapse_micro_edges(faces, P, weld_tol) if weld_tol else (0, set())
    if nm:
        info['micro_edges_collapsed'] = nm
        if dead:
            info['degenerate_faces_dropped'] = len(dead)
    nin = orient_inner_loops([f for fi, f in enumerate(faces) if fi not in dead], P)
    if nin:
        info['inner_loops_reversed'] = nin
    keep = [fi for fi in range(n0) if fi not in dead]
    eu = _edge_use(faces, keep)
    consistent = all(len(v) == 2 and v[0][1] != v[1][1] for v in eu.values())
    if not consistent:
        # ---- 1/2: duplicated faces (same vertex set)
        groups = collections.defaultdict(list)
        for fi in keep:
            groups[frozenset(p for lp in faces[fi] for p in lp)].append(fi)
        same_dup, opp_pairs = set(), []
        for g in groups.values():
            if len(g) < 2:
                continue
            seen = {}
            for fi in g:
                c = _canon(faces[fi][0]); r = _canon(faces[fi][0][::-1])
                if c in seen:
                    same_dup.add(fi)               # exact repeat with the same winding: always redundant
                elif seen.get(r) is not None:
                    opp_pairs.append((seen[r], fi)); seen[r] = None
                else:
                    seen[c] = fi
        if same_dup:
            keep = [fi for fi in keep if fi not in same_dup]; info['duplicate_faces_dropped'] = len(same_dup)
        if opp_pairs:
            both = set(x for pr in opp_pairs for x in pr); one = set(pr[1] for pr in opp_pairs)
            cand = {'keep': keep}
            if 2 * len(opp_pairs) >= 0.75 * len(keep):
                # (nearly) every face has a reversed twin: a double-sided surface mesh, never cell walls
                cand['double_sided_collapsed'] = [fi for fi in keep if fi not in one]
            else:
                cand['internal_walls_removed'] = [fi for fi in keep if fi not in both]
                cand['double_sided_collapsed'] = [fi for fi in keep if fi not in one]
            score = {k: _bad_edges(faces, v) for k, v in cand.items()}
            best = min(cand, key=lambda k: (score[k], k != 'keep'))
            if best != 'keep' and score[best] < score['keep']:
                keep = cand[best]; info[best] = len(opp_pairs)
        if info:
            eu = _edge_use(faces, keep)
        # ---- 2b: open shells with small gaps (T-junctions, missing facets): close them without moving a vertex
        if any(len(v) == 1 for v in eu.values()):
            nk = close_gaps(faces, keep, eu, P, info)
            if nk is not None:
                keep = nk; eu = _edge_use(faces, keep)
    # ---- 3/4/5: pieces through manifold edges; orientation walk inside each closed piece
    pieces, loose = [], []
    comps = _components(keep, eu)
    for c in comps:
        if consistent and len(comps) == 1:
            flip = dict.fromkeys(c, False)
        else:
            ceu = _edge_use(faces, c) if len(comps) > 1 else eu
            if len(c) < 4 or any(len(v) != 2 for v in ceu.values()):
                loose += c; continue                # open / non-manifold: written as it came
            adj = collections.defaultdict(list)
            for (f1, d1), (f2, d2) in ceu.values():
                adj[f1].append((f2, d1 == d2)); adj[f2].append((f1, d1 == d2))
            flip = {c[0]: False}; stack = [c[0]]; ok = True
            while stack and ok:
                f = stack.pop()
                for g, same in adj[f]:
                    want = flip[f] ^ same
                    if g not in flip:
                        flip[g] = want; stack.append(g)
                    elif flip[g] != want:
                        ok = False; break
            if not ok:
                loose += c; continue                # non-orientable: written as it came
        pc = [(fi, flip[fi]) for fi in c]
        v = _signed_volume(faces, pc, P)
        if v < 0:
            pc = [(fi, not r) for fi, r in pc]
        nflip = sum(1 for _, r in pc if r)
        v_src = _signed_volume(faces, [(fi, False) for fi in c], P) if nflip == len(c) else None
        pieces.append({'pc': pc, 'nflip': nflip, 'n': len(c), 'v_src': v_src, 'bb': None, 'host': None})
    # voids: a piece wound inward in the source, strictly inside another piece
    if len(pieces) > 1 and not info.get('double_sided_collapsed'):   # winding of a double-sided mesh means nothing
        for p in pieces:
            p['bb'] = _bbox(faces, [fi for fi, _ in p['pc']], P)
        for p in pieces:
            if p['nflip'] == p['n'] and p['v_src'] is not None and p['v_src'] < 0:
                hosts = [q for q in pieces if q is not p and q['nflip'] < q['n'] and _inside(p['bb'], q['bb'])]
                if hosts:
                    p['host'] = min(hosts, key=lambda q: (q['bb'][3] - q['bb'][0]) * (q['bb'][4] - q['bb'][1]) * (q['bb'][5] - q['bb'][2]))
                    p['pc'] = [(fi, False) for fi, _ in p['pc']]; p['nflip'] = 0
                    info['voids_kept'] += 1
    out = []
    for p in pieces:
        if p['host'] is not None:
            continue
        pc = list(p['pc'])
        for q in pieces:
            if q['host'] is p:
                pc += q['pc']
        if p['nflip'] == p['n']:
            info['pieces_reversed_outward'] += 1
        elif p['nflip']:
            info['faces_reoriented'] += p['nflip']
        out.append(pc)
    if loose:
        la = sum(_area(faces[fi][0], P) for fi in loose)
        if out and la <= 1e-4 * sum(_area(faces[fi][0], P) for fi in keep):
            info['sliver_faces_dropped'] = len(loose)   # zero-area debris next to closed pieces (no volume)
        else:
            out.append([(fi, False) for fi in sorted(loose)])
            if out[:-1]:
                info['faces_left_as_is'] = len(loose)
    if len(out) > 1:
        info['pieces_split'] = len(out)
    if not info or info.keys() <= {'inner_loops_reversed', 'micro_edges_collapsed', 'degenerate_faces_dropped'} \
            and len(out) == 1 and len(out[0]) == len(keep) and all(not r for _, r in out[0]):
        return ([[(fi, False) for fi in keep]] if info else unchanged), info
    if not split and len(out) > 1:
        out = [[x for c in out for x in c]]
    return out, info
