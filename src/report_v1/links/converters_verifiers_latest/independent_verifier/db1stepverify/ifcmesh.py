"""Mesh IFC elements with IfcOpenShell (world coordinates, mm): volume, volume centroid, bbox, profile name, triangles."""
import os
import numpy as np


def _profile(e):
    """ProfileName of the body extrusion, unwrapping mapped items and boolean results (Tekla cuts)."""
    try:
        for r in (e.Representation.Representations if e.Representation else []):
            for it in r.Items:
                for _ in range(20):
                    if it.is_a("IfcMappedItem"): it = it.MappingSource.MappedRepresentation.Items[0]
                    elif it.is_a("IfcBooleanResult"): it = it.FirstOperand
                    else: break
                if it.is_a("IfcSweptAreaSolid") and it.SweptArea is not None:
                    return it.SweptArea.ProfileName
    except Exception:
        pass
    return None


def mesh_ifc(path_or_file, types=None, exclude=(), threads=None, want_tris=True, max_tris=6_000_000):
    """-> list of dict(guid, type, name, profile, volume_mm3, centroid, bbox, tri_index) and a triangle soup (mm)."""
    import ifcopenshell, ifcopenshell.geom
    f = ifcopenshell.open(path_or_file) if isinstance(path_or_file, str) else path_or_file
    st = ifcopenshell.geom.settings(); st.set("use-world-coords", True)
    it = ifcopenshell.geom.iterator(st, f, threads or max(1, (os.cpu_count() or 4) - 1))
    out = []; tris = []; tri_owner = []; n = 0
    if it.initialize():
        while True:
            sh = it.get()
            if (types is None or sh.type in types) and sh.type not in exclude:
                v = np.array(sh.geometry.verts, dtype=np.float64).reshape(-1, 3) * 1000.0
                fc = np.array(sh.geometry.faces, dtype=np.int64).reshape(-1, 3)
                if len(v) and len(fc):
                    a, b, c = v[fc[:, 0]], v[fc[:, 1]], v[fc[:, 2]]
                    tv = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
                    vol = float(tv.sum())
                    cen = ((a + b + c) / 4.0 * tv[:, None]).sum(0) / vol if abs(vol) > 1e-6 else (v.min(0) + v.max(0)) / 2
                    lo, hi = v.min(0), v.max(0)
                    try: prof = _profile(f.by_guid(sh.guid))
                    except Exception: prof = None
                    out.append(dict(guid=sh.guid, type=sh.type, name=sh.name, profile=prof, volume_mm3=abs(vol),
                                    centroid=[float(x) for x in cen], bbox=[*map(float, lo), *map(float, hi)]))
                    if want_tris and n < max_tris:
                        T = np.stack([a, b, c], 1); tris.append(T); tri_owner.append(np.full(len(T), len(out) - 1)); n += len(T)
            if not it.next(): break
    T = np.concatenate(tris) if tris else np.zeros((0, 3, 3)); O = np.concatenate(tri_owner) if tri_owner else np.zeros(0, int)
    return out, T, O


def _mesh_child(args):
    path, exclude = args
    return mesh_ifc(path, exclude=set(exclude))


def mesh_ifc_timeout(path, exclude=(), timeout=900):
    """mesh_ifc in a child process: IfcOpenShell can loop forever on some boolean cuts (seen on 0.8.5 with hollow
    sections). -> (elements, tris, owners) or raises TimeoutError; the child is killed on timeout."""
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor, TimeoutError as FTE
    ex = ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"))
    fut = ex.submit(_mesh_child, (path, tuple(sorted(exclude))))
    try:
        return fut.result(timeout=timeout)
    except FTE:
        for p in list(getattr(ex, "_processes", {}).values()):
            p.kill()
        raise TimeoutError(f"meshing {os.path.basename(path)} exceeded {timeout} s")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def ifc_head(path_or_bytes):
    """Header facts of an IFC: schema, originating system (Tekla?), exporter."""
    import re
    h = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, "rb").read(4000)
    t = h.decode("latin-1")
    sc = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", t)
    return dict(schema=sc.group(1) if sc else None, tekla="Tekla Structures" in t, grid_export="GridExporter" in t,
                header=" ".join(t[t.find("HEADER;"):t.find("ENDSEC;")].split())[:400])
