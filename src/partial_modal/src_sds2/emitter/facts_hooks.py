"""Side tables of one SDS/2 conversion for the issue maker, collected inside the converter process (installed by
emit_run.py next to the IFC emitter; version-agnostic over sds2-step-pipeline v4 / v5.x).

Two hooks, both run AFTER the converter has written what they look at, so nothing the converter computes or writes can
change (the caller proves it: the STEP written is byte-identical to the shipped STEP):

  sds2ifc.emit (wrapped)    on the Write() of the final STEP, after the IFC is written: walks the same XCAF document
                            and writes <out>_facts_instances.jsonl, one row per top-level instance in document order:
                            GlobalId (sds2label.guid, the pipeline's part id), label, unique part number (as
                            <out>_ifc_products.jsonl), world placement (origin mm, x / z axes), world bounding box (mm,
                            OpenCASCADE optimal box of the placed B-rep), and the hole tools the converter cut into the
                            part (sds2ifc's cut_holes record) placed in world mm: [kind, p0 xyz, axis xyz, radius, length
                            (, slot half length)]
  to_step2.convert (wrapped) after convert() returns for the final -o path: writes <out>_facts_convert.json: the
                            converter's stats dict, decoded holes per piece (to_step2.HOLES) and the holes-cut counter,
                            every skipped piece (<out>_skipped.csv) with the geometry the SDS/2 job records for it (piece
                            table name / section / L / W / T / weight, its placement found in the member file by its
                            origin, its own vertices local + world and their envelope: range along the thinnest local
                            axis + convex hull on the other two), and every member (type, work line p1 -> p2 in mm,
                            section and its dimensions) - members that got no solid at all are what the converter
                            dropped without a skipped row
v5.x converters run convert() in a forked child and may re-run it for read-back repair: each run rewrites both files
for the final path, the last one wins (as for the STEP and the IFC). Errors are written to <out>_facts_error.txt and
never raised into the converter."""
import collections, csv, json, os, sys, traceback
import numpy as np

MM = 25.4
TARGET = None
META = {}


def install(conv_root, target, meta):
    global TARGET, META
    TARGET = os.path.abspath(target)
    META = dict(meta)
    import sds2ifc
    import to_step2
    orig_emit = sds2ifc.emit

    def emit(doc, step_path):
        orig_emit(doc, step_path)
        try:
            instances_facts(doc, step_path)
        except Exception:
            _err('instances', step_path)
    sds2ifc.emit = emit
    orig_convert = to_step2.convert

    def convert(job, out, *a, **k):
        r = orig_convert(job, out, *a, **k)
        if os.path.abspath(out) == TARGET:
            try:
                convert_facts(job, out, r)
            except Exception:
                _err('convert', out)
        return r
    to_step2.convert = convert


def _err(what, path):
    with open(os.path.splitext(path)[0] + '_facts_error.txt', 'a') as f:
        f.write(f'[{what}]\n' + traceback.format_exc() + '\n')


def _f(x, nd=4):
    return round(float(x), nd)


