#!/usr/bin/env python3
"""Delivered STEP reader for models converted from SDS/2 by our converter (sds2-step-pipeline: an OpenCASCADE AP214 STEP,
each unique piece written once as a part and placed per instance as an assembly component named by the instance label,
or written as a placed copy named by it; solids are exact B-reps - faceted pieces with true cylindrical bolt holes,
cylindrical rods and studs - not the faceted ifc2step output stepfacets.py reads).

Every instance becomes one delivered part. Its id is the GlobalId the IFC emitter gave the same instance
(sds2label.guid: sha256 of this STEP file + the instance label, '<member type> #<member> / <piece> (piece <id>, inst
<n>)', with the k-th repeat of a label in document order suffixed), so the delivered part and the IFC product of one
instance carry the same id. Volume, centre and bounding box are measured on the B-rep solids with OpenCASCADE, solid by
solid and summed (verify._props: the measures the rebuild is held to), never on a faceted approximation.

SDS/2 mode is decided by the schedule folder (sds2_mode: extract_info.json names the emitter as the IFC's
originating system); models whose IFC came from anywhere else never reach this module.

usage: occstep.py DELIVERED.step     (prints the first parts and the count)"""
import collections, hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sds2label  # noqa: E402

EMITTER = 'z3-sds2-ifc-emitter'


def sds2_mode(folder):
    """True when the schedule folder was extracted from an IFC our SDS/2 IFC emitter wrote"""
    if not folder:
        return False
    try:
        info = json.load(open(os.path.join(folder, 'extract_info.json')))
    except Exception:
        return False
    return str(info.get('originating_system', '')).startswith(EMITTER)


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def instances(path):
    """[(label, placed shape)] of every top-level instance, in document order"""
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.TDF import TDF_Label
    from OCP.TDataStd import TDataStd_Name
    from OCP.IFSelect import IFSelect_RetDone
    try:
        from OCP.TDF import TDF_LabelSequence
    except ImportError:
        from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    doc = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    rd = STEPCAFControl_Reader()
    rd.SetNameMode(True)
    if rd.ReadFile(path) != IFSelect_RetDone:
        raise ValueError('cannot read ' + path)
    rd.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    def nm(lab):
        a = TDataStd_Name()
        return a.Get().ToExtString() if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else ''
    out = []
    roots = TDF_LabelSequence()
    st.GetFreeShapes(roots)
    for i in range(1, roots.Length() + 1):
        lab = roots.Value(i)
        if XCAFDoc_ShapeTool.IsAssembly_s(lab):
            comps = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(lab, comps, False)
            for j in range(1, comps.Length() + 1):
                c = comps.Value(j)
                ref = TDF_Label()
                XCAFDoc_ShapeTool.GetReferredShape_s(c, ref)
                out.append((nm(c) or nm(ref), XCAFDoc_ShapeTool.GetShape_s(ref).Moved(XCAFDoc_ShapeTool.GetLocation_s(c))))
        else:
            out.append((nm(lab), XCAFDoc_ShapeTool.GetShape_s(lab)))
    return out


def _solids(shape):
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID
    from build123d import Solid
    out = []
    ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        out.append(Solid(ex.Current()))
        ex.Next()
    return out


def products(path):
    """{GlobalId: {'name': instance label, 'solids': [build123d Solid]}}"""
    salt = file_sha256(path)
    seen = collections.Counter()
    out = {}
    for label, shp in instances(path):
        k = seen[label.strip()]
        seen[label.strip()] += 1
        out[sds2label.guid(salt, sds2label.key(label, k))] = {'name': label, 'description': '', 'solids': _solids(shp)}
    return out


def delivered_props(path):
    """{GlobalId: {'v', 'c', 'lo', 'hi', 'name'}} (mm), as verify.delivered_props returns for a faceted delivered STEP"""
    import verify
    out = {}
    for pid, d in products(path).items():
        if not d['solids']:
            continue
        v, c, lo, hi = verify._props(d['solids'])
        out[pid] = {'v': float(v), 'c': [float(x) for x in c], 'lo': [float(x) for x in lo], 'hi': [float(x) for x in hi],
                    'name': d['name']}
    return out


if __name__ == '__main__':
    P = delivered_props(sys.argv[1])
    for pid, d in list(P.items())[:5]:
        print(pid, d['name'][:60], round(d['v'], 1), [round(x, 2) for x in d['c']])
    print(len(P), 'parts')
