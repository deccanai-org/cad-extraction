"""v2 (eng): naming-independent evidence that the part -> attribute link is right.
A wrong link hands each part another object's attribute record. Two consequences can be checked without
relying on how the detailer named parts:
  * contour plates: a part named PL<t>/BL<t> must own an outline record (found through the PART's own
    outline link, which does not pass through the attribute record) whose extent equals the part length;
  * cut parts: a part whose attribute record says ANTIMATERIAL must be the child of a cut relation.
Used to overrule the COLUMN-name heuristic (railing / stair models name horizontal rails 'COLUMN': the Tekla
IFC of model 80bd353ac7 shows 54 of 68 COLUMN-named parts horizontal)."""
import numpy as np
from db1dec import PLATE1_RE


def evidence(db, lay, M):
    cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
    po = sum(1 for m in cp[:2000] if db.outline_points(lay, m)) if lay.get('poly_stride') else 0
    cut = [m for m in M if m['cut']]
    child = set()
    cl = getattr(db, 'cut_layout', None)
    for s, recs in db.runs:
        if cl and s != cl['stride']: continue
        if not cl and s != 69: continue
        child |= set(int(x) for x in db.I(recs + (cl['cut'] if cl else 21)))
    cr = sum(1 for m in cut if m['seq'] in child)
    return dict(plates_named=min(len(cp), 2000), plates_with_outline=po, cut_parts=len(cut), cut_parts_in_relations=cr)


def confirmed(ev):
    """True when either check is decisive (>= 10 samples, >= 90 %)"""
    a = ev['plates_named'] >= 10 and ev['plates_with_outline'] >= 0.9 * ev['plates_named']
    b = ev['cut_parts'] >= 10 and ev['cut_parts_in_relations'] >= 0.9 * ev['cut_parts']
    return bool(a or b)
