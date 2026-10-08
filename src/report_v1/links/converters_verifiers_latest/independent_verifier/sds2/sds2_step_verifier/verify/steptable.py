"""Read a converted STEP file into a 'solid table' (one row per placed solid), cached as JSON next to the STEP.

Row fields (lengths in INCHES, job coordinates, so they compare directly with decoded SDS2 data):
  name, stage ('member' | 'piece' | 'bolt'), member_id, piece_id, tags, valid, closed, volume (in^3), faces,
  lo[3], hi[3] (axis-aligned bbox), center[3], obb[3] (oriented-bbox full sizes, sorted desc),
  in_assembly (True = an assembly component: the production converter writes exact pieces once and places them
  per instance; approximate pieces, studs, rods and concrete are written as standalone solids)
Assemblies are walked recursively and every component is placed by its accumulated location, so a shared part
used 40 times gives 40 rows. The STEP length unit is read from the file header and converted, so a wrong unit
shows up as a scale error rather than being silently absorbed.
"""
import os, re, json, time

MM_PER_IN = 25.4
READER = 3              # cache format; reader 1 saw only top-level shapes of assembly files; 3 adds 'entry'
# stage 1; the converter may append part tags in parentheses, e.g. "JOIST 24K4 #12 (joist_envelope)"
NAME_MEMBER = re.compile(r"^(?P<type>.+?) (?P<section>\S+) #(?P<mid>\d+)(?: \((?P<tags>[^()]*)\))?$")
# stage 2; the converter may append ", inst <k>", ", member envelope" and other tags inside the parentheses.
# The member type can be empty (members whose type the decoder could not read: "#1 / RB5/8 (piece 1)").
# v4 converter: a main material it could only build from the member writes the piece label + " member envelope"
NAME_PIECE = re.compile(r"^\s*(?:(?P<type>.+?) )?#(?P<mid>\d+) / (?P<pname>.+) \(piece (?P<pid>\d+)(?:, inst (?P<inst>\d+))?(?P<tags>(?:, [^,()]+)*)\)(?P<env> member envelope)?$")
# stage 2: a member with no fabricated pieces (joists) written as its stage-1 solid
NAME_ENVELOPE = re.compile(r"^\s*(?:(?P<type>.+?) )?#(?P<mid>\d+) / (?P<pname>.+) \(member envelope\)$")
# stage 2 bolts: from SDS2's own bolt records, or nominal heavy hex through hole stacks no record covers (guessed);
# v4 appends " (inst N)"
NAME_BOLT = re.compile(r"^BOLT (?:(?P<btype>\S+) )?(?P<d>[\d.]+) x (?P<L>[\d.]+) \(grip (?P<g>[\d.]+)\)(?: \(inst \d+\))?$")
NAME_BOLT_NOMINAL = re.compile(r"^BOLT (?P<d>[\d.]+) x (?P<g>[\d.]+) grip \(nominal heavy hex\)(?: \(inst \d+\))?$")


def _tags(s):
    """', approx, joist_envelope' or 'approx, bolt_guessed' -> ['approx', 'joist_envelope']; first word of each tag
    ('member envelope' -> 'member_envelope')."""
    s = (s or "").replace("member envelope", "member_envelope")
    return [t.split()[0] for t in s.split(",") if t.strip()]


def parse_name(name):
    m = NAME_BOLT.match(name) or NAME_BOLT_NOMINAL.match(name)
    if m:
        guessed = m.re is NAME_BOLT_NOMINAL
        return dict(stage="bolt", member_type="BOLT", member_id=None, piece_id=None, section=f"BOLT {m['d']}",
                    approx=False, tags=["bolt_guessed"] if guessed else [])
    m = NAME_ENVELOPE.match(name)
    if m:
        return dict(stage="piece", member_type=m["type"] or "", member_id=int(m["mid"]), piece_id=0, section=m["pname"],
                    inst=None, approx=False, tags=["member_envelope"])
    m = NAME_PIECE.match(name)
    if m:
        tags = _tags(m["tags"]) + (["member_envelope"] if m["env"] else [])
        return dict(stage="piece", member_type=m["type"] or "", member_id=int(m["mid"]), piece_id=int(m["pid"]), section=m["pname"],
                    inst=int(m["inst"]) if m["inst"] else None, approx="approx" in tags, tags=tags)
    m = NAME_MEMBER.match(name)
    if m:
        tags = _tags(m["tags"])
        return dict(stage="member", member_type=m["type"], member_id=int(m["mid"]), piece_id=None, section=m["section"],
                    approx="approx" in tags, tags=tags)
    return dict(stage="unknown", member_type="", member_id=None, piece_id=None, section="", tags=[])


def _step_unit_scale(path):
    """Return inches-per-file-unit from the STEP header's length unit (SI_UNIT with optional prefix)."""
    with open(path, "rb") as f:
        head = f.read(4_000_000).decode("latin-1", "replace")
    m = re.search(r"SI_UNIT\(\s*(\.[A-Z]+\.|\$)\s*,\s*\.METRE\.\s*\)", head)
    prefix = m.group(1) if m else ".MILLI."
    per_m = {".MILLI.": 1e-3, ".CENTI.": 1e-2, ".DECI.": 1e-1, "$": 1.0}.get(prefix, 1e-3)
    if re.search(r"CONVERSION_BASED_UNIT\(\s*'INCH'", head):
        return 1.0, "INCH"
    return per_m / 0.0254, {".MILLI.": "MM", "$": "M"}.get(prefix, prefix)


