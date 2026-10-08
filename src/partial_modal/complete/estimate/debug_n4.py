"""debug: why the closed n4 plates are BRepCheck-invalid (Modal, app pmp-estimate-dbg)"""
import json, pathlib, modal
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
img = (modal.Image.debian_slim(python_version='3.11')
       .apt_install('libgl1', 'libxrender1', 'libxext6', 'libsm6', 'libfontconfig1', 'libxkbcommon0', 'libxi6')
       .pip_install_from_requirements(str(ROOT / 'code' / 'requirements.txt'))
       .add_local_file(str(ROOT / 'testB_results' / 'n4' / 'scripts' / 'steelbuild.py'), '/d/steelbuild.py')
       .add_local_file(str(HERE / 'out' / 'n4_ifc_c2s' / 'patch.json'), '/d/patch.json'))
app = modal.App('pmp-estimate-dbg', image=img)

@app.function(cpu=2.0, memory=8192, timeout=1200)
def dbg():
    import sys; sys.path.insert(0, '/d')
    import steelbuild as sb
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    p = json.load(open('/d/patch.json'))
    o = p['ops'][0]
    faces = o['geometry']['solids'][0]['faces']
    out = {}
    sol = sb.exact_part({'solids': [{'faces': faces}]})[0]
    base = sol.wrapped.Located(TopLoc_Location())
    out['valid'] = BRepCheck_Analyzer(base).IsValid()
    for kind, nm in ((TopAbs_FACE, 'face'), (TopAbs_EDGE, 'edge')):
        ex = TopExp_Explorer(base, kind); n = 0; nb = []
        while ex.More():
            if not BRepCheck_Analyzer(ex.Current()).IsValid(): nb.append(n)
            n += 1; ex.Next()
        out[nm] = [n, nb[:20], len(nb)]
    # merged side faces: big polygon + its loop as one polygon
    import collections
    key = lambda q: (round(q[0], 2), round(q[1], 2), round(q[2], 2))
    big = [i for i, fc in enumerate(faces) if len(fc[0]) >= 1000]
    loops = faces[-2:]
    merged = []
    for bi in big:
        P = faces[bi][0]
        for lp in loops:
            L = lp[0]
            ks = {key(q) for q in L}
            if key(P[0]) in ks and key(P[-1]) in ks:
                # walk the loop from P[-1] to P[0] not through the chord
                idx = {key(q): j for j, q in enumerate(L)}
                a, b = idx[key(P[-1])], idx[key(P[0])]
                n = len(L)
                fw = [(a + k) % n for k in range(n)]
                path1 = fw[:fw.index(b) + 1]
                bw = [(a - k) % n for k in range(n)]
                path2 = bw[:bw.index(b) + 1]
                path = path1 if len(path1) > len(path2) else path2
                merged.append((bi, P + [L[j] for j in path[1:-1]]))
    out['merged'] = [(bi, len(m)) for bi, m in merged]
    nf = [fc for i, fc in enumerate(faces[:-2]) if i not in big] + [[m] for _, m in merged]
    sol2 = sb.exact_part({'solids': [{'faces': nf}]})[0]
    b2 = sol2.wrapped.Located(TopLoc_Location())
    out['merged_valid'] = BRepCheck_Analyzer(b2).IsValid()
    out['merged_defects'] = sb.solid_defects(sol2)
    out['merged_volume'] = sb._volume(sol2.wrapped)
    for i, (bi, m) in enumerate(merged):
        out[f'merged_face_{i}_valid'] = BRepCheck_Analyzer(sb._planar_face([m])).IsValid()
    # each face alone
    badf = []
    for i, fc in enumerate(faces):
        f = sb._planar_face(fc)
        if not BRepCheck_Analyzer(f).IsValid():
            badf.append((i, len(fc[0])))
    out['bad_single_faces'] = badf
    out['volume'] = sb._volume(sol.wrapped)
    # original (open) for comparison
    return out

@app.local_entrypoint()
def main():
    print(json.dumps(dbg.remote(), indent=1))
