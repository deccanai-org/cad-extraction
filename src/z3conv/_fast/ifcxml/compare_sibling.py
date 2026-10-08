#!/usr/bin/env python3
"""compare_sibling.py - semantic comparison of an SPF converted from ifcXML with an independent SPF export of the same
model (e.g. buildingSMART / xBIM sample pairs), matched by GlobalId.

    compare_sibling.py CONVERTED.ifc SIBLING.ifc [--report R.json]

Per IfcRoot present in both: class, Name; per relationship: the GlobalIds referenced by every attribute (single or
aggregate) - this checks the ifcXML inverse-nesting reconstruction (RelatingObject / RelatedObjects ...); per
IfcProduct: the absolute placement matrix (max abs difference) and the representation item classes.
"""
import sys, json, argparse, collections
import ifcopenshell
import ifcopenshell.util.placement
import numpy as np


def gid_refs(v):
    if isinstance(v, ifcopenshell.entity_instance):
        return {v.GlobalId} if v.id() and v.is_a('IfcRoot') else set()
    if isinstance(v, (tuple, list)):
        r = set()
        for x in v:
            r |= gid_refs(x)
        return r
    return set()


def items(p):
    out = collections.Counter()
    if getattr(p, 'Representation', None) is None:
        return out
    for r in p.Representation.Representations:
        for it in r.Items:
            out[it.is_a()] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('conv')
    ap.add_argument('sibling')
    ap.add_argument('--report')
    a = ap.parse_args()
    f = ifcopenshell.open(a.conv)
    g = ifcopenshell.open(a.sibling)
    A = {e.GlobalId: e for e in f.by_type('IfcRoot')}
    B = {e.GlobalId: e for e in g.by_type('IfcRoot')}
    common = sorted(set(A) & set(B))
    rep = {'conv': a.conv, 'sibling': a.sibling, 'roots_conv': len(A), 'roots_sibling': len(B), 'common': len(common),
           'only_conv': sorted(set(A) - set(B))[:20], 'only_sibling': sorted(set(B) - set(A))[:20]}
    bad = collections.Counter()
    samples = []
    n_rel = n_prod = 0
    maxd = 0.0

    def fail(k, m):
        bad[k] += 1
        if len(samples) < 30:
            samples.append('%s: %s' % (k, m))
    for gid in common:
        x, y = A[gid], B[gid]
        if x.is_a() != y.is_a():
            fail('class', '%s %s vs %s' % (gid, x.is_a(), y.is_a()))
            continue
        if (x.Name or '') != (y.Name or ''):
            fail('name', '%s %r vs %r' % (gid, x.Name, y.Name))
        if x.is_a('IfcRelationship'):
            n_rel += 1
            for i in range(len(x)):
                ra, rb = gid_refs(x[i]), gid_refs(y[i])
                if ra != rb:
                    fail('relationship_refs', '%s %s attr %d: %d vs %d gids, missing %s extra %s' % (
                        gid, x.is_a(), i, len(ra), len(rb), sorted(rb - ra)[:3], sorted(ra - rb)[:3]))
        if x.is_a('IfcProduct'):
            n_prod += 1
            if x.ObjectPlacement is not None and y.ObjectPlacement is not None:
                ma = ifcopenshell.util.placement.get_local_placement(x.ObjectPlacement)
                mb = ifcopenshell.util.placement.get_local_placement(y.ObjectPlacement)
                d = float(np.max(np.abs(np.array(ma) - np.array(mb))))
                maxd = max(maxd, d)
                if d > 1e-6:
                    fail('placement', '%s %s max diff %.3g' % (gid, x.is_a(), d))
            elif (x.ObjectPlacement is None) != (y.ObjectPlacement is None):
                fail('placement_presence', gid)
            if items(x) != items(y):
                fail('representation_items', '%s %s %s vs %s' % (gid, x.is_a(), dict(items(x)), dict(items(y))))
    rep.update(relationships_compared=n_rel, products_compared=n_prod, placement_max_abs_diff=maxd,
               failures=dict(bad), samples=samples, verdict='pass' if not bad else 'differences')
    s = json.dumps(rep, indent=1)
    if a.report:
        open(a.report, 'w').write(s)
    print(s[:3000])


if __name__ == '__main__':
    main()