def read_step(path, use_cache=True):
    cache = path + ".table.json"
    if use_cache and os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(path):
        tab = json.load(open(cache))
        if tab.get("reader") == READER:
            return tab
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    from OCP.TDF import TDF_Label, TDF_Tool
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TopLoc import TopLoc_Location
    from OCP.TDataStd import TDataStd_Name
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box, Bnd_OBB
    from OCP.BRepBndLib import BRepBndLib
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_FACE, TopAbs_SOLID
    from OCP.BRep import BRep_Tool

    t0 = time.time()
    scale, unit = _step_unit_scale(path)          # inches per file unit
    r = STEPCAFControl_Reader(); r.SetNameMode(True)
    if r.ReadFile(path) != IFSelect_RetDone:
        raise RuntimeError(f"STEP read failed: {path}")
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    r.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    # OCCT scales geometry to its session unit (mm) on read; the header unit is recorded for the unit check
    s_in = 1.0 / MM_PER_IN

    def name_of(lab):
        attr = TDataStd_Name()
        return attr.Get().ToExtString() if lab.FindAttribute(TDataStd_Name.GetID_s(), attr) else ""

    part_props = {}                               # placement-invariant properties, computed once per part

    def props_of(key, shape):
        if key not in part_props:
            g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g)
            obb = Bnd_OBB(); BRepBndLib.AddOBB_s(shape, obb, True, True, False)
            closed = True; nsh = 0
            ex = TopExp_Explorer(shape, TopAbs_SHELL)
            while ex.More():
                nsh += 1
                if not BRep_Tool.IsClosed_s(ex.Current()): closed = False
                ex.Next()
            nf = 0; ex = TopExp_Explorer(shape, TopAbs_FACE)
            while ex.More(): nf += 1; ex.Next()
            nsol = 0; ex = TopExp_Explorer(shape, TopAbs_SOLID)
            while ex.More(): nsol += 1; ex.Next()
            part_props[key] = dict(valid=bool(BRepCheck_Analyzer(shape).IsValid()), closed=closed and nsh > 0, solids=nsol,
                                   volume=g.Mass() * s_in ** 3, faces=nf,
                                   obb=sorted([2 * obb.XHSize() * s_in, 2 * obb.YHSize() * s_in, 2 * obb.ZHSize() * s_in], reverse=True))
        return part_props[key]

    rows = []

    def entry_of(lab):
        e = TCollection_AsciiString(); TDF_Tool.Entry_s(lab, e)                  # unique label id, e.g. "0:1:1:7"
        return e.ToCString()

    def emit(lab, loc, name, in_asm, own):
        """lab: the shape (part) label; own: the label of this placement (the component, or the free shape itself),
        recorded as 'entry' so a later step (dedup.py) can remove exactly this instance."""
        base = XCAFDoc_ShapeTool.GetShape_s(lab)
        shape = base.Moved(loc) if in_asm else base
        box = Bnd_Box(); BRepBndLib.Add_s(shape, box)
        pmin, pmax = box.CornerMin(), box.CornerMax()
        row = dict(name=name, **parse_name(name), **props_of(entry_of(lab), base),
                   lo=[pmin.X() * s_in, pmin.Y() * s_in, pmin.Z() * s_in], hi=[pmax.X() * s_in, pmax.Y() * s_in, pmax.Z() * s_in],
                   in_assembly=in_asm, entry=entry_of(own))
        row["center"] = [(a + b) / 2 for a, b in zip(row["lo"], row["hi"])]
        rows.append(row)

    def walk(lab, loc):
        comps = TDF_LabelSequence(); XCAFDoc_ShapeTool.GetComponents_s(lab, comps, False)
        for i in range(1, comps.Length() + 1):
            c = comps.Value(i)
            ref = TDF_Label()
            if not XCAFDoc_ShapeTool.GetReferredShape_s(c, ref):
                continue
            cloc = loc.Multiplied(XCAFDoc_ShapeTool.GetLocation_s(c))
            if XCAFDoc_ShapeTool.IsAssembly_s(ref):
                walk(ref, cloc)
            else:
                emit(ref, cloc, name_of(c) or name_of(ref), True, c)   # the component carries the instance name

    labels = TDF_LabelSequence(); st.GetFreeShapes(labels)
    for i in range(1, labels.Length() + 1):
        lab = labels.Value(i)
        if XCAFDoc_ShapeTool.IsAssembly_s(lab):
            walk(lab, TopLoc_Location())
        else:
            emit(lab, TopLoc_Location(), name_of(lab), False, lab)
    out = dict(path=path, unit=unit, inches_per_unit=scale, solids=rows, reader=READER, read_seconds=round(time.time() - t0, 1))
    if use_cache:
        json.dump(out, open(cache, "w"))
    return out


