"""Write a de-duplicated copy of a converted STEP: drop the exact repeats the converter wrote (the same physical piece
listed under two members; v4 notes: open issue). The original file is never modified.

Which solids go is decided by the verifier's G4 check: identical volume and bounding box (0.01 in) written more than
once, excluding repeats that already exist in the SDS2 job itself (twin members, kept as-is). The first copy of each
group (lowest member id) is kept, so the kept owner is a convention, not a fact: the geometry is exact, the member
link of a kept shared piece may be the other member of the connection.

Output: <out_dir>/<name>.step, the copy without the repeats, and <out_dir>/<name>_dedup.csv listing every removed
solid (name, member, piece, entry). Each removal is checked against the instance name recorded by the verifier, so a
label mismatch aborts instead of removing the wrong solid.

usage (normally called by verify.py --dedup-out DIR):  python dedup.py <step> <removals.json> <out_dir>
"""
import os, sys, csv, json


def write_clean(step, removals, out_dir):
    """removals: rows of the verifier's solid table (need 'entry' and 'name'). Returns (out_step, removed count)."""
    from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.TDF import TDF_Label, TDF_Tool
    from OCP.TDataStd import TDataStd_Name
    from OCP.Interface import Interface_Static
    from OCP.IFSelect import IFSelect_RetDone

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(step))[0]
    out = os.path.join(out_dir, base + ".step")
    if os.path.abspath(out) == os.path.abspath(step):
        raise SystemExit("refusing to overwrite the original STEP: choose another --dedup-out folder")
    r = STEPCAFControl_Reader(); r.SetNameMode(True)
    if r.ReadFile(step) != IFSelect_RetDone:
        raise RuntimeError(f"STEP read failed: {step}")
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    r.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    def name_of(lab):
        a = TDataStd_Name()
        return a.Get().ToExtString() if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else ""

    labels = []
    for t in removals:
        lab = TDF_Label()
        TDF_Tool.Label_s(doc.Main().Data(), TCollection_AsciiString(t["entry"]), lab, False)
        if lab.IsNull():
            raise RuntimeError(f"entry {t['entry']} not found in {step}")
        nm = name_of(lab)
        if nm != t["name"]:
            # components carry the instance name; free shapes their own. Anything else: stop, don't guess
            ref = TDF_Label()
            if not (XCAFDoc_ShapeTool.GetReferredShape_s(lab, ref) and name_of(ref) == t["name"]):
                raise RuntimeError(f"entry {t['entry']}: label says {nm!r}, verifier recorded {t['name']!r}")
        labels.append(lab)
    from OCP.OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    parts = []
    for lab in labels:
        if XCAFDoc_ShapeTool.IsComponent_s(lab):
            ref = TDF_Label()
            if XCAFDoc_ShapeTool.GetReferredShape_s(lab, ref): parts.append(ref)
            st.RemoveComponent(lab)
        else:
            st.RemoveShape(lab, True)
    # a shared part whose last placement was removed would otherwise be written as a loose solid at the origin
    for ref in parts:
        users = TDF_LabelSequence()
        if XCAFDoc_ShapeTool.GetUsers_s(ref, users, False) == 0:
            st.RemoveShape(ref, False)
    st.UpdateAssemblies()
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPCAFControl_Writer(); w.SetNameMode(True)
    w.Transfer(doc, STEPControl_AsIs)
    if w.Write(out) != IFSelect_RetDone:
        raise RuntimeError(f"STEP write failed: {out}")
    with open(os.path.join(out_dir, base + "_dedup.csv"), "w", newline="", encoding="utf-8") as f:
        cw = csv.DictWriter(f, fieldnames=["name", "member", "piece", "entry"]); cw.writeheader()
        cw.writerows(dict(name=t["name"], member=t.get("member_id"), piece=t.get("piece_id"), entry=t["entry"]) for t in removals)
    return out, len(labels)


if __name__ == "__main__":
    step, rem, out_dir = sys.argv[1:4]
    o, n = write_clean(step, json.load(open(rem)), out_dir)
    print(f"removed {n} duplicate solids -> {o}")