def _js(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    if isinstance(o, tuple):
        return list(o)
    return str(o)


# ======================================================================================== instances (emit time)
def instances_facts(doc, step_path):
    import sds2ifc, sds2label
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.TDF import TDF_Label
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    try:
        from OCP.TDF import TDF_LabelSequence
    except ImportError:
        from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = TDF_LabelSequence()
    st.GetFreeShapes(roots)
    I3 = np.hstack([np.eye(3), np.zeros((3, 1))])
    inst = []          # (label, shape as referred, world 3x4, world shape)
    root_name = ''
    for i in range(1, roots.Length() + 1):
        lab = roots.Value(i)
        if XCAFDoc_ShapeTool.IsAssembly_s(lab):
            root_name = root_name or sds2ifc._name(lab)
            comps = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(lab, comps, False)
            for j in range(1, comps.Length() + 1):
                c = comps.Value(j)
                ref = TDF_Label()
                XCAFDoc_ShapeTool.GetReferredShape_s(c, ref)
                loc = XCAFDoc_ShapeTool.GetLocation_s(c)
                S = XCAFDoc_ShapeTool.GetShape_s(ref)
                inst.append((sds2ifc._name(c) or sds2ifc._name(ref), S, sds2ifc._loc_matrix(loc), S.Moved(loc)))
        else:
            S = XCAFDoc_ShapeTool.GetShape_s(lab)
            inst.append((sds2ifc._name(lab), S, I3.copy(), S))
    salt = META['shipped_sha256']
    parts = sds2ifc._shape_map()
    seen = collections.Counter()
    base = os.path.splitext(step_path)[0]
    tmp = base + '_facts_instances.jsonl.tmp'
    n_tools = 0
    with open(tmp, 'w') as fh:
        for label, S, M, W in inst:
            S0, M0 = sds2ifc.unwrap(S, M)
            k = parts.FindIndex(S0)
            if not k:
                k = parts.Add(S0)
            occ = seen[label.strip()]
            seen[label.strip()] += 1
            gid = sds2label.guid(salt, sds2label.key(label, occ))
            R, t = M0[:, :3], M0[:, 3]
            row = dict(guid=gid, label=label, occ=occ, part=k, origin_mm=[_f(v) for v in t],
                       x=[_f(v, 9) for v in R[:, 0]], z=[_f(v, 9) for v in R[:, 2]])
            box = Bnd_Box()
            try:
                BRepBndLib.AddOptimal_s(W, box, False, False)
            except Exception:
                BRepBndLib.Add_s(W, box, False)
            if not box.IsVoid():
                lo, hi = box.CornerMin(), box.CornerMax()
                row['bbox_mm'] = [[_f(lo.X()), _f(lo.Y()), _f(lo.Z())], [_f(hi.X()), _f(hi.Y()), _f(hi.Z())]]
            else:
                row['bbox_mm'] = None
            rec = sds2ifc.recipe(S0)
            tools = []
            while rec[0] == 'cut':
                tools = rec[2] + tools
                rec = rec[1]
            if tools:
                hl = []
                for tl in tools:
                    p0 = R @ np.asarray(tl['p0']) + t
                    a = R @ np.asarray(tl['a'])
                    h = [tl['kind'], [_f(v) for v in p0], [_f(v, 9) for v in a], _f(tl['r']), _f(tl['L'])]
                    if tl['kind'] == 'slot':
                        h.append(_f(tl['s']))
                    hl.append(h)
                row['holes'] = hl
                n_tools += len(hl)
            fh.write(json.dumps(row, default=_js) + '\n')
    os.replace(tmp, base + '_facts_instances.jsonl')
    with open(base + '_facts_instances_meta.json', 'w') as f:
        json.dump(dict(instances=len(inst), unique_parts=parts.Extent(), root=root_name, hole_tools_placed=n_tools,
                       salt=salt), f, indent=1)


# ======================================================================================== convert-time facts
def _read_csv(path):
    if not os.path.exists(path):
        return None
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def _num(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def _vertices(job, sid):
    """the piece's own vertex records, as the converter's builders read them (v5 piece_vertices, else the tagged scan,
    else the mesh vertex records): (V inches piece-local, which)"""
    import instances, to_step2
    for name, fn in (('piece_vertices', getattr(instances, 'piece_vertices', None)),
                     ('subm_vertices', getattr(instances, 'subm_vertices', None)),
                     ('mesh_vertices', getattr(to_step2, 'mesh_vertices', None))):
        if fn is None:
            continue
        try:
            V = fn(job, sid)
        except Exception:
            continue
        if V is not None and len(V) >= 1:
            return np.asarray(V, float), name
    return None, None


def _hull2(P):
    """2D convex hull (Andrew's monotone chain) of points rounded to 1e-5 in, counter-clockwise, no repeated point"""
    pts = sorted({(round(float(x), 5), round(float(y), 5)) for x, y in P})
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _envelope(V):
    """the piece's own vertices (piece-local inches) -> their range along the thinnest local axis t and the convex hull
    of their coordinates on the other two axes (a, b) = ((t+1)%3, (t+2)%3), CCW in (a, b). Pure bookkeeping of the
    recorded points: facts_build decides whether another source record confirms it before it is used as geometry."""
    lo, hi = V.min(0), V.max(0)
    ext = hi - lo
    t = int(np.argmin(ext))
    a, b = (t + 1) % 3, (t + 2) % 3
    H = _hull2(V[:, [a, b]])
    area = 0.0
    for i in range(len(H)):
        (x1, y1), (x2, y2) = H[i], H[(i + 1) % len(H)]
        area += x1 * y2 - x2 * y1
    return dict(thickness_axis=t, plane_axes=[a, b], range_t_in=[_f(lo[t], 5), _f(hi[t], 5)],
                extents_in=[_f(e, 5) for e in ext], hull_points=len(H),
                hull_in=[[_f(x, 5), _f(y, 5)] for x, y in H] if len(H) <= 4096 else None,
                hull_area_in2=_f(abs(area) / 2.0, 4),
                note='convex hull of the piece\'s own vertex records on its two largest local axes (CCW in plane_axes '
                     'order) and their range along the thinnest one (thickness_axis); piece-local inches')


def _members(job):
    from sds2job import read_members
    r = read_members(job)
    mems = r[0] if isinstance(r, tuple) else r
    return list(mems)


def _shape_dims(s):
    if s is None:
        return None
    out = dict(name=getattr(s, 'name', None))
    for k in ('d', 'bf', 'tf', 'tw', 'k', 'weight'):
        v = getattr(s, k, None)
        if v is not None:
            out[k + ('_in' if k != 'weight' else '_lb_per_ft')] = _f(v, 5)
    return out


def convert_facts(job, out, ret):
    import to_step2
    from piece_table import read_pieces, kind as piece_kind
    from instances import material_instances
    from sds2job import read_shapes, read_version
    base = os.path.splitext(out)[0]
    ok, stats = (ret if isinstance(ret, tuple) and len(ret) == 2 else (None, None))
    res = dict(schema='pmp-sds2-convert-facts/1', job_version=None, ok=bool(ok) if ok is not None else None,
               stats=stats, errors=[])
    try:
        res['job_version'] = read_version(job)
    except Exception as e:
        res['errors'].append(f'read_version: {e}')
    pieces = read_pieces(job)
    try:
        shapes = read_shapes(job)
    except Exception as e:
        shapes = {}
        res['errors'].append(f'read_shapes: {e}')
    # decoded holes per piece (piece-local inches) and the holes-cut counter
    hp = {}
    for (j_, sid), H in sorted(getattr(to_step2, 'HOLES', {}).items(), key=lambda kv: str(kv[0])):
        if j_ != job or not H:
            continue
        p = pieces.get(sid, {})
        hp[str(sid)] = dict(name=p.get('name'), n=len(H),
                            dia_in=sorted({_f(h['dia'], 5) for h in H}), bolt_in=sorted({_f(h.get('bolt', 0), 5) for h in H}),
                            slots=sum(1 for h in H if h.get('slot', 0) > 0))
    res['holes_by_piece'] = hp
    res['holes_cut_counter'] = dict(getattr(to_step2, 'HOLES_CUT', {}) or {})
    # members (work lines in mm)
    mem_rows, mem_by_id = [], {}
    try:
        for m in _members(job):
            sec = getattr(m, 'section', None)
            r = dict(member=int(m.id), type=m.type, p1_mm=[_f(v * MM) for v in m.p1], p2_mm=[_f(v * MM) for v in m.p2],
                     roll=_f(getattr(m, 'roll', 0.0) or 0.0, 6), section=_shape_dims(sec))
            mem_rows.append(r)
            mem_by_id[int(m.id)] = r
    except Exception as e:
        res['errors'].append(f'read_members: {type(e).__name__}: {e}')
    res['members'] = mem_rows
    # skipped pieces with their source geometry
    sk = _read_csv(base + '_skipped.csv') or []
    inst_cache = {}
    out_rows = []
    for r in sk:
        n, sid = int(_num(r.get('member'), 0) or 0), int(_num(r.get('piece'), 0) or 0)
        row = dict(r)
        ev = dict()
        try:
            p = pieces.get(sid)
            if p is not None:
                ev['piece_table'] = dict(name=p['name'], kind=piece_kind(p), section_index=int(p['sec']),
                                         L_in=_f(p['L'], 5), W_in=_f(p['W'], 5), T_in=_f(p['T'], 5), weight_lb=_f(p['wt'], 3))
                if p['sec'] in shapes:
                    ev['section'] = _shape_dims(shapes[p['sec']])
                if piece_kind(p) == 'plate' and min(p['L'], p['W'], p['T']) > 0:
                    ev['piece_table']['LxWxT_steel_weight_lb'] = _f(p['L'] * p['W'] * p['T'] * 0.2836, 3)
            if n > 0 and sid > 0:
                if n not in inst_cache:
                    inst_cache[n] = material_instances(job, n, pieces)[1]
                o_ref = np.array([_num(r.get('ox'), np.nan), _num(r.get('oy'), np.nan), _num(r.get('oz'), np.nan)])
                cands = [(M, o) for s_, M, o in inst_cache[n] if s_ == sid]
                hit = [(M, o) for M, o in cands if np.all(np.abs(np.asarray(o) - o_ref) <= 1e-3)]
                ev['placement_candidates'] = len(cands)
                if hit:
                    M, o = hit[0]
                    M, o = np.asarray(M, float), np.asarray(o, float)
                    ev['placement'] = dict(origin_mm=[_f(v * MM) for v in o], rows_of_M=[[_f(v, 9) for v in row_] for row_ in M],
                                           note='world = origin + M.T @ local (piece-local inches)')
                    V, which = _vertices(job, sid)
                    if V is not None:
                        W = (o + V @ M) * MM
                        ev['vertices'] = dict(source=which, n=int(len(V)),
                                              local_bbox_in=[[_f(v, 5) for v in V.min(0)], [_f(v, 5) for v in V.max(0)]],
                                              world_bbox_mm=[[_f(v) for v in W.min(0)], [_f(v) for v in W.max(0)]])
                        if len(V) <= 512:
                            ev['vertices']['world_mm'] = [[_f(v, 3) for v in q] for q in W]
                        try:
                            ev['vertices']['envelope'] = _envelope(V)
                        except Exception as e:
                            ev['vertices']['envelope_error'] = f'{type(e).__name__}: {e}'
                else:
                    ev['placement'] = None
            mr = mem_by_id.get(n)
            if mr is not None:
                ev['member'] = dict(type=mr['type'], p1_mm=mr['p1_mm'], p2_mm=mr['p2_mm'], section=mr['section'])
        except Exception as e:
            ev['error'] = f'{type(e).__name__}: {e}'
        row['source_evidence'] = ev
        out_rows.append(row)
    res['skipped'] = out_rows
    tmp = base + '_facts_convert.json.tmp'
    with open(tmp, 'w') as f:
        json.dump(res, f, default=_js)
    os.replace(tmp, base + '_facts_convert.json')
