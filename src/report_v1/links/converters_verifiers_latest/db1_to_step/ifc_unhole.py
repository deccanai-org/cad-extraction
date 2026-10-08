"""ifc_unhole.py IN.ifc OUT.ifc GUID [GUID ...]  - crash-bisect fallback for bolt holes.
For each culprit element: drop only its bolt-hole subtractions (IfcBooleanResult DIFFERENCE whose second operand is an
extrusion of a profile named BOLT_HOLE_*), keeping the part and its Tekla part cuts. Prints one JSON line
{"unholed": {guid: holes_removed}, "untouched": [guids without bolt holes]} so the worker can tag the holes left uncut
and fall back to ifc_exclude.py only for elements that still crash."""
import sys, json, ifcopenshell

def is_hole(op):
    return op is not None and op.is_a('IfcExtrudedAreaSolid') and (getattr(op.SweptArea, 'ProfileName', None) or '').startswith('BOLT_HOLE')

def strip(item, n):
    """-> (new item, holes removed)"""
    if item.is_a('IfcBooleanResult') and item.Operator == 'DIFFERENCE':
        first, k = strip(item.FirstOperand, 0)
        if is_hole(item.SecondOperand):
            return first, n + k + 1
        if first is not item.FirstOperand:
            item.FirstOperand = first
        return item, n + k
    return item, n

if __name__ == '__main__':
    src, dst = sys.argv[1:3]; guids = set(sys.argv[3:])
    f = ifcopenshell.open(src); res = {}; untouched = []
    for e in f.by_type('IfcProduct'):
        if e.GlobalId not in guids or not e.Representation: continue
        tot = 0
        for rep in e.Representation.Representations:
            items = list(rep.Items); new = []
            for it in items:
                ni, k = strip(it, 0); new.append(ni); tot += k
            if tot:
                rep.Items = new
                if all(not x.is_a('IfcBooleanResult') for x in new): rep.RepresentationType = 'SweptSolid'
        if tot: res[e.GlobalId] = tot
        else: untouched.append(e.GlobalId)
    f.write(dst)
    print(json.dumps({'unholed': res, 'untouched': untouched}))
