"""n4_ifc_c2s (GRID3, Tekla IFC): 6 identical curved plates PL1/4"X5 9/16" arrive OPEN (surface model in the STEP, invalid
solid in our rebuild). Each side face of the plate is a 1,000-vertex polygon in the source IFC and stops short of the
plate's outline: the rest of each side is missing (268 free edges = 2 loops of 134 points, each loop flat and lying in
its side plane). Estimate: fill each free loop with the planar face it bounds -> a closed faceted solid. The free loops
are exactly the missing side regions (not holes: the two loops differ, a through-hole would repeat on both sides)."""
import collections
import math

import est_common as E


def free_loops(faces):
    key = lambda p: (round(p[0], 2), round(p[1], 2), round(p[2], 2))
    ec = collections.Counter()
    pt = {}
    for f in faces:
        for lp in f:
            n = len(lp)
            for i in range(n):
                a, b = key(lp[i]), key(lp[(i + 1) % n])
                pt[a], pt[b] = lp[i], lp[(i + 1) % n]
                ec[tuple(sorted([a, b]))] += 1
    free = [e for e, c in ec.items() if c == 1]
    adj = collections.defaultdict(list)
    for a, b in free:
        adj[a].append(b)
        adj[b].append(a)
    if any(len(v) != 2 for v in adj.values()):
        return None, len(free)
    loops, seen = [], set()
    for v0 in sorted(adj):
        if v0 in seen:
            continue
        loop, prev, cur = [v0], None, v0
        seen.add(v0)
        while True:
            nx = [w for w in adj[cur] if w != prev]
            nxt = nx[0] if prev is not None else adj[cur][0]
            if nxt == v0:
                break
            if nxt in seen:
                return None, len(free)
            loop.append(nxt)
            seen.add(nxt)
            prev, cur = cur, nxt
        loops.append([pt[k] for k in loop])
    return loops, len(free)


def plane_fit(loop):
    n = [0.0, 0.0, 0.0]
    m = len(loop)
    for i in range(m):
        a, b = loop[i], loop[(i + 1) % m]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    ln = math.sqrt(sum(x * x for x in n))
    n = [x / ln for x in n]
    c = [sum(p[k] for p in loop) / m for k in range(3)]
    dev = max(abs(sum((p[k] - c[k]) * n[k] for k in range(3))) for p in loop)
    return n, c, dev


def make(tag, *a):
    t = E.Tree(tag)
    patch, log = E.new_patch(t), E.new_log(t)
    for gid, p in sorted(t.flagged('open_in_source')):
        ex = t.exact(gid)
        if not ex or len(ex['solids']) != 1:
            log['not_estimated'].append({'part_id': gid, 'category': 'open_in_source', 'why': 'no single faceted source body'})
            continue
        faces = ex['solids'][0]['faces']
        loops, nfree = free_loops(faces)
        if not loops:
            log['not_estimated'].append({'part_id': gid, 'category': 'open_in_source', 'why': f'{nfree} free edges do not form closed loops'})
            continue
        info, ok = [], True
        big = [len(f[0]) for f in faces if len(f[0]) >= 1000]
        for lp in loops:
            n, c, dev = plane_fit(lp)
            info.append({'points': len(lp), 'normal': [round(x, 6) for x in n], 'flatness_mm': round(dev, 4)})
            ok = ok and dev <= 0.05
        if not ok:
            log['not_estimated'].append({'part_id': gid, 'category': 'open_in_source', 'why': 'a free loop is not flat', 'loops': info})
            continue
        # each free loop shares the closing chord of one capped side polygon: the side face = that polygon continued along
        # the loop (one simple planar polygon; the capped polygon alone, closing across its chord, is not a valid face)
        key = lambda q: (round(q[0], 2), round(q[1], 2), round(q[2], 2))
        capped = [i for i, fc in enumerate(faces) if len(fc) == 1 and len(fc[0]) >= 1000]
        merged, used = {}, set()
        for bi in capped:
            P = faces[bi][0]
            for li, L in enumerate(loops):
                idx = {key(q): j for j, q in enumerate(L)}
                if li in used or key(P[0]) not in idx or key(P[-1]) not in idx:
                    continue
                a, b, n = idx[key(P[-1])], idx[key(P[0])], len(L)
                fw = [(a + k) % n for k in range(n)]
                bw = [(a - k) % n for k in range(n)]
                p1, p2 = fw[:fw.index(b) + 1], bw[:bw.index(b) + 1]
                path = p1 if len(p1) > len(p2) else p2
                merged[bi] = [list(map(float, q)) for q in P] + [list(map(float, L[j])) for j in path[1:-1]]
                used.add(li)
                break
        if len(used) != len(loops):
            log['not_estimated'].append({'part_id': gid, 'category': 'open_in_source', 'why': 'a free loop does not continue a capped side polygon'})
            continue
        new_faces = [([merged[i]] if i in merged else f) for i, f in enumerate(faces)]
        for i in merged:
            info_i = {'capped_polygon_vertices': len(faces[i][0]), 'side_polygon_vertices': len(merged[i])}
            info.append(info_i)
        geom = {'kind': 'faceted', 'solids': [{'faces': new_faces, 'voids': []}]}
        basis = ('estimated: the source IFC writes each side of this curved plate as one polygon of exactly 1,000 vertices that '
                 'stops short of the outline (an exporter vertex cap) and closes across a chord; the rest of each side is a '
                 f'free-edge loop ({", ".join(str(i["points"]) for i in info if "points" in i)} points) lying flat (<= '
                 f'{max(i["flatness_mm"] for i in info if "flatness_mm" in i):g} mm) in that side plane and sharing the chord; each '
                 'side face is rebuilt as the capped polygon continued along its loop (every vertex a source vertex, none added); '
                 'the two loops differ, so they are not a through-hole; the 6 parts are identical (same 1,295.4 mm length, same loops)')
        patch['ops'].append({
            'op': 'replace_part', 'id': f'est:close:{gid}', 'part_id': gid, 'geometry': geom, 'colour': 'AMBER',
            'resolves': [{'part_id': gid, 'category': c} for c in ('open_in_source', 'surface_model', 'our_script_invalid_solid')],
            'provenance': {'what': f'curved plate {p["name"]} {t.parts[gid].get("designation")}: its 2 side faces completed where the source '
                                   f'polygons stop at 1,000 vertices (closed solid)',
                           'source': f'IFC {gid}: IfcFacetedBrep ({len(faces)} faces, every vertex kept)',
                           'basis': basis,
                           'evidence': {'confidence': 0.95, 'free_edges': nfree, 'loops': info, 'source_polygons_at_cap': big}}})
        log['estimates'].append({'kind': 'close_open_source_body', 'part_id': gid, 'name': p['name'],
                                 'designation': t.parts[gid].get('designation'), 'part_mark': t.parts[gid].get('part_mark'),
                                 'faces_source': len(faces), 'side_faces_completed': len(loops), 'faces_added': 0, 'free_edges': nfree, 'loops': info,
                                 'confidence': 0.95, 'basis': basis, 'bbox': p.get('bbox')})
    log['summary']['closed_plates'] = len(patch['ops'])
    log['left_to_other_tracks'] = ['nothing else flagged in n4 (814 GREY, 6 YELLOW/ORANGE/PURPLE = these 6 plates)']
    return t, patch, log
