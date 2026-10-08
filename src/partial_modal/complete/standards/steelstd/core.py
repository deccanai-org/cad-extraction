"""StdItem: what every builder returns = GEOM (world mm) + colour + provenance (+ the exact target the build must hit).

colour rule (complete/INTERFACES.md): BLUE when every dimension comes from the cited table for a size the caller got
from the source data; AMBER as soon as one choice is an estimate (each estimate is listed in `estimates` and goes into
provenance.basis, prefixed 'estimated:'). The standard is cited in provenance.standard either way.
"""
from . import geom as G


def make_item(geometry, what, standard, estimates=(), evidence=None, simplifications=(), name='', designation='',
              role='accessory', ifc_class='IfcMechanicalFastener', target=True, tol_rel=0.005, tol_mm=0.5):
    estimates = [e for e in estimates if e]
    colour = 'AMBER' if estimates else 'BLUE'
    pv = {'what': what, 'standard': standard}
    if estimates:
        pv['basis'] = 'estimated: ' + '; '.join(estimates)
    ev = dict(evidence or {})
    if simplifications:
        ev['modelling_simplifications'] = list(simplifications)
    if ev:
        pv['evidence'] = ev
    it = {'geometry': geometry, 'colour': colour, 'provenance': pv, 'estimates': estimates,
          'part': {'role': role, 'ifc_class': ifc_class, 'name': name or what, 'designation': designation}}
    if target:
        it['target'] = G.target(geometry, tol_rel, tol_mm)
    return it


def solid(item):
    """the item's build123d Solid / Compound (needs build123d; the GEOM itself is kernel-free)"""
    return G.to_shape(item['geometry'])
