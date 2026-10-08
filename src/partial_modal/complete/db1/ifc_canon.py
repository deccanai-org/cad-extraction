"""ifc_canon.py - per-product canonical geometry hash of an IFC (conda env python: ifcopenshell 0.9.0).

geometry(product) = its ObjectPlacement graph + Representation graph + every IfcOpeningElement voiding it (placement +
representation), serialised recursively by VALUE (entity type + attributes, references followed, no #ids), IfcRoot
GlobalId / OwnerHistory / Name / Description left out of the geometry. Two products have the same hash iff the IFC states
the same geometry for them (exact: floats compared bit for bit through repr). Name is reported separately.

hashes(path) -> {GlobalId: {'cls', 'name', 'geom': sha256 hex, 'openings': n}}"""
import hashlib
import ifcopenshell

SKIP_ROOT = {'GlobalId', 'OwnerHistory', 'Name', 'Description'}


class Canon:
    def __init__(self):
        self.memo = {}

    def ent(self, e):
        k = e.id()
        if k and k in self.memo:
            return self.memo[k]
        info = e.get_info(include_identifier=False, recursive=False)
        t = info.pop('type')
        root = e.is_a('IfcRoot')
        parts = [t]
        for a, v in info.items():
            if root and a in SKIP_ROOT:
                continue
            parts.append(a + '=' + self.val(v))
        s = hashlib.sha256('|'.join(parts).encode()).hexdigest()
        if k:
            self.memo[k] = s
        return s

    def val(self, v):
        if isinstance(v, ifcopenshell.entity_instance):
            return '@' + self.ent(v)
        if isinstance(v, (list, tuple)):
            return '[' + ','.join(self.val(x) for x in v) + ']'
        if isinstance(v, float):
            return repr(v)
        return repr(v)


def hashes(path):
    f = ifcopenshell.open(path)
    c = Canon()
    out = {}
    for p in f.by_type('IfcProduct'):
        if p.is_a('IfcOpeningElement') or p.is_a('IfcSpatialStructureElement') or p.is_a('IfcSpatialElement'):
            continue
        h = hashlib.sha256()
        h.update(b'P' + (c.ent(p.ObjectPlacement) if p.ObjectPlacement else '-').encode())
        h.update(b'R' + (c.ent(p.Representation) if p.Representation else '-').encode())
        ops = []
        for rel in (getattr(p, 'HasOpenings', None) or []):
            o = rel.RelatedOpeningElement
            ops.append((c.ent(o.ObjectPlacement) if o.ObjectPlacement else '-') + ':' + (c.ent(o.Representation) if o.Representation else '-'))
        for o in sorted(ops):
            h.update(b'O' + o.encode())
        out[p.GlobalId] = {'cls': p.is_a(), 'name': p.Name, 'geom': h.hexdigest(), 'openings': len(ops)}
    return out
