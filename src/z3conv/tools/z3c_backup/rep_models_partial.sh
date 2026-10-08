#!/bin/bash
# Report models: for the chosen class-1 STEP models (indices into /opt/report/assets/cands.json) -> GLB (OCC RWGltf_CafWriter, binary glTF)
# + a 2000x1500 still (matplotlib, same camera / scale / background for every model). Reads the SHIPPED STEP object from each package.
# READ-ONLY on S3. Output /opt/report/assets/models/. Idempotent: first call starts unit z3repmodels; later calls print progress.
export AWS_DEFAULT_REGION=ap-south-1; FORCE=${FORCE:-}
D=/opt/report; O=$D/assets/pmodels; mkdir -p $O $D/work/pmodels; [ -n "$FORCE" ] && { systemctl stop z3repmodelsp 2>/dev/null; rm -f $O/finished $O/*.glb $O/*.png $O/models.json; }
if systemctl is-active -q z3repmodelsp; then echo running; tail -n 5 $O/log.txt; exit 0; fi
if [ -f $O/finished ] && [ -z "$FORCE" ]; then echo "finished $(cat $O/finished)"; tail -n 12 $O/log.txt; ls -la $O | tail -20; exit 0; fi
echo H4sIAMIzxWoC/7WV247iRhCG7+cpWnMRbaQ12+fDpTFkYcJhhE1WyWrVavdhh8RgZMxmlKdPGyYzwJBkLhLJsoru6irq67/Kn2/A5xsAbp1pTUJv33f2Ktij8YvftKt273xy3Na6GP44SZPRzwN9N+/nCYaIdS+uEezFh8IeQzr3zTff6L6xv+23Oh/kOCmG6bSzkvvF/G6YFfn5DwQZaGuAYgjxxzH3una++rBr/fbDKF0sxrleDPMiXS7SWdEl73VbB1ckFUESo87e7KvqcJxhARXipLQcO04hLTFjpVcYKUIwDcEHHpRyzlgqBKUc8uC8IdEDltG+PYv24Jv6+Ldsvd5WvvW6rfWu3jfW396AL+9PKZKj587t8DPGE4pE6+wpiNP3Tf2rt+1OD+KWhhTFvch8E8GbCuSt95WOfPHr5Wug+vtV5Vabr/pODx+3vQ5TImUIVpzQEgRBSOhZfc5aZSgR3BGOPWXxjISGkXMKLTpmNNttUz+u1iZW8Kr6Jw25Ev27ho4KARhirnMwaFbfPHhSTTbNQFqZdR2rbfa23TfPPAhOMIOQg3SZg7RtVvs1GG/Cqqo0ukbl7/1B2p++kOHx6pkQZyV7aHDJOS2t85ZKLD0PJRUxmvAcQamiZCEnTGBSKoUEsoaVLgQouAxUXsioxW8ASF434RvVQ6jO58tiBLLhrFikE5AXw+FETwtEorQUeAdm/nfwyceKmw0YeVO1DyCL9+MbcJcNRt9fo/dTvXLJ7NMoO2+6DpVSAp/VpzALjDJmsZPUBekwt6I0ZVk6HqB3FlEYEHH+0H3QYc8Z9x4bLhVDFF3QIm+X2387so5HDjPrxUklg7RI9TJP9fPciipN0kk6nWvKeqDwj2YHJlHF10DGESUQTWDMr188wahuo6bHP2QnbLmkFBJ2RoOj4FAZJDUcGuFKhyQUOF4rZFF/ylnMkMKxty0njstuKS5yaiJuYq28YEv/VyVCpT/61deoq+/AfXRodp0KpUZEgHeIR1L2ASTgr3kF5ht/VXyd6zAbgf5yPBmMZx/BfDY8TDWH4iDnJ8hi4wp8IccAUQmtc0FIbg2BCDFMDbSEGElLo6gJwjDhQomDEMogx7AKEbwIVHjsLpCxf/oC3Hz5Ezc3nJFKBwAA | base64 -d | gunzip > $D/assets/cands_partial.json
cat > $D/rep_models_p.py <<'PYEOF'
import os, sys, json, time, math
import numpy as np, boto3
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.TCollection import TCollection_ExtendedString, TCollection_AsciiString
from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
from OCC.Core.TDF import TDF_LabelSequence
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.RWGltf import RWGltf_CafWriter
from OCC.Core.TColStd import TColStd_IndexedDataMapOfStringString
from OCC.Core.Message import Message_ProgressRange
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.BRep import BRep_Tool
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopoDS import topods
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d_partial/'
O = '/opt/report/assets/pmodels'; W = '/opt/report/work/pmodels'
C = json.load(open('/opt/report/assets/cands_partial.json'))
pick = [int(x) for x in sys.argv[1].split(',')]
def log(*a): print(time.strftime('%H:%M:%S'), *a, flush=True)
def triangles(shape):
    tris = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = topods.Face(ex.Current()); loc = TopLoc_Location()
        t = BRep_Tool.Triangulation(f, loc)
        if t is not None:
            tr = loc.Transformation()
            n = t.NbNodes(); pts = np.array([[t.Node(i).Transformed(tr).X(), t.Node(i).Transformed(tr).Y(), t.Node(i).Transformed(tr).Z()] for i in range(1, n + 1)])
            for i in range(1, t.NbTriangles() + 1):
                a, b, c = t.Triangle(i).Get(); tris.append(pts[[a - 1, b - 1, c - 1]])
        ex.Next()
    return np.array(tris)
def render(tris, out, w=2000, h=1500):
    if len(tris) > 600000:                     # keep the still tractable: every k-th triangle of the densest models (outline preserved)
        tris = tris[::int(math.ceil(len(tris) / 600000))]
    c = tris.reshape(-1, 3); lo, hi = c.min(0), c.max(0); ctr = (lo + hi) / 2; span = (hi - lo).max()
    t = (tris - ctr) / span
    # isometric camera (same for every model)
    az, el = math.radians(-50), math.radians(30)
    R = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    E = np.array([[1, 0, 0], [0, math.cos(el), -math.sin(el)], [0, math.sin(el), math.cos(el)]])
    v = t @ R.T @ E.T
    nrm = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]); nn = np.linalg.norm(nrm, axis=1, keepdims=True); nn[nn == 0] = 1; nrm /= nn
    light = np.array([0.35, 0.55, 0.75]); light /= np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.abs(nrm @ light)
    order = np.argsort(v[:, :, 1].mean(1))[::-1]          # painter's algorithm: far (larger y after rotation) first
    base = np.array([0.31, 0.47, 0.73])
    cols = np.clip(base[None, :] * shade[:, None] + 0.08, 0, 1)
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100); ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor('#0f1623'); fig.patch.set_facecolor('#0f1623')
    from matplotlib.collections import PolyCollection
    pc = PolyCollection(v[order][:, :, [0, 2]], facecolors=cols[order], edgecolors=cols[order], linewidths=0.15, antialiased=True)
    ax.add_collection(pc); xs = v[:, :, 0]; zs = v[:, :, 2]
    pad = 0.06; xr = (xs.min(), xs.max()); zr = (zs.min(), zs.max()); s = max(xr[1] - xr[0], (zr[1] - zr[0]) * w / h) * (1 + pad)
    cx, cz = sum(xr) / 2, sum(zr) / 2
    ax.set_xlim(cx - s / 2, cx + s / 2); ax.set_ylim(cz - s / 2 * h / w, cz + s / 2 * h / w); ax.axis('off')
    fig.savefig(out, dpi=100, facecolor=fig.get_facecolor()); plt.close(fig)
def write_glb(tris, out):
    """compact binary glTF: one mesh, shared vertices (deduplicated at 0.1 mm), uint32 indices, metres, Y-up; flat-shaded in the viewer"""
    import struct
    v = tris.reshape(-1, 3).astype(np.float64)
    ctr = (v.min(0) + v.max(0)) / 2; v = (v - ctr) / 1000.0
    q = np.round(v * 1e4).astype(np.int64)
    uq, inv = np.unique(q, axis=0, return_inverse=True)
    pos = (uq / 1e4).astype(np.float32); pos = np.stack([pos[:, 0], pos[:, 2], -pos[:, 1]], 1).astype(np.float32)
    idx = inv.reshape(-1).astype(np.uint32)
    binb = pos.tobytes() + idx.tobytes(); binb += b'\0' * ((4 - len(binb) % 4) % 4)
    g = {'asset': {'version': '2.0', 'generator': 'cad-report STEP->glb (faceted, exact vertices)'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
         'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1, 'material': 0}]}],
         'materials': [{'pbrMetallicRoughness': {'baseColorFactor': [0.45, 0.6, 0.85, 1], 'metallicFactor': 0.25, 'roughnessFactor': 0.6}, 'doubleSided': True}],
         'buffers': [{'byteLength': len(binb)}],
         'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': pos.nbytes, 'target': 34962},
                         {'buffer': 0, 'byteOffset': pos.nbytes, 'byteLength': idx.nbytes, 'target': 34963}],
         'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': int(len(pos)), 'type': 'VEC3', 'min': pos.min(0).tolist(), 'max': pos.max(0).tolist()},
                       {'bufferView': 1, 'componentType': 5125, 'count': int(len(idx)), 'type': 'SCALAR'}]}
    js = json.dumps(g, separators=(',', ':')).encode(); js += b' ' * ((4 - len(js) % 4) % 4)
    with open(out, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(binb)))
        f.write(struct.pack('<II', len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack('<II', len(binb), 0x004E4942)); f.write(binb)
    np.save(out[:-4] + '_tris.npy', tris.astype(np.float32))
res = []
for i in pick:
    disk, src, pid, relpath, nbytes, rkey, mid, parts = C[i][:8]
    tag = C[i][8]; kind = C[i][9]; key = f'{PK}{pid}/{relpath}'; loc = f'{W}/{tag}.step'
    log('model', i, pid[:70], relpath, nbytes)
    s3.download_file(B, key, loc)
    doc = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    rd = STEPCAFControl_Reader(); rd.SetNameMode(True); rd.ReadFile(loc); rd.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool(doc.Main()); labs = TDF_LabelSequence(); st.GetFreeShapes(labs)
    shapes = [st.GetShape(labs.Value(k)) for k in range(1, labs.Length() + 1)]
    for sh in shapes: BRepMesh_IncrementalMesh(sh, 2.0, False, 0.5, True)
    glb = f'{O}/{tag}.glb'
    tris = np.concatenate([triangles(sh) for sh in shapes]) if shapes else np.zeros((0, 3, 3))
    write_glb(tris, glb)
    render(tris, f'{O}/{tag}.png')
    bb = tris.reshape(-1, 3); ext = (bb.max(0) - bb.min(0)).tolist() if len(bb) else None
    res.append({'idx': i, 'tag': tag, 'kind': kind, 'disk': disk, 'source': src, 'project_id': pid, 'relpath': relpath, 'step_bytes': nbytes, 'model_id': mid,
                'parts': parts, 'triangles': int(len(tris)), 'glb_bytes': os.path.getsize(glb), 'extent_mm': ext})
    log('done', tag, 'tris', len(tris), 'glb MB', round(os.path.getsize(glb) / 1e6, 1)); os.remove(loc)
    json.dump(res, open(f'{O}/models.json', 'w'), indent=1)
PYEOF
date -u +%FT%TZ > $O/started
systemctl reset-failed z3repmodelsp 2>/dev/null
systemd-run --unit=z3repmodelsp --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/report/venv/bin/python $D/rep_models_p.py 0,1,2,3,4,5 > $O/log.txt 2>&1; echo rc=\$? >> $O/log.txt; date -u +%FT%TZ > $O/finished"
sleep 30; echo "started: $(systemctl is-active z3repmodelsp)"; tail -n 3 $O/log.txt
